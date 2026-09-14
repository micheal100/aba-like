"""Method A — seasonal NOR bands from historical same-slot samples.

For every point, look only at historical points from the same seasonal slot
(e.g. "Monday 09:00" for `weekday_hour`) within the configured lookback
window, strictly *before* the current point's timestamp — no look-ahead, so
this same function is safe for both live scoring and chronological
backtesting.

Two selectable statistics (`cfg.nor_method`):
  - robust_mad (default): median +/- alpha * 1.4826*MAD. Falls back to the
    1st/99th empirical percentile when MAD is zero (a slot with a constant
    historical value would otherwise produce a zero-width band).
  - classic_meanstd: literal mean +/- alpha * standard deviation.

`alpha` is an engineering starting point, not a claimed match to any
SolarWinds-internal constant. NOR here is a per-slot statistical band over a
configurable lookback — not a guarantee of SolarWinds' proprietary model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Config
from .base import compute_slot

OUTPUT_COLUMNS = [
    "timestamp", "entity_type", "entity_id", "entity_name", "metric_name", "value",
    "lower_nor", "upper_nor", "expected_value", "trained", "sample_count",
    "model_method", "lookback_days", "alpha", "nor_method", "slot",
]


def _bounds_robust_mad(hist: np.ndarray, alpha: float) -> tuple[float, float, float]:
    median = float(np.median(hist))
    mad = float(np.median(np.abs(hist - median)))
    robust_sigma = 1.4826 * mad
    if robust_sigma == 0:
        lower = float(np.percentile(hist, 1))
        upper = float(np.percentile(hist, 99))
    else:
        lower = median - alpha * robust_sigma
        upper = median + alpha * robust_sigma
    return lower, upper, median


def _bounds_classic_meanstd(hist: np.ndarray, alpha: float) -> tuple[float, float, float]:
    mean = float(np.mean(hist))
    std = float(np.std(hist, ddof=1)) if len(hist) > 1 else 0.0
    if std == 0:
        lower = float(np.percentile(hist, 1))
        upper = float(np.percentile(hist, 99))
    else:
        lower = mean - alpha * std
        upper = mean + alpha * std
    return lower, upper, mean


_BOUND_FUNCS = {"robust_mad": _bounds_robust_mad, "classic_meanstd": _bounds_classic_meanstd}


def score_history(history: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Score every row in `history` against same-slot history preceding it.

    Pass the full rolling-store history to backtest chronologically; pass
    just the latest hour's rows (plus enough lookback already in `history`)
    for a live hourly `run`.
    """
    if history.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    bound_fn = _BOUND_FUNCS.get(cfg.nor_method)
    if bound_fn is None:
        raise ValueError(f"Unknown nor_method '{cfg.nor_method}'")

    df = history.copy()
    df["slot"] = compute_slot(df["timestamp"], cfg.seasonal_slot)
    lookback = pd.Timedelta(days=cfg.lookback_days)

    rows = []
    for (etype, eid, ename, metric), g in df.groupby(
        ["entity_type", "entity_id", "entity_name", "metric_name"], sort=False
    ):
        g = g.sort_values("timestamp").reset_index(drop=True)
        timestamps = g["timestamp"].to_numpy()
        slots = g["slot"].to_numpy()
        values = g["value"].to_numpy(dtype=float)

        for i in range(len(g)):
            t = timestamps[i]
            slot = slots[i]
            window_start = t - lookback
            mask = (slots == slot) & (timestamps >= window_start) & (timestamps < t)
            hist_vals = values[mask]
            hist_vals = hist_vals[~np.isnan(hist_vals)]
            sample_count = len(hist_vals)
            trained = sample_count >= cfg.min_points

            if trained:
                lower_nor, upper_nor, expected_value = bound_fn(hist_vals, cfg.alpha)
            else:
                lower_nor = upper_nor = expected_value = np.nan

            rows.append(
                {
                    "timestamp": t,
                    "entity_type": etype,
                    "entity_id": eid,
                    "entity_name": ename,
                    "metric_name": metric,
                    "value": values[i],
                    "lower_nor": lower_nor,
                    "upper_nor": upper_nor,
                    "expected_value": expected_value,
                    "trained": trained,
                    "sample_count": sample_count,
                    "model_method": "seasonal_robust",
                    "lookback_days": cfg.lookback_days,
                    "alpha": cfg.alpha,
                    "nor_method": cfg.nor_method,
                    "slot": slot,
                }
            )

    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
