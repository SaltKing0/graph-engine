"""Prespecified pair metrics. Unknown and unreviewed labels never become negatives."""
from __future__ import annotations

from collections import Counter


def score(rows: list[dict], labels: dict) -> dict:
    counts: Counter = Counter()
    error_cases = set()
    for row in rows:
        alerts: dict[str, list[dict]] = {}
        for alert in row["alerts"]:
            alerts.setdefault(alert["decision_id"], []).append(alert)
        counts["raw_alerts"] += len(row["alerts"])
        for did in row["eligible_decisions"]:
            counts["attempted_pairs"] += 1
            label = labels["pairs"][f"{row['event_id']}/{did}"]
            outcome = label["outcome"]
            counts[outcome] += 1
            surfaced = alerts.get(did, [])
            counts["surfaced_pairs"] += bool(surfaced)
            counts["error_pairs"] += bool(row.get("error"))
            if row.get("error"):
                error_cases.add(row["event_id"])
            if outcome == "pending":
                continue
            counts["scored_surfaced_pairs"] += bool(surfaced)
            correct = any(a.get("path") in label.get("valid_paths", []) for a in surfaced)
            if outcome == "positive":
                counts["true_positive"] += bool(correct and not row.get("error"))
                counts["missed_impacts"] += not correct or bool(row.get("error"))
            elif outcome == "negative":
                counts["false_alerts"] += bool(surfaced)
            elif outcome in ("inconclusive", "unanswerable"):
                counts[f"{outcome}_explicit_uncertainty"] += bool(not row.get("error") and any(
                    a.get("uncertainty_reason") and a.get("path") in label.get("valid_paths", []) for a in surfaced))
            if outcome in ("positive", "negative"):
                counts["known_pairs"] += 1
                counts["known_surfaced_pairs"] += bool(surfaced)
                counts["false_abstentions"] += bool(surfaced) and all(
                    a.get("uncertainty_reason") for a in surfaced)
            for alert in surfaced:
                counts["emitted_paths"] += 1
                counts["correct_paths"] += alert.get("path") in label.get("valid_paths", [])
    def rate(numerator: str, denominator: str) -> dict:
        n, d = counts[numerator], counts[denominator]
        return {"value": n / d if d else None, "numerator": n, "denominator": d}
    counts["error_cases"] = len(error_cases)
    known_surfaced = counts["known_surfaced_pairs"]
    return {"counts": dict(counts),
            "precision": {"value": counts["true_positive"] / known_surfaced if known_surfaced else None,
                          "numerator": counts["true_positive"], "denominator": known_surfaced},
            "recall": rate("true_positive", "positive"),
            "false_alert_rate": rate("false_alerts", "negative"),
            "false_discovery_fraction": rate("false_alerts", "scored_surfaced_pairs"),
            "miss_rate": rate("missed_impacts", "positive"),
            "path_correctness": rate("correct_paths", "emitted_paths"),
            "inconclusive_handling": rate("inconclusive_explicit_uncertainty", "inconclusive"),
            "unanswerable_handling": rate("unanswerable_explicit_uncertainty", "unanswerable"),
            "false_abstention_rate": rate("false_abstentions", "known_pairs"),
            "rationale_correctness": None, "unsupported_conclusions": None,
            "answer_quality": None, "human_review_time": None}
