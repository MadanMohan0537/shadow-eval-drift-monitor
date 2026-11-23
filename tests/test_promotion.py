import tempfile
import unittest
from pathlib import Path

from shadowgauge.bridge import analyze_bridge
from shadowgauge.cli import main
from shadowgauge.promotion import PromotionLedger
from shadowgauge.simulation import generate_bridge_overlap


class PromotionLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/"ledger.db"
        self.ledger = PromotionLedger(self.path)
        self.ledger.initialize("lexical-v1", "ops-a", "2026-11-23T08:00:00-05:00")

    def tearDown(self):
        self.tmp.cleanup()

    def test_compatible_policy_can_be_approved_and_activated(self):
        report = analyze_bridge(generate_bridge_overlap(False))
        self.ledger.propose(report, "eval-a", "2026-11-23T08:05:00-05:00")
        self.ledger.approve(report["new_grader"], "owner-b", "2026-11-23T08:10:00-05:00", "reviewed overlap")
        result = self.ledger.activate(report["new_grader"], "ops-c", "2026-11-23T08:15:00-05:00", "deploy completed")
        self.assertEqual(result["active_grader"], "lexical-v2-compatible")
        self.assertEqual(result["active_count"], 1)
        self.assertEqual([event["to_state"] for event in result["events"]],
                         ["active", "proposed", "approved", "superseded", "active"])

    def test_failed_bridge_is_quarantined_and_cannot_be_approved(self):
        report = analyze_bridge(generate_bridge_overlap(True))
        result = self.ledger.propose(report, "eval-a", "2026-11-23T08:05:00-05:00")
        policy = next(row for row in result["policies"] if row["grader"] == report["new_grader"])
        self.assertEqual(policy["state"], "quarantined")
        with self.assertRaisesRegex(ValueError, "proposed"):
            self.ledger.approve(report["new_grader"], "owner-b", "2026-11-23T08:10:00-05:00", "ignore failure")

    def test_stale_bridge_and_duplicate_proposal_are_rejected(self):
        report = analyze_bridge(generate_bridge_overlap(False))
        self.ledger.propose(report, "eval-a", "2026-11-23T08:05:00-05:00")
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.ledger.propose(report, "eval-a", "2026-11-23T08:06:00-05:00")
        stale = analyze_bridge(generate_bridge_overlap(True))
        stale["old_grader"] = "not-active"
        with self.assertRaisesRegex(ValueError, "active"):
            self.ledger.propose(stale, "eval-a", "2026-11-23T08:07:00-05:00")

    def test_invalid_identity_and_time_fail_closed(self):
        report = analyze_bridge(generate_bridge_overlap(False))
        with self.assertRaises(ValueError):
            self.ledger.propose(report, "", "2026-11-23T08:05:00-05:00")
        with self.assertRaises(ValueError):
            self.ledger.propose(report, "eval-a", "not-a-time")

    def test_cli_demo_writes_auditable_report(self):
        out = Path(self.tmp.name)/"promotion.json"
        db = Path(self.tmp.name)/"demo.db"
        self.assertEqual(main(["promotion-demo", "--db", str(db), "--output", str(out)]), 0)
        import json
        report = json.loads(out.read_text())
        self.assertEqual(report["active_count"], 1)
        self.assertEqual(report["active_grader"], "lexical-v2-compatible")
        self.assertIn("quarantined", {row["state"] for row in report["policies"]})


if __name__ == "__main__":
    unittest.main()
