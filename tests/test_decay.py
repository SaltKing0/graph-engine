"""Unit tests for the forgetting strategy (Weibull decay, V2#2)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_engine.decay import (
    weibull_decay,
    retention_from_frequency,
    degradation_level,
    decay_level,
    DEGRADATION_LADDER,
)


def test_weibull_decay_starts_at_one_and_decays():
    assert weibull_decay(0) == 1.0
    assert 0 < weibull_decay(10) < 1.0
    assert weibull_decay(100) < weibull_decay(10)  # monoton fallend


def test_weibull_decay_is_monotonic():
    ages = [1, 5, 20, 60, 200]
    vals = [weibull_decay(a) for a in ages]
    assert all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))


def test_retention_from_frequency():
    assert retention_from_frequency(0) == 0.0
    assert retention_from_frequency(1) > 0.0
    assert retention_from_frequency(100) > retention_from_frequency(1)
    assert retention_from_frequency(50) < 1.0  # saturates upward, never exactly 1


def test_degradation_ladder():
    assert DEGRADATION_LADDER == ("record", "summary", "gist", "tombstone")


def test_degradation_level_thresholds():
    assert degradation_level(0.9) == "record"
    assert degradation_level(0.5) == "summary"
    assert degradation_level(0.3) == "gist"
    assert degradation_level(0.1) == "tombstone"


def test_decay_level_combines_frequency_and_age():
    # jung + oft abgerufen → record
    assert decay_level(retrievals=50, age=1) == "record"
    # alt + nie abgerufen → tombstone
    assert decay_level(retrievals=0, age=500) == "tombstone"
    # same age: more frequent access protects against forgetting
    assert decay_level(retrievals=50, age=20) in ("record", "summary", "gist")
    assert decay_level(retrievals=0, age=20) == "tombstone"
