"""SQLite-backed event queue, grades, windows, and alerts."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from .privacy import PrivacyPolicy, sanitize_event


SCHEMA = """
CREATE TABLE IF NOT EXISTS sampled_events (
  event_id TEXT PRIMARY KEY, ts TEXT NOT NULL, intent TEXT NOT NULL,
  question TEXT NOT NULL, context TEXT NOT NULL, response TEXT NOT NULL,
  inclusion_probability REAL NOT NULL, sample_reason TEXT NOT NULL,
  synthetic_failure INTEGER, status TEXT NOT NULL DEFAULT 'pending',
  expires_at TEXT
);
CREATE TABLE IF NOT EXISTS grades (
  event_id TEXT PRIMARY KEY REFERENCES sampled_events(event_id),
  groundedness REAL NOT NULL, unanswered INTEGER NOT NULL,
  harmful INTEGER NOT NULL, failure INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
  window_name TEXT NOT NULL, psi REAL NOT NULL, message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS privacy_usage (
  event_id TEXT NOT NULL, data_class TEXT NOT NULL,
  original_bytes INTEGER NOT NULL, retained_bytes INTEGER NOT NULL,
  redactions INTEGER NOT NULL, dropped_fields INTEGER NOT NULL,
  PRIMARY KEY(event_id, data_class)
);
"""


class Store:
    def __init__(self, path: str | Path, privacy_policy: PrivacyPolicy | None = None) -> None:
        self.path = str(path)
        self.privacy_policy = privacy_policy or PrivacyPolicy()
        with self.connect() as db:
            db.executescript(SCHEMA)
            columns = {row[1] for row in db.execute("PRAGMA table_info(sampled_events)")}
            if "expires_at" not in columns:
                db.execute("ALTER TABLE sampled_events ADD COLUMN expires_at TEXT")
            self._migrate_existing_rows(db)

    def _migrate_existing_rows(self, db: sqlite3.Connection) -> None:
        """Apply the current redaction/TTL boundary to databases from earlier releases."""
        rows = db.execute(
            """SELECT event_id,ts,intent,question,context,response,synthetic_failure
               FROM sampled_events""").fetchall()
        for row in rows:
            event = dict(row)
            clean, usage, expires_at, _ = sanitize_event(event, self.privacy_policy)
            db.execute(
                """UPDATE sampled_events SET ts=?,intent=?,question=?,context=?,response=?,
                   synthetic_failure=?,expires_at=? WHERE event_id=?""",
                (clean["ts"], clean["intent"], clean["question"], clean["context"],
                 clean["response"], clean.get("synthetic_failure"), expires_at,
                 clean["event_id"]),
            )
            present = db.execute("SELECT 1 FROM privacy_usage WHERE event_id=? LIMIT 1",
                                 (clean["event_id"],)).fetchone()
            if not present:
                for data_class, values in usage.items():
                    db.execute("INSERT INTO privacy_usage VALUES (?,?,?,?,?,0)",
                               (clean["event_id"], data_class, values["original_bytes"],
                                values["retained_bytes"], values["redactions"]))

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def enqueue(self, event: dict[str, Any], probability: float, reason: str) -> None:
        if isinstance(probability, bool) or not isinstance(probability, (int, float)) or not math.isfinite(probability) or not 0 < probability <= 1:
            raise ValueError("inclusion probability must be finite and in (0, 1]")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("sample reason must be nonempty text")
        clean, usage, expires_at, dropped_fields = sanitize_event(event, self.privacy_policy)
        with self.connect() as db:
            inserted = db.execute(
                """INSERT OR IGNORE INTO sampled_events
                (event_id,ts,intent,question,context,response,inclusion_probability,
                 sample_reason,synthetic_failure,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (clean["event_id"], clean["ts"], clean["intent"], clean["question"],
                 clean["context"], clean["response"], probability, reason,
                 clean.get("synthetic_failure"), expires_at),
            )
            if inserted.rowcount:
                for data_class, values in usage.items():
                    db.execute("INSERT INTO privacy_usage VALUES (?,?,?,?,?,?)",
                               (clean["event_id"], data_class, values["original_bytes"],
                                values["retained_bytes"], values["redactions"],
                                dropped_fields if data_class == "metadata" else 0))

    def pending(self, limit: int = 100) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute("SELECT * FROM sampled_events WHERE status='pending' ORDER BY ts LIMIT ?", (limit,)))

    def save_grade(self, event_id: str, groundedness: float, unanswered: bool,
                   harmful: bool, failure: bool) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO grades VALUES (?,?,?,?,?)",
                       (event_id, groundedness, int(unanswered), int(harmful), int(failure)))
            db.execute("UPDATE sampled_events SET status='graded' WHERE event_id=?", (event_id,))

    def graded(self) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute("SELECT e.*, g.groundedness, g.failure FROM sampled_events e JOIN grades g USING(event_id) ORDER BY e.ts"))

    def prune_expired(self, now: str) -> dict[str, int]:
        """Delete expired event content, grades, and byte-accounting rows."""
        from .privacy import parse_timestamp
        normalized = parse_timestamp(now).isoformat()
        with self.connect() as db:
            ids = [row[0] for row in db.execute(
                "SELECT event_id FROM sampled_events WHERE expires_at IS NOT NULL AND expires_at<=?",
                (normalized,))]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                grades = db.execute(f"DELETE FROM grades WHERE event_id IN ({placeholders})", ids).rowcount
                db.execute(f"DELETE FROM privacy_usage WHERE event_id IN ({placeholders})", ids)
                events = db.execute(f"DELETE FROM sampled_events WHERE event_id IN ({placeholders})", ids).rowcount
            else:
                events = grades = 0
        return {"expired_events_deleted": events, "grades_deleted": grades}

    def privacy_summary(self) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT data_class, SUM(original_bytes), SUM(retained_bytes),
                          SUM(redactions), MAX(dropped_fields)
                   FROM privacy_usage GROUP BY data_class ORDER BY data_class""").fetchall()
        classes = {row[0]: {"original_bytes": row[1], "retained_bytes": row[2],
                            "redactions": row[3]} for row in rows}
        return {"classes": classes,
                "dropped_fields": sum(row[4] for row in rows),
                "retention_days": self.privacy_policy.retention_days}

    def add_alert(self, created_at: str, window: str, psi: float, message: str) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO alerts(created_at,window_name,psi,message) VALUES (?,?,?,?)",
                       (created_at, window, psi, message))

    def summary(self) -> dict[str, Any]:
        with self.connect() as db:
            queued = db.execute("SELECT COUNT(*) FROM sampled_events").fetchone()[0]
            graded = db.execute("SELECT COUNT(*) FROM grades").fetchone()[0]
            failures = db.execute("SELECT COUNT(*) FROM grades WHERE failure=1").fetchone()[0]
            alerts = [dict(r) for r in db.execute("SELECT * FROM alerts ORDER BY id")]
        return {"sampled": queued, "graded": graded, "failures": failures,
                "alerts": alerts, "privacy": self.privacy_summary()}

    def export_json(self) -> str:
        return json.dumps(self.summary(), indent=2)

