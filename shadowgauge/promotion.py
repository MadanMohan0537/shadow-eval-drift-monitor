"""Append-only grader promotion decisions backed by SQLite."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .privacy import parse_timestamp


SCHEMA = """
CREATE TABLE IF NOT EXISTS grader_policies (
  grader TEXT PRIMARY KEY, state TEXT NOT NULL,
  bridge_sha256 TEXT, thresholds_json TEXT, created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_grader
  ON grader_policies(state) WHERE state='active';
CREATE TABLE IF NOT EXISTS grader_policy_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, grader TEXT NOT NULL,
  from_state TEXT, to_state TEXT NOT NULL, actor TEXT NOT NULL,
  occurred_at TEXT NOT NULL, reason TEXT NOT NULL,
  bridge_sha256 TEXT, thresholds_json TEXT NOT NULL
);
"""


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise ValueError(f"{label} must be 1–200 characters")
    return value.strip()


def _time(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("occurred_at must be an ISO-8601 timestamp")
    return parse_timestamp(value).isoformat()


class PromotionLedger:
    """Persist one active grader and every state transition that selected it."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _event(self, db: sqlite3.Connection, grader: str, before: str | None,
               after: str, actor: str, occurred_at: str, reason: str,
               bridge_sha: str | None, thresholds: dict) -> None:
        db.execute("INSERT INTO grader_policy_events (grader,from_state,to_state,actor,occurred_at,reason,bridge_sha256,thresholds_json) VALUES (?,?,?,?,?,?,?,?)",
                   (grader, before, after, actor, occurred_at, reason, bridge_sha,
                    json.dumps(thresholds, sort_keys=True, separators=(",", ":"))))

    def initialize(self, grader: str, actor: str, occurred_at: str,
                   reason: str = "record existing active grader") -> dict:
        grader, actor, occurred_at, reason = (_text(grader, "grader"),
                                               _text(actor, "actor"),
                                               _time(occurred_at),
                                               _text(reason, "reason"))
        with self._connect() as db:
            if db.execute("SELECT 1 FROM grader_policies LIMIT 1").fetchone():
                raise ValueError("ledger is already initialized")
            db.execute("INSERT INTO grader_policies VALUES (?,?,?,?,?)",
                       (grader, "active", None, "{}", occurred_at))
            self._event(db, grader, None, "active", actor, occurred_at, reason, None, {})
        return self.snapshot()

    def propose(self, bridge: dict, actor: str, occurred_at: str,
                reason: str = "propose grader after frozen overlap") -> dict:
        actor, occurred_at, reason = (_text(actor, "actor"), _time(occurred_at),
                                      _text(reason, "reason"))
        required = {"old_grader", "new_grader", "status", "thresholds", "overall",
                    "segments", "coverage_debt", "violations", "limitation"}
        if not isinstance(bridge, dict) or set(bridge) != required:
            raise ValueError("bridge analysis has unsupported or missing fields")
        old, new = _text(bridge["old_grader"], "old_grader"), _text(bridge["new_grader"], "new_grader")
        if bridge["status"] not in {"compatible", "quarantine"} or not isinstance(bridge["thresholds"], dict):
            raise ValueError("bridge status or thresholds are invalid")
        bridge_sha = _digest(bridge)
        thresholds_json = json.dumps(bridge["thresholds"], sort_keys=True, separators=(",", ":"))
        with self._connect() as db:
            active = db.execute("SELECT grader FROM grader_policies WHERE state='active'").fetchone()
            if active is None or active["grader"] != old:
                raise ValueError("bridge old grader must be the uniquely active grader")
            if db.execute("SELECT 1 FROM grader_policies WHERE grader=?", (new,)).fetchone():
                raise ValueError("proposed grader already exists; evidence is immutable")
            db.execute("INSERT INTO grader_policies VALUES (?,?,?,?,?)",
                       (new, "proposed", bridge_sha, thresholds_json, occurred_at))
            self._event(db, new, None, "proposed", actor, occurred_at, reason,
                        bridge_sha, bridge["thresholds"])
            if bridge["status"] == "quarantine":
                db.execute("UPDATE grader_policies SET state='quarantined' WHERE grader=?", (new,))
                self._event(db, new, "proposed", "quarantined", actor, occurred_at,
                            "bridge thresholds or coverage failed", bridge_sha,
                            bridge["thresholds"])
        return self.snapshot()

    def approve(self, grader: str, actor: str, occurred_at: str, reason: str) -> dict:
        return self._transition(grader, "proposed", "approved", actor, occurred_at, reason)

    def activate(self, grader: str, actor: str, occurred_at: str, reason: str) -> dict:
        grader, actor, occurred_at, reason = (_text(grader, "grader"), _text(actor, "actor"),
                                               _time(occurred_at), _text(reason, "reason"))
        with self._connect() as db:
            row = db.execute("SELECT * FROM grader_policies WHERE grader=?", (grader,)).fetchone()
            if row is None or row["state"] != "approved":
                raise ValueError("only an approved grader can become active")
            active = db.execute("SELECT * FROM grader_policies WHERE state='active'").fetchone()
            if active is None:
                raise ValueError("ledger has no active grader")
            thresholds = json.loads(row["thresholds_json"])
            active_thresholds = json.loads(active["thresholds_json"])
            db.execute("UPDATE grader_policies SET state='superseded' WHERE grader=?", (active["grader"],))
            self._event(db, active["grader"], "active", "superseded", actor, occurred_at,
                        f"superseded by {grader}", active["bridge_sha256"], active_thresholds)
            db.execute("UPDATE grader_policies SET state='active' WHERE grader=?", (grader,))
            self._event(db, grader, "approved", "active", actor, occurred_at, reason,
                        row["bridge_sha256"], thresholds)
        return self.snapshot()

    def _transition(self, grader: str, before: str, after: str, actor: str,
                    occurred_at: str, reason: str) -> dict:
        grader, actor, occurred_at, reason = (_text(grader, "grader"), _text(actor, "actor"),
                                               _time(occurred_at), _text(reason, "reason"))
        with self._connect() as db:
            row = db.execute("SELECT * FROM grader_policies WHERE grader=?", (grader,)).fetchone()
            if row is None or row["state"] != before:
                raise ValueError(f"grader must be {before} before it can be {after}")
            db.execute("UPDATE grader_policies SET state=? WHERE grader=?", (after, grader))
            self._event(db, grader, before, after, actor, occurred_at, reason,
                        row["bridge_sha256"], json.loads(row["thresholds_json"]))
        return self.snapshot()

    def snapshot(self) -> dict:
        with self._connect() as db:
            policies = [dict(row) for row in db.execute(
                "SELECT grader,state,bridge_sha256,thresholds_json,created_at FROM grader_policies ORDER BY created_at,grader")]
            events = [dict(row) for row in db.execute(
                "SELECT id,grader,from_state,to_state,actor,occurred_at,reason,bridge_sha256,thresholds_json FROM grader_policy_events ORDER BY id")]
        for row in policies + events:
            row["thresholds"] = json.loads(row.pop("thresholds_json"))
        active = [row["grader"] for row in policies if row["state"] == "active"]
        return {"active_grader": active[0] if len(active) == 1 else None,
                "active_count": len(active), "policies": policies, "events": events}
