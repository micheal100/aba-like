"""Optional: compare this script's fired events against native SolarWinds
alert history (including real ABA, if you've enabled it on a few test nodes)
for validation purposes.

This reads standard alert history via SWIS — it does not read internal ABA
model objects and does not claim to reproduce them. It exists purely so you
can sanity-check this script's anomaly calls against what native ABA (or any
other alert) actually did on the same nodes over the same window.
"""
from __future__ import annotations

import pandas as pd

from .swis_client import SwisClient, in_clause
from .swis_queries import build_alert_history_query

EVENT_TYPE_TRIGGERED = 0  # best-effort assumption; confirm via `doctor`/sample data
EVENT_TYPE_RESET = 1


def fetch_native_alert_events(
    client: SwisClient, node_ids: list[int], start: pd.Timestamp, end: pd.Timestamp,
    name_like: str | None = None,
) -> pd.DataFrame:
    swql = build_alert_history_query(in_clause(node_ids), name_like)
    params = {
        "start": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }
    if name_like:
        params["name_like"] = name_like
    rows = client.query(swql, params)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["TimeStamp"] = pd.to_datetime(df["TimeStamp"], utc=True)
    return df


def compare_events(
    native: pd.DataFrame, ours: pd.DataFrame, tolerance_minutes: int = 30,
) -> pd.DataFrame:
    """Match native "Triggered" events to our own `fire` rows within a
    tolerance window, per node. Everything unmatched on either side is
    surfaced so you can judge over/under-triggering, not to score "accuracy"
    against SolarWinds' proprietary model.
    """
    if native.empty:
        native_triggers = pd.DataFrame(columns=["RelatedNodeId", "TimeStamp", "AlertName"])
    else:
        native_triggers = native[native["EventType"] == EVENT_TYPE_TRIGGERED][
            ["RelatedNodeId", "TimeStamp", "AlertName"]
        ].rename(columns={"RelatedNodeId": "entity_id"})

    ours_fired = ours[ours["fire"]][["entity_id", "entity_name", "metric_name", "timestamp", "reason"]]

    tol = pd.Timedelta(minutes=tolerance_minutes)
    rows = []
    matched_our_idx: set[int] = set()

    for _, nt in native_triggers.iterrows():
        candidates = ours_fired[
            (ours_fired["entity_id"] == nt["entity_id"])
            & (ours_fired["timestamp"] >= nt["TimeStamp"] - tol)
            & (ours_fired["timestamp"] <= nt["TimeStamp"] + tol)
        ]
        if candidates.empty:
            rows.append({
                "entity_id": nt["entity_id"], "native_time": nt["TimeStamp"],
                "native_alert": nt["AlertName"], "our_time": None, "our_metric": None,
                "match": "native_only",
            })
        else:
            for idx, c in candidates.iterrows():
                matched_our_idx.add(idx)
                rows.append({
                    "entity_id": nt["entity_id"], "native_time": nt["TimeStamp"],
                    "native_alert": nt["AlertName"], "our_time": c["timestamp"],
                    "our_metric": c["metric_name"], "match": "matched",
                })

    for idx, c in ours_fired.iterrows():
        if idx not in matched_our_idx:
            rows.append({
                "entity_id": c["entity_id"], "native_time": None, "native_alert": None,
                "our_time": c["timestamp"], "our_metric": c["metric_name"], "match": "ours_only",
            })

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["sort_key"] = result["native_time"].fillna(result["our_time"])
    return result.sort_values("sort_key").drop(columns="sort_key")
