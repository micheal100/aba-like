"""Pull raw samples from SWIS and resample them into the rolling store's shape."""
from __future__ import annotations

import logging

import pandas as pd

from .config import Config
from .grouping import Entity, discover_in_scope_entities
from .swis_client import SwisClient, in_clause
from .swis_queries import QUERIES

log = logging.getLogger(__name__)

_AGG_FUNCS = {"mean": "mean", "max": "max", "p95": (lambda s: s.quantile(0.95))}


def discover_all_entities(client: SwisClient, cfg: Config) -> dict[str, list[Entity]]:
    result: dict[str, list[Entity]] = {}
    for name, et in cfg.entity_types.items():
        result[name] = discover_in_scope_entities(client, et)
    return result


def fetch_raw_samples(
    client: SwisClient,
    cfg: Config,
    entities_by_type: dict[str, list[Entity]],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Fetch raw (native-poll-resolution) samples for every configured metric."""
    frames: list[pd.DataFrame] = []
    swis_dt_fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    start_s, end_s = start.strftime(swis_dt_fmt), end.strftime(swis_dt_fmt)

    for metric in cfg.metrics:
        entities = entities_by_type.get(metric.entity_type, [])
        if not entities:
            continue
        et = cfg.entity_types[metric.entity_type]
        builder = QUERIES.get(metric.source)
        if builder is None:
            raise ValueError(f"Unknown metric source '{metric.source}' for metric '{metric.name}'")

        ids = [e.entity_id for e in entities]
        id_to_name = {e.entity_id: e.entity_name for e in entities}

        swql = builder(et, metric, in_clause(ids))
        rows = client.query(swql, {"start": start_s, "end": end_s})
        if not rows:
            log.debug("No rows for metric=%s entity_type=%s in window", metric.name, metric.entity_type)
            continue

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["DateTime"], utc=True)
        df["entity_type"] = metric.entity_type
        df["entity_id"] = df["EntityID"].astype(int)
        df["entity_name"] = df["entity_id"].map(id_to_name)
        df["metric_name"] = metric.name
        df["value"] = pd.to_numeric(df["Value"], errors="coerce")
        frames.append(df[["timestamp", "entity_type", "entity_id", "entity_name", "metric_name", "value"]])

    if not frames:
        return pd.DataFrame(columns=["timestamp", "entity_type", "entity_id", "entity_name", "metric_name", "value"])
    return pd.concat(frames, ignore_index=True)


def resample_to_interval(raw: pd.DataFrame, interval: str, aggregation: str) -> pd.DataFrame:
    if raw.empty:
        return raw
    agg = _AGG_FUNCS.get(aggregation)
    if agg is None:
        raise ValueError(f"Unknown resample aggregation '{aggregation}'")

    grouped = (
        raw.set_index("timestamp")
        .groupby(["entity_type", "entity_id", "entity_name", "metric_name"])["value"]
        .resample(interval)
        .agg(agg)
        .dropna()
        .reset_index()
    )
    return grouped[["timestamp", "entity_type", "entity_id", "entity_name", "metric_name", "value"]]
