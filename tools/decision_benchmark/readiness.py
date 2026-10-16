"""Assess frozen gates without treating absent observations as passing scores."""
from __future__ import annotations


def assess(scores: dict, gates: dict, *, independent: bool) -> dict:
    results = {}
    for name, metric, threshold, lower in (
        ('false_alerts', 'false_alert_rate', 'false_alert_rate_max', False),
        ('misses', 'miss_rate', 'miss_rate_max', False),
        ('inconclusive_handling', 'inconclusive_handling', 'inconclusive_handling_min', True),
    ):
        value = scores[metric]
        passed = None if value['value'] is None else (
            value['value'] >= gates[threshold] if lower else value['value'] <= gates[threshold])
        results[name] = dict(status='unmeasured' if passed is None else 'pass' if passed else 'fail',
            measurement=value, threshold=gates[threshold], release_evidence=independent)
    counts = scores['counts']
    for name, count, threshold in (
        ('heldout_positive', counts.get('positive', 0), 'heldout_positive_min'),
        ('heldout_negative', counts.get('negative', 0), 'heldout_negative_min'),
        # One event can have multiple inconclusive pairs; pair count is not case count.
        ('heldout_inconclusive_cases', None, 'heldout_inconclusive_min'),
    ):
        actual = count if independent else 0 if count is not None else None
        results[name] = dict(status='unmeasured' if actual is None else 'pass' if actual >= gates[threshold] else 'fail',
            observed=actual, threshold=gates[threshold], reason='Independent held-out cases only; synthetic cases do not qualify.')
    for name, threshold in (
        ('provenance_correctness', 'provenance_correctness_min'),
        ('unsupported_conclusions', 'unsupported_conclusions_max'),
        ('integrity', 'integrity_pass_min'),
        ('median_review_time_reduction', 'median_review_time_reduction_min'),
    ):
        results[name] = dict(status='unmeasured', observed=None, threshold=gates[threshold],
            reason='Requires independent judgment or the complete controlled protocol; component checks are insufficient.')
    return dict(passed=False, promotion='keep experimental', frozen_thresholds=gates, gates=results,
        reason='Source-change diagnostics cannot establish semantic improvement; independent coverage and human measurements are missing.')
