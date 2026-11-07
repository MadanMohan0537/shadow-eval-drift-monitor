# Architecture and operating model

## Boundary

ShadowGauge is a local-first reference implementation. It does not intercept or answer production requests. A host application hands it a copy after returning its response; selected copies enter SQLite and a separate worker grades them.

## Data contract

Required event fields are `event_id`, ISO-8601 `ts`, `intent`, `question`, `context`, and `response`. Synthetic replays may add `synthetic_failure`; production integrations must not pretend to have this ground-truth label. Every sampled row also stores `inclusion_probability` and `sample_reason`. Unknown event fields are dropped before persistence.

## Decisions

| Decision | Reason | Tradeoff |
|---|---|---|
| SHA-256 Bernoulli sampling | Replays are deterministic and auditable | A caller must provide stable, non-secret IDs |
| Oversample new intents | Shortens time to first signal | Raw sample averages become biased |
| Hájek estimator | Easier-to-read bounded rate than an unnormalized total | Depends on correct inclusion probabilities |
| Cap inverse weights at 20 | Prevents rare records dominating | Introduces bias; report ESS and clip count |
| SQLite queue | Zero-service setup and durable local demo | Single-node throughput ceiling |
| Fixed-bin PSI | Detects distribution changes, not just mean changes | Needs calibrated bins and adequate counts |
| Two-window gate | Reduces one-window false alarms | Adds one window of detection latency |
| Redact before SQL | Avoid known identifier/credential patterns reaching the database | Pattern coverage is incomplete and may over-redact |
| Event-time TTL | Makes retention reproducible in replays and backfills | Late events may be immediately eligible for deletion |

## Failure modes

- If the worker stops, pending rows remain durable; queue depth should be alerted on.
- If event IDs repeat, `INSERT OR IGNORE` prevents duplicate grading.
- If probabilities are omitted or wrong, weighted estimates are invalid. The API rejects probabilities outside `(0, 1]`.
- If a daily cap is reached, decisions carry `daily_cap` as the reason but are not queued. The host should count rejected decisions for coverage reporting.
- If a grader changes, current scores are not directly comparable. The bridge requires a frozen overlap before product attribution.
- If the prune command is not scheduled, expired rows remain. Backups, WAL files, and freed SQLite pages require separate lifecycle controls.

## Privacy and retention boundary

`sanitize_event` accepts only the documented schema and transforms content fields before
the insert. It replaces detected emails, phone-like strings, bearer tokens, and common API
key forms with typed placeholders. Metadata is validated but not pattern-redacted because
timestamps and stable IDs must retain their meaning. Per-event audit rows record original
and retained UTF-8 bytes plus redaction and dropped-field counts by data class.

Expiry is calculated from the normalized event time and a validated 1–365 day policy.
`prune_expired` deletes matching grades, audit rows, and sampled content in one transaction.
When an older database is opened, existing content receives the current redaction and TTL
policy before normal use. Regexes are not a security proof: contextual identifiers,
obfuscated values, free-form secrets, SQLite free pages, WAL files, exports, and backups are
outside this MVP's guarantee.

## Grader-version bridge

Before promotion, the old and proposed graders score the same frozen events.
`analyze_bridge` validates unique IDs, bounded scores, distinct version names and
minimum coverage per intent. It reports paired mean shifts and pass/fail flips overall
and by segment. Any coverage or compatibility violation quarantines the transition.
`classify_product_drift` labels a shifted window `MEASUREMENT_HOLD` while the bridge
is quarantined, preventing a grader-only change from becoming a product incident.
This does not authenticate versions, persist approval state or prove coverage beyond
the supplied overlap.

## Production hardening path

Add schema-specific DLP, scheduled deletion verification across backups, a shared queue and budget counter, version all policies and graders, enforce minimum segment counts, and connect incident records to an authenticated delivery adapter. Validate every threshold on a frozen replay plus human-reviewed labels before enabling paging.

