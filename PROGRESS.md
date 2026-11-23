# Existing-project improvement record

## 2026-11-23 — ShadowGauge

- Reinspected source, 27 tests, CI, README, architecture, backlog and Project Lab #3 extensions.
- Shipped the grader promotion ledger with immutable bridge hashes and threshold snapshots.
- Added proposed, quarantined, approved, active and superseded transitions; stale and duplicate proposals fail, and SQLite enforces exactly one active grader.
- Added a deterministic quarantine-and-promotion demo, five regression/CLI tests and a CI command; 32 tests pass locally.
- Documented that actor labels and timestamps are self-asserted and that the ledger records authorization intent rather than deploying code.
- No repository was created or renamed.
- Next project in the rotation: CaseFoundry (#4).
- Next ShadowGauge priority: sequential false-alarm control, followed by bridge uncertainty bands.

## 2026-11-07 — ShadowGauge

- Reinspected source, 20 tests, CI, README, architecture, backlog and Project Lab extensions.
- Shipped pre-persistence field allowlisting and typed redaction for common identifiers and credentials.
- Added 1–365 day event-time TTLs, older-database migration, explicit pruning, and retained-byte accounting by data class.
- Added seven privacy/correctness regression tests; 27 tests pass locally.
- Corrected the CI badge to the existing public repository; no repository was created or renamed.
- Next project in the rotation: CaseFoundry (#4).
- Next ShadowGauge priority: bridge promotion ledger, then sequential false-alarm control.

## 2026-10-22 — ShadowGauge

- Inspected source, 13 tests, CI, README, architecture, backlog and project notes.
- Shipped the grader-version bridge with frozen paired overlap and intent coverage checks.
- Added measurement-hold versus product-incident attribution and a reproducible CLI demo.
- Added seven focused tests; 20 tests pass locally.
- No new repository was created.
- Next project in the rotation: CaseFoundry (#4).
- Next ShadowGauge priority: privacy redaction and retention, then bridge promotion state.
