"""Forgetting strategy (Roadmap V2#2).

Weibull decay on retrieval frequency instead of hard deletion + graceful
degradation ladder:  record -> summary -> gist -> tombstone.

Pure functions — easy to test, no dependencies.
"""

from __future__ import annotations

import math

# Levels of graceful degradation, descending by retention.
DEGRADATION_LADDER = ("record", "summary", "gist", "tombstone")

# Default thresholds for level selection (score in [0,1]).
DEGRADATION_THRESHOLDS = (0.6, 0.4, 0.2)


def weibull_decay(age: float, scale: float = 30.0, shape: float = 1.5) -> float:
    """Weibull survival: exp(-(age/scale)^shape) in (0,1].

    Age in the same units as `scale` (e.g. days). As age increases the
    value sinks toward 0 — a gentle forgetting, no hard cutoff.
    """
    if age <= 0:
        return 1.0
    return math.exp(-((age / scale) ** shape))


def retention_from_frequency(retrievals: int, freq_scale: float = 10.0) -> float:
    """Retention share from retrieval frequency (saturating upward).

    The more often an item is retrieved, the more of it is retained —
    but it never decays to 0 with at least one retrieval.
    """
    if retrievals <= 0:
        return 0.0
    return 1.0 - math.exp(-retrievals / freq_scale)


def degradation_level(
    score: float,
    thresholds: tuple[float, float, float] = DEGRADATION_THRESHOLDS,
) -> str:
    """Maps a decay score to a level (high = stays, low = dies)."""
    if score >= thresholds[0]:
        return "record"
    if score >= thresholds[1]:
        return "summary"
    if score >= thresholds[2]:
        return "gist"
    return "tombstone"


def decay_score(retrievals: int, age: float, freq_scale: float = 10.0,
                age_scale: float = 30.0, shape: float = 1.5) -> float:
    """Combines retrieval frequency (retains) with age (forgets) → [0,1]."""
    return retention_from_frequency(retrievals, freq_scale) * weibull_decay(age, age_scale, shape)


def decay_level(retrievals: int, age: float, freq_scale: float = 10.0,
                age_scale: float = 30.0, shape: float = 1.5) -> str:
    """Graceful degradation level for an item with (retrievals, age)."""
    return degradation_level(decay_score(retrievals, age, freq_scale, age_scale, shape))
