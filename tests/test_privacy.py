import tempfile
import unittest
from pathlib import Path
import sqlite3

from shadowgauge.privacy import PrivacyPolicy, sanitize_event
from shadowgauge.store import Store
from shadowgauge.worker import run_batch


def event(event_id="evt-private", ts="2026-01-01T00:00:00+00:00"):
    return {
        "event_id": event_id,
        "ts": ts,
        "intent": "account",
        "question": "Email me at person@example.com or +1 (212) 555-0199",
        "context": "Authorization: Bearer abcdefghijklmnop",
        "response": "Use api_testsecret12345 for access",
        "synthetic_failure": 0,
        "debug_trace": "must never persist",
    }


class PrivacyTests(unittest.TestCase):
    def test_secrets_redacted_and_unknown_fields_dropped_before_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"private.db"
            store = Store(path)
            store.enqueue(event(), .25, "new_intent")
            raw = path.read_bytes()
            for secret in (b"person@example.com", b"212) 555", b"abcdefghijklmnop",
                           b"testsecret12345", b"must never persist"):
                self.assertNotIn(secret, raw)
            row = store.pending()[0]
            self.assertIn("[REDACTED_EMAIL]", row["question"])
            self.assertIn("[REDACTED_BEARER_TOKEN]", row["context"])

    def test_privacy_summary_reports_classes_bytes_and_redactions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/"usage.db", PrivacyPolicy(14))
            store.enqueue(event(), .25, "new_intent")
            report = store.privacy_summary()
            self.assertEqual(report["retention_days"], 14)
            self.assertEqual(report["dropped_fields"], 1)
            self.assertGreaterEqual(report["classes"]["content"]["redactions"], 4)
            self.assertGreater(report["classes"]["content"]["retained_bytes"], 0)

    def test_pruning_removes_expired_event_grade_and_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"expiry.db"
            store = Store(path, PrivacyPolicy(7))
            store.enqueue(event(), .25, "new_intent")
            self.assertEqual(run_batch(store), 1)
            result = store.prune_expired("2026-01-08T00:00:00+00:00")
            self.assertEqual(result, {"expired_events_deleted": 1, "grades_deleted": 1})
            self.assertEqual(store.summary()["sampled"], 0)
            self.assertEqual(store.privacy_summary()["classes"], {})

    def test_unexpired_event_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/"future.db", PrivacyPolicy(7))
            store.enqueue(event(), .25, "new_intent")
            self.assertEqual(store.prune_expired("2026-01-07T23:59:59+00:00")["expired_events_deleted"], 0)

    def test_invalid_policy_and_probability_fail_closed(self):
        for days in (0, 366, 1.5, True):
            with self.assertRaises(ValueError):
                PrivacyPolicy(days)
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/"invalid.db")
            for probability in (0, 1.1, float("nan"), True):
                with self.assertRaises(ValueError):
                    store.enqueue(event(), probability, "bad")

    def test_missing_fields_and_invalid_timestamps_fail_closed(self):
        broken = event()
        broken.pop("response")
        with self.assertRaisesRegex(ValueError, "missing"):
            sanitize_event(broken, PrivacyPolicy())
        with self.assertRaisesRegex(ValueError, "ISO-8601"):
            sanitize_event(event(ts="not-a-date"), PrivacyPolicy())

    def test_existing_database_is_redacted_and_given_expiry_on_open(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"legacy.db"
            with sqlite3.connect(path) as db:
                db.execute("""CREATE TABLE sampled_events (
                    event_id TEXT PRIMARY KEY, ts TEXT NOT NULL, intent TEXT NOT NULL,
                    question TEXT NOT NULL, context TEXT NOT NULL, response TEXT NOT NULL,
                    inclusion_probability REAL NOT NULL, sample_reason TEXT NOT NULL,
                    synthetic_failure INTEGER, status TEXT NOT NULL DEFAULT 'pending')""")
                db.execute("INSERT INTO sampled_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                           ("legacy-1", "2026-01-01", "account", "person@example.com",
                            "Bearer abcdefghijklmnop", "safe", .1, "fixed", 0, "pending"))
            store = Store(path, PrivacyPolicy(10))
            row = store.pending()[0]
            self.assertEqual(row["question"], "[REDACTED_EMAIL]")
            self.assertEqual(row["context"], "[REDACTED_BEARER_TOKEN]")
            self.assertEqual(row["expires_at"], "2026-01-11T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
