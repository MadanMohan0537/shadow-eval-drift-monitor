"""Deterministic minimization and retention policy applied before persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any


ALLOWED_FIELDS = frozenset({
    "event_id", "ts", "intent", "question", "context", "response",
    "synthetic_failure",
})
REQUIRED_FIELDS = frozenset({
    "event_id", "ts", "intent", "question", "context", "response",
})
FIELD_CLASSES = {
    "event_id": "metadata", "ts": "metadata", "intent": "metadata",
    "question": "content", "context": "content", "response": "content",
    "synthetic_failure": "test_fixture",
}

PATTERNS = (
    ("email", re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.I)),
    ("phone", re.compile(r"(?<!\w)(?:\+?\d[\d .()-]{7,}\d)(?!\w)")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.I)),
    ("api_key", re.compile(r"\b(?:sk|api)[-_][A-Za-z0-9_-]{8,}\b", re.I)),
)


@dataclass(frozen=True)
class PrivacyPolicy:
    retention_days: int = 30

    def __post_init__(self) -> None:
        if isinstance(self.retention_days, bool) or not isinstance(self.retention_days, int):
            raise ValueError("retention_days must be an integer")
        if not 1 <= self.retention_days <= 365:
            raise ValueError("retention_days must be between 1 and 365")


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("event ts must be nonempty ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("event ts must be valid ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def redact_text(value: str) -> tuple[str, int]:
    if not isinstance(value, str):
        raise ValueError("persisted event fields must be text")
    redactions = 0
    for label, pattern in PATTERNS:
        value, count = pattern.subn(f"[REDACTED_{label.upper()}]", value)
        redactions += count
    return value, redactions


def sanitize_event(event: dict[str, Any], policy: PrivacyPolicy) -> tuple[dict[str, Any], dict[str, dict[str, int]], str, int]:
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    missing = REQUIRED_FIELDS - set(event)
    if missing:
        raise ValueError("event missing required fields: " + ", ".join(sorted(missing)))
    clean: dict[str, Any] = {}
    usage: dict[str, dict[str, int]] = {}
    for field in sorted(ALLOWED_FIELDS & set(event)):
        value = event[field]
        if field == "synthetic_failure":
            if value not in (0, 1, False, True, None):
                raise ValueError("synthetic_failure must be boolean, 0, 1, or null")
            clean[field] = None if value is None else int(value)
            original = retained = 0 if value is None else 1
            redactions = 0
        else:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"event {field} must be nonempty text")
            original = len(value.encode("utf-8"))
            if FIELD_CLASSES[field] == "content":
                clean[field], redactions = redact_text(value)
            else:
                clean[field], redactions = value, 0
            retained = len(clean[field].encode("utf-8"))
        data_class = FIELD_CLASSES[field]
        bucket = usage.setdefault(data_class, {"original_bytes": 0, "retained_bytes": 0, "redactions": 0})
        bucket["original_bytes"] += original
        bucket["retained_bytes"] += retained
        bucket["redactions"] += redactions
    expiry = parse_timestamp(clean["ts"]) + timedelta(days=policy.retention_days)
    expires_at = expiry.isoformat()
    dropped_fields = len(set(event) - ALLOWED_FIELDS)
    return clean, usage, expires_at, dropped_fields
