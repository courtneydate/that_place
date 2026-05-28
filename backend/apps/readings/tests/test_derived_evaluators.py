"""Unit tests for the pure-function derived-stream evaluators (Sprint 27).

These tests are intentionally ORM-free — the evaluators take SourceReading
dataclasses and return DerivedOutput dataclasses. The dispatch-layer tests
(test_derived_dispatch) cover the integration with Stream / StreamReading.

Ref: SPEC.md § Feature: Derived / Computed Streams; ROADMAP Sprint 27
"""
from datetime import datetime, timedelta, timezone

from apps.readings.derived import (
    DerivedOutput,
    SourceReading,
    evaluate_delta,
    evaluate_difference,
    evaluate_scale,
    evaluate_sum,
    evaluate_window,
)

UTC = timezone.utc


def _ts(minute, second=0):
    return datetime(2026, 5, 28, 10, minute, second, tzinfo=UTC)


# ---------------------------------------------------------------------------
# delta
# ---------------------------------------------------------------------------


def test_delta_returns_none_for_first_reading():
    new = SourceReading(stream_id=1, timestamp=_ts(0), value=100.0)
    assert evaluate_delta(new, previous_reading=None) is None


def test_delta_basic_diff():
    prev = SourceReading(stream_id=1, timestamp=_ts(0), value=100.0)
    new = SourceReading(stream_id=1, timestamp=_ts(5), value=150.0)
    out = evaluate_delta(new, previous_reading=prev)
    assert out == DerivedOutput(timestamp=_ts(5), value=50.0, quality='measured')


def test_delta_negative_dropped_as_counter_reset():
    prev = SourceReading(stream_id=1, timestamp=_ts(0), value=100.0)
    new = SourceReading(stream_id=1, timestamp=_ts(5), value=20.0)
    assert evaluate_delta(new, previous_reading=prev) is None


def test_delta_no_max_gap_minutes_does_not_suppress():
    """With max_gap_minutes unset, an arbitrarily large gap still computes."""
    prev = SourceReading(stream_id=1, timestamp=_ts(0), value=100.0)
    new = SourceReading(
        stream_id=1,
        timestamp=_ts(0) + timedelta(hours=6),
        value=160.0,
    )
    out = evaluate_delta(new, previous_reading=prev)
    assert out is not None and out.value == 60.0


def test_delta_with_max_gap_minutes_suppresses_long_gap():
    prev = SourceReading(stream_id=1, timestamp=_ts(0), value=100.0)
    new = SourceReading(stream_id=1, timestamp=_ts(0) + timedelta(minutes=20), value=120.0)
    assert evaluate_delta(new, previous_reading=prev, max_gap_minutes=15) is None


def test_delta_propagates_worst_input_quality():
    prev = SourceReading(stream_id=1, timestamp=_ts(0), value=100.0, quality='measured')
    new = SourceReading(stream_id=1, timestamp=_ts(5), value=150.0, quality='estimated')
    out = evaluate_delta(new, previous_reading=prev)
    assert out is not None and out.quality == 'estimated'


# ---------------------------------------------------------------------------
# scale
# ---------------------------------------------------------------------------


def test_scale_multiplies_value():
    r = SourceReading(stream_id=1, timestamp=_ts(0), value=4.5)
    out = evaluate_scale(r, factor=2.0)
    assert out.value == 9.0 and out.timestamp == _ts(0)


def test_scale_preserves_quality():
    r = SourceReading(stream_id=1, timestamp=_ts(0), value=4.5, quality='estimated')
    out = evaluate_scale(r, factor=2.0)
    assert out.quality == 'estimated'


# ---------------------------------------------------------------------------
# window_min / window_max / window_avg
# ---------------------------------------------------------------------------


def test_window_returns_none_for_empty_input():
    assert evaluate_window([], aggregate='min', window_end=_ts(15)) is None


def test_window_min_over_readings():
    readings = [
        SourceReading(1, _ts(0), 30.0),
        SourceReading(1, _ts(5), 25.0),
        SourceReading(1, _ts(10), 28.0),
    ]
    out = evaluate_window(readings, aggregate='min', window_end=_ts(15))
    assert out is not None and out.value == 25.0 and out.timestamp == _ts(15)


def test_window_max_over_readings():
    readings = [
        SourceReading(1, _ts(0), 30.0),
        SourceReading(1, _ts(5), 25.0),
        SourceReading(1, _ts(10), 28.0),
    ]
    out = evaluate_window(readings, aggregate='max', window_end=_ts(15))
    assert out is not None and out.value == 30.0


def test_window_avg_over_readings():
    readings = [
        SourceReading(1, _ts(0), 30.0),
        SourceReading(1, _ts(5), 20.0),
        SourceReading(1, _ts(10), 40.0),
    ]
    out = evaluate_window(readings, aggregate='avg', window_end=_ts(15))
    assert out is not None and out.value == 30.0


def test_window_unknown_aggregate_raises():
    import pytest
    with pytest.raises(ValueError):
        evaluate_window([SourceReading(1, _ts(0), 1.0)], aggregate='nope', window_end=_ts(15))


def test_window_inherits_worst_input_quality():
    readings = [
        SourceReading(1, _ts(0), 30.0, quality='measured'),
        SourceReading(1, _ts(5), 25.0, quality='gap'),
    ]
    out = evaluate_window(readings, aggregate='min', window_end=_ts(15))
    assert out is not None and out.quality == 'gap'


# ---------------------------------------------------------------------------
# sum (cross-source, minute-bucketed)
# ---------------------------------------------------------------------------


def test_sum_pairs_readings_in_same_minute_bucket():
    a = [SourceReading(1, _ts(5, 12), 100.0)]
    b = [SourceReading(2, _ts(5, 47), 50.0)]  # same minute bucket as a
    outs = evaluate_sum({1: a, 2: b})
    assert len(outs) == 1
    assert outs[0].timestamp == _ts(5)  # bucket boundary
    assert outs[0].value == 150.0


def test_sum_skips_buckets_missing_a_source():
    a = [SourceReading(1, _ts(5, 0), 100.0), SourceReading(1, _ts(6, 0), 200.0)]
    b = [SourceReading(2, _ts(5, 0), 50.0)]
    outs = evaluate_sum({1: a, 2: b})
    assert len(outs) == 1
    assert outs[0].timestamp == _ts(5)


def test_sum_keeps_latest_per_stream_in_bucket():
    a = [SourceReading(1, _ts(5, 10), 100.0), SourceReading(1, _ts(5, 50), 110.0)]
    b = [SourceReading(2, _ts(5, 30), 50.0)]
    outs = evaluate_sum({1: a, 2: b})
    # Latest a in the bucket (110) + the only b (50) = 160
    assert len(outs) == 1 and outs[0].value == 160.0


def test_sum_returns_empty_when_no_sources():
    assert evaluate_sum({}) == []


def test_sum_inherits_worst_quality():
    a = [SourceReading(1, _ts(5, 0), 100.0, quality='measured')]
    b = [SourceReading(2, _ts(5, 30), 50.0, quality='estimated')]
    outs = evaluate_sum({1: a, 2: b})
    assert outs[0].quality == 'estimated'


# ---------------------------------------------------------------------------
# difference (cross-source, minute-bucketed)
# ---------------------------------------------------------------------------


def test_difference_a_minus_b_at_same_bucket():
    a = [SourceReading(1, _ts(5, 12), 200.0)]
    b = [SourceReading(2, _ts(5, 47), 80.0)]
    outs = evaluate_difference(a, b, source_a_id=1, source_b_id=2)
    assert outs[0].value == 120.0 and outs[0].timestamp == _ts(5)


def test_difference_can_go_negative():
    a = [SourceReading(1, _ts(5, 0), 50.0)]
    b = [SourceReading(2, _ts(5, 0), 80.0)]
    outs = evaluate_difference(a, b, source_a_id=1, source_b_id=2)
    assert outs[0].value == -30.0


def test_difference_skips_bucket_missing_either_source():
    a = [SourceReading(1, _ts(5, 0), 100.0), SourceReading(1, _ts(6, 0), 110.0)]
    b = [SourceReading(2, _ts(5, 0), 80.0)]
    outs = evaluate_difference(a, b, source_a_id=1, source_b_id=2)
    assert len(outs) == 1 and outs[0].timestamp == _ts(5)
