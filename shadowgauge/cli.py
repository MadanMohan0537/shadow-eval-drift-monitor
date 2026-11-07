"""Command-line interface for replay, workers, and reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .monitoring import DriftGate, psi
from .sampling import AdaptiveSampler, estimate_failure_rate
from .simulation import generate_events
from .store import Store
from .worker import run_batch
from .bridge import analyze_bridge, classify_product_drift
from .simulation import generate_bridge_overlap
from .privacy import PrivacyPolicy


def simulate(db_path: str, output: str, count: int) -> dict:
    store = Store(db_path)
    sampler = AdaptiveSampler(base_rate=0.12, new_intent_rate=0.35,
                              known_intents={"billing", "account"}, daily_cap=count)
    population = generate_events(count=count, regression_at=int(count * 0.65))
    sampled_truth = []
    for event in population:
        day = event["ts"][:10]
        decision = sampler.decide(event["event_id"], event["intent"], day)
        if decision.included:
            store.enqueue(event, decision.probability, decision.reason)
            sampled_truth.append((bool(event["synthetic_failure"]), decision.probability))
    while run_batch(store, 200):
        pass
    estimate = estimate_failure_rate(sampled_truth)
    rows = store.graded()
    pivot = max(1, len(rows) // 2)
    baseline = [r["groundedness"] for r in rows[:pivot]]
    later = [r["groundedness"] for r in rows[pivot:]]
    # Split the changed period in two so the consecutive-window gate is exercised.
    half = max(1, len(later) // 2)
    gate = DriftGate(threshold=0.2, consecutive_required=2, cooldown_windows=2)
    scores = [psi(baseline, later[:half]), psi(baseline, later[half:])]
    alerted = False
    for index, score in enumerate(scores, start=1):
        if gate.evaluate(score):
            alerted = True
            store.add_alert(population[-1]["ts"], f"regression-{index}", score,
                            "Groundedness distribution shifted for two consecutive windows")
    population_rate = sum(e["synthetic_failure"] for e in population) / len(population)
    report = {
        **store.summary(),
        "population_failure_rate": round(population_rate, 4),
        "raw_sample_failure_rate": round(estimate.raw_rate, 4),
        "weighted_failure_rate": round(estimate.weighted_rate, 4),
        "effective_sample_size": round(estimate.effective_sample_size, 1),
        "psi_windows": [round(s, 4) for s in scores],
        "alert_fired": alerted,
    }
    Path(output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shadowgauge")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("simulate", help="run reproducible traffic and regression replay")
    demo.add_argument("--db", default="shadowgauge.db")
    demo.add_argument("--output", default="report.json")
    demo.add_argument("--count", type=int, default=800)
    work = sub.add_parser("worker", help="grade one pending batch")
    work.add_argument("--db", default="shadowgauge.db")
    work.add_argument("--limit", type=int, default=100)
    bridge = sub.add_parser("bridge-demo", help="reproduce a grader-only shift quarantine")
    bridge.add_argument("--output", default="bridge-report.json")
    prune = sub.add_parser("prune", help="delete sampled content past its retention deadline")
    prune.add_argument("--db", default="shadowgauge.db")
    prune.add_argument("--now", required=True, help="ISO-8601 cutoff time")
    prune.add_argument("--retention-days", type=int, default=30)
    args = parser.parse_args(argv)
    if args.command == "simulate":
        print(json.dumps(simulate(args.db, args.output, args.count), indent=2))
    elif args.command == "worker":
        print(json.dumps({"processed": run_batch(Store(args.db), args.limit)}))
    elif args.command == "bridge-demo":
        overlap = generate_bridge_overlap(grader_shift=True)
        analysis = analyze_bridge(overlap)
        baseline = [row["old_score"] for row in overlap["rows"]]
        current = [row["new_score"] for row in overlap["rows"]]
        report = {**analysis, "drift_decision": classify_product_drift(
            baseline, current, analysis)}
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    else:
        store = Store(args.db, PrivacyPolicy(args.retention_days))
        print(json.dumps(store.prune_expired(args.now), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

