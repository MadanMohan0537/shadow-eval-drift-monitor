# Rigorous feature backlog

This backlog compares proposed work with the MVP so plans are not confused with shipped behavior. The sampling-bias inspector, grader-version bridge, and local privacy boundary are implemented. Other items remain planned.

| Priority | Feature | Concrete user problem | Intended behavior | Dependencies | Success test | Risks and tradeoffs |
|---|---|---|---|---|---|---|
| P1 shipped | Sampling-bias inspector | Adaptive sampling makes a raw average look like population quality | Store inclusion probabilities; show raw and capped inverse-probability estimates with ESS | Sampling policy + event store | On skewed synthetic traffic, weighted estimate recovers the known mix more closely than raw | Tiny probabilities inflate variance; clipping lowers variance but adds bias |
| P2 shipped | Grader-version bridge | A grader upgrade can look like an app regression | Double-grade a frozen overlap batch; isolate grader-only shifts; preserve segment breakdowns and quarantine incompatible versions | Versioned grader names + frozen overlap artifact | Seeded grader-only PSI shift creates measurement hold, not product incident; compatible control still detects app regression | Double grading costs more; overlap may miss rare intents; hold pauses product alerting |
| P2 shipped | Privacy budget and field redaction | Shadow copies may retain secrets or personal data | Allowlist fields, redact common patterns before SQL, attach TTL, migrate older rows, count bytes by class, and explicitly prune expiry | Versioned local policy + SQLite audit rows | Seeded secrets never reach SQLite; older rows are redacted on open; expired event, grade, and audit rows disappear | Regex redaction misses context and may over-redact; pruning requires scheduling; deleted SQLite pages/backups need separate handling |
| P2 | Sequential false-alarm control | Repeated window checks inflate false positives | Calibrate alert thresholds across repeated tests and surface the error budget | Historical clean replay | Clean 30-day replay stays under target false-alert rate while injected regressions remain detectable | More conservative thresholds delay detection |
| P3 | Coverage allocator | Fixed new-intent oversampling can exhaust the budget early | Allocate the daily budget by novelty, volume, uncertainty, and minimum segment floors | Intent clustering, shared atomic counter | Rare critical segments meet coverage floors without exceeding cap | Gaming or unstable clusters can divert budget |
| P3 | Delayed-label audit | Proxy graders can drift away from real customer outcomes | Join later refunds, escalations, or human reviews to grader predictions | Consent-safe label pipeline | Monthly precision/recall report catches seeded grader decay | Labels are delayed, selective, and potentially sensitive |
| P3 | Incident explainer | A PSI number does not tell an operator what changed | Rank changed intents, grader dimensions, and representative redacted examples | Segment aggregates, privacy layer | On an injected intent regression, correct segment ranks first | Examples may leak data or imply false causality |
| P3 | Queue health SLO | A quiet monitor can silently stop grading | Track queue age, processing lag, throughput, and dead letters separately from model quality | Worker heartbeats | Killed-worker drill alerts before quality data becomes stale | More operational alerts can create noise |
| P4 | Signed policy snapshots | Teams cannot reproduce why an old request was selected or alerted | Persist immutable sampler, grader, and threshold versions with each decision | Config serialization, release process | Historical replay reproduces the original decision byte-for-byte | Storage and migration complexity |

## Next slice

Build the bridge promotion ledger next so a compatible overlap records which grader was
actually proposed, approved, and activated. Follow with sequential false-alarm control.

## Further rigorous additions — planned

| Priority | Feature | Problem and behavior | Dependencies | Success test | Risks/tradeoffs |
|---|---|---|---|---|---|
| P1 | Bridge promotion ledger | A compatible report does not prove which grader was activated | Persist proposed, quarantined, approved and active transitions with immutable thresholds | Historical incident identifies exactly one active grader policy | Workflow state adds operator burden and requires operator identity policy |
| P2 | Redaction canary corpus | Pattern tests do not cover contextual or encoded sensitive data | Run a frozen canary corpus through each privacy-policy revision and publish misses/over-redactions | Reviewed synthetic canaries and policy versioning | A deliberately hidden canary is detected without regressing benign text | Canary success can create false confidence outside its patterns |
| P2 | Deletion-verification drill | Row deletion does not prove backups and free pages are clean | Verify retention across primary DB, compaction, exports and backup lifecycle | Backup inventory and operational runner | Seeded expired marker is absent from every declared storage surface | Vacuuming and backup rotation add I/O and operational cost |
| P2 | Bridge uncertainty bands | Point thresholds are brittle on small overlaps | Bootstrap paired mean/flip shifts per intent and suppress conclusions with low support | Clean repeated fixtures meet predeclared false-quarantine budget | Wide bands can block upgrades |
| P2 | Sentinel intent set | Traffic overlap may omit rare critical intents | Require curated safety/billing sentinels alongside traffic-derived overlap | Removing a sentinel segment always creates coverage debt | Sentinels can become stale |
| P3 | Dual-stream incident replay | Quarantine pauses current alerts | Reprocess quarantined windows under both graders after approval | Replayed decisions preserve original evidence and show attribution | Storage and operational complexity |

