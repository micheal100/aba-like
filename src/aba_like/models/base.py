"""Shared seasonal-slot helpers, kept separate so a Method B (forecast+residual)
model can reuse them later without depending on seasonal_robust.py internals.
"""
from __future__ import annotations

import pandas as pd


def compute_slot(timestamps: pd.Series, seasonal_slot: str) -> pd.Series:
    if seasonal_slot == "weekday_hour":
        return timestamps.dt.dayofweek * 24 + timestamps.dt.hour
    if seasonal_slot == "hour_only":
        return timestamps.dt.hour
    if seasonal_slot == "weekday_only":
        return timestamps.dt.dayofweek
    raise ValueError(f"Unknown seasonal_slot '{seasonal_slot}'")


def slot_label(slot_value: int, seasonal_slot: str) -> str:
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if seasonal_slot == "weekday_hour":
        return f"{days[slot_value // 24]} {slot_value % 24:02d}:00"
    if seasonal_slot == "hour_only":
        return f"{slot_value:02d}:00"
    if seasonal_slot == "weekday_only":
        return days[slot_value]
    return str(slot_value)
