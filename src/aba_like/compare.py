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

EVENT_TYPE_TRIGGERED = 0  # confirmed against a live "ABA CPU - Anomaly-Based Alerting" alert
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


def _fmt(ts) -> str | None:
    return None if ts is None or pd.isna(ts) else ts.strftime("%Y-%m-%d %H:%M UTC")


def compare_events(
    native: pd.DataFrame, ours: pd.DataFrame, tolerance_minutes: int = 30,
) -> pd.DataFrame:
    """Match native "Triggered" events to our own `fire` rows within a
    tolerance window, per node. Everything unmatched on either side is
    surfaced so you can judge over/under-triggering, not to score "accuracy"
    against SolarWinds' proprietary model.

    Output columns are named and formatted for someone comparing results in
    Excel/Sheets, not for further scripting — plain labels, readable
    timestamps, and this tool's own plain-English `reason` included so a
    non-developer can see *why* it did or didn't fire without reading code.
    """
    if native.empty:
        native_triggers = pd.DataFrame(columns=["RelatedNodeId", "TimeStamp", "AlertName", "EntityCaption"])
    else:
        native_triggers = native[native["EventType"] == EVENT_TYPE_TRIGGERED][
            ["RelatedNodeId", "TimeStamp", "AlertName", "EntityCaption"]
        ].rename(columns={"RelatedNodeId": "entity_id"})

    ours_fired = ours[ours["fire"]][
        ["entity_id", "entity_name", "metric_name", "timestamp", "reason"]
    ]

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
                "Result": "Native ABA only (this tool did not flag it)",
                "Node": nt["EntityCaption"], "Node ID": nt["entity_id"],
                "Native ABA Time": _fmt(nt["TimeStamp"]), "Native Alert Name": nt["AlertName"],
                "This Tool's Time": None, "This Tool's Metric": None,
                "Minutes Apart": None, "This Tool's Reason": None,
            })
        else:
            for idx, c in candidates.iterrows():
                matched_our_idx.add(idx)
                delta_min = round(abs((c["timestamp"] - nt["TimeStamp"]).total_seconds()) / 60, 1)
                rows.append({
                    "Result": "Both flagged this",
                    "Node": nt["EntityCaption"], "Node ID": nt["entity_id"],
                    "Native ABA Time": _fmt(nt["TimeStamp"]), "Native Alert Name": nt["AlertName"],
                    "This Tool's Time": _fmt(c["timestamp"]), "This Tool's Metric": c["metric_name"],
                    "Minutes Apart": delta_min, "This Tool's Reason": c["reason"],
                })

    for idx, c in ours_fired.iterrows():
        if idx not in matched_our_idx:
            rows.append({
                "Result": "This tool only (native ABA did not flag it)",
                "Node": c["entity_name"], "Node ID": c["entity_id"],
                "Native ABA Time": None, "Native Alert Name": None,
                "This Tool's Time": _fmt(c["timestamp"]), "This Tool's Metric": c["metric_name"],
                "Minutes Apart": None, "This Tool's Reason": c["reason"],
            })

    result = pd.DataFrame(rows, columns=[
        "Result", "Node", "Node ID", "Native ABA Time", "Native Alert Name",
        "This Tool's Time", "This Tool's Metric", "Minutes Apart", "This Tool's Reason",
    ])
    if result.empty:
        return result
    result["_sort_key"] = result["Native ABA Time"].fillna(result["This Tool's Time"])
    return result.sort_values("_sort_key").drop(columns="_sort_key").reset_index(drop=True)
