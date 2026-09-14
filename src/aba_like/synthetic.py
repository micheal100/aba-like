"""Generate a small synthetic history CSV for testing without live SWIS access.

Produces, per the build brief's test-case list: a metric with clean daily/
weekly seasonality (no alerts expected), one with an injected upper spike,
one with an injected lower spike, and a cold-start entity with too few
samples to train.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)


def _daily_pattern(hours: np.ndarray, weekdays: np.ndarray, base: float, peak: float, noise: float) -> np.ndarray:
    # Business-hours bump on weekdays (Mon-Fri), flatter on weekends.
    is_weekday = weekdays < 5
    business_hours = (hours >= 9) & (hours < 18)
    shape = base + (peak - base) * np.sin(np.clip(hours - 9, 0, 9) / 9 * np.pi) * (business_hours & is_weekday)
    return shape + RNG.normal(0, noise, size=len(hours))


def generate_history(lookback_days: int = 14, interval_hours: int = 1) -> pd.DataFrame:
    # Generate one extra week beyond lookback_days so the most recent points have a
    # full second weekly occurrence of their weekday_hour slot to train against —
    # with exactly `lookback_days` of data the very last hour's slot only has one
    # prior weekly occurrence, one short of the default min_points=2.
    end = pd.Timestamp.now(tz="UTC").floor("h")
    start = end - pd.Timedelta(days=lookback_days + 7)
    full_index = pd.date_range(start, end, freq=f"{interval_hours}h", inclusive="left")
    hours = full_index.hour.values
    weekdays = full_index.dayofweek.values

    frames = []

    def add(entity_id: int, entity_name: str, metric_name: str, values: np.ndarray, index: pd.DatetimeIndex):
        frames.append(pd.DataFrame({
            "timestamp": index, "entity_type": "node", "entity_id": entity_id,
            "entity_name": entity_name, "metric_name": metric_name, "value": values,
        }))

    # 1) Stable seasonal metric: expected daily peak, should never fire.
    seasonal = _daily_pattern(hours, weekdays, base=20, peak=65, noise=3)
    add(101, "demo-node-seasonal", "cpu_load_pct", np.clip(seasonal, 0, 100), full_index)

    # 2) Same seasonality, but the most recent point is a genuine upper spike.
    spike = _daily_pattern(hours, weekdays, base=20, peak=65, noise=3)
    spike[-1] = 98.0
    add(102, "demo-node-spike", "cpu_load_pct", np.clip(spike, 0, 100), full_index)

    # 3) Same seasonality, most recent point is a genuine lower spike
    #    (e.g. a service that unexpectedly went idle).
    low_spike = _daily_pattern(hours, weekdays, base=20, peak=65, noise=3)
    low_spike[-1] = 0.5
    add(103, "demo-node-lowspike", "cpu_load_pct", np.clip(low_spike, 0, 100), full_index)

    # 4) Cold-start: brand-new entity with only a handful of historical points.
    cold_index = full_index[-5:]
    cold_values = np.array([55.0, 58.0, 90.0, 60.0, 57.0])  # includes a "spike" that should NOT fire (untrained)
    add(104, "demo-node-coldstart", "cpu_load_pct", cold_values, cold_index)

    df = pd.concat(frames, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df
