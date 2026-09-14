import numpy as np
import pandas as pd
import pytest

from aba_like.config import Config
from aba_like.models.seasonal_robust import score_history


def _hourly_history(values, start="2026-01-05T00:00:00Z"):  # 2026-01-05 is a Monday
    idx = pd.date_range(start, periods=len(values), freq="1h", tz="UTC")
    return pd.DataFrame({
        "timestamp": idx, "entity_type": "node", "entity_id": 1,
        "entity_name": "n1", "metric_name": "cpu_load_pct", "value": values,
    })


def _daily_history(values, start="2026-01-05T09:00:00Z"):
    # One sample per day at a fixed hour, so every point shares the same
    # `hour_only` slot regardless of how few days of history exist.
    idx = pd.date_range(start, periods=len(values), freq="24h", tz="UTC")
    return pd.DataFrame({
        "timestamp": idx, "entity_type": "node", "entity_id": 1,
        "entity_name": "n1", "metric_name": "cpu_load_pct", "value": values,
    })


def _cfg(**overrides) -> Config:
    cfg = Config(lookback_days=14, min_points=5, alpha=3.0, seasonal_slot="hour_only")
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def test_stable_metric_no_anomaly():
    # Same value every hour for 10 days plus one more identical point: MAD=0
    # triggers the quantile fallback, and the fallback point still equals the
    # constant value, so it must not be flagged.
    values = [50.0] * (24 * 10 + 1)
    history = _hourly_history(values)
    scored = score_history(history, _cfg())
    last = scored.iloc[-1]
    assert last["trained"]
    assert last["lower_nor"] <= last["value"] <= last["upper_nor"]


def test_upper_spike_detected():
    rng = np.random.default_rng(0)
    base = 50 + rng.normal(0, 1, 24 * 10)
    values = np.concatenate([base, [95.0]])
    history = _hourly_history(values)
    scored = score_history(history, _cfg())
    last = scored.iloc[-1]
    assert last["trained"]
    assert last["value"] > last["upper_nor"]


def test_lower_spike_detected():
    rng = np.random.default_rng(0)
    base = 50 + rng.normal(0, 1, 24 * 10)
    values = np.concatenate([base, [2.0]])
    history = _hourly_history(values)
    scored = score_history(history, _cfg())
    last = scored.iloc[-1]
    assert last["trained"]
    assert last["value"] < last["lower_nor"]


def test_expected_daily_peak_no_alert():
    # Every day's 09:00 sample sits in the same `hour_only` slot and is always
    # ~80 (a business-hours peak); today's 80 should sit inside the band even
    # though it's far from an all-hours average.
    values = [80.0] * 20 + [80.0]
    history = _daily_history(values, start="2026-01-05T09:00:00Z")
    scored = score_history(history, _cfg(min_points=5))
    last = scored.iloc[-1]
    assert last["trained"]
    assert last["lower_nor"] <= last["value"] <= last["upper_nor"]


def test_cold_start_untrained():
    values = [50.0, 52.0, 90.0]  # only 2 prior same-slot points before the "spike"
    history = _daily_history(values)
    scored = score_history(history, _cfg(min_points=5))
    last = scored.iloc[-1]
    assert not last["trained"]
    assert pd.isna(last["lower_nor"])
    assert last["sample_count"] == 2


def test_mad_zero_uses_quantile_fallback():
    values = [50.0] * 30 + [50.0]
    history = _daily_history(values)
    scored = score_history(history, _cfg(min_points=5))
    last = scored.iloc[-1]
    assert last["trained"]
    assert last["lower_nor"] < last["upper_nor"] or last["lower_nor"] == last["upper_nor"] == 50.0


def test_no_lookahead_in_backtest():
    # A future spike must not influence the bounds computed for earlier points.
    values = [50.0] * 30 + [500.0] + [50.0] * 5
    history = _daily_history(values)
    scored = score_history(history, _cfg(min_points=5))
    early_point = scored.iloc[29]  # the day right before the spike, well-trained
    assert early_point["trained"]
    assert early_point["upper_nor"] < 500.0
