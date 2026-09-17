"""Rolling CSV history store.

One flat CSV: timestamp, entity_type, entity_id, entity_name, metric_name, value.
Each `fetch` run appends newly-resampled hourly points and purges anything
older than `lookback_days` — "for each new run, the oldest hour gets purged."

CSV was an explicit, deliberate choice for this POC's scale (up to ~500
entities x a handful of metrics x hourly points over `lookback_days`); revisit
if/when volumes grow well beyond that.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

COLUMNS = ["timestamp", "entity_type", "entity_id", "entity_name", "metric_name", "value"]


def load_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path, parse_dates=["timestamp"])
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")
    return df


def save_history(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.sort_values(["entity_type", "entity_id", "metric_name", "timestamp"])
    df.to_csv(path, index=False)


def merge_and_purge(
    existing: pd.DataFrame,
    new_rows: pd.DataFrame,
    lookback_days: int,
    now: pd.Timestamp,
) -> pd.DataFrame:
    # Concatenating with an empty frame changes dtype-inference behavior in future
    # pandas versions (FutureWarning) — skip it entirely rather than rely on that.
    frames = [df for df in (existing, new_rows) if not df.empty]
    combined = pd.concat(frames, ignore_index=True) if frames else existing.copy()
    combined = combined.drop_duplicates(
        subset=["entity_type", "entity_id", "metric_name", "timestamp"], keep="last"
    )
    cutoff = now - pd.Timedelta(days=lookback_days)
    before = len(combined)
    combined = combined[combined["timestamp"] >= cutoff]
    purged = before - len(combined)
    if purged:
        log.info("Purged %d rows older than lookback (%s)", purged, cutoff.isoformat())
    return combined


def last_timestamp(df: pd.DataFrame) -> pd.Timestamp | None:
    if df.empty:
        return None
    return df["timestamp"].max()
