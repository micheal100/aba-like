"""Backtest metrics and Markdown report generation.

Backtesting itself is just `score_history` + `apply_alert_logic` run over the
full stored history in chronological order (both already avoid look-ahead by
construction) — this module only summarizes the result.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import Config


def compute_metrics(alerted: pd.DataFrame, incidents: pd.DataFrame | None = None) -> dict:
    m: dict = {}
    m["total_observations"] = int(len(alerted))
    m["trained_observations"] = int(alerted["trained"].sum())
    m["untrained_observations"] = int((~alerted["trained"]).sum())
    m["anomaly_events"] = int(alerted["anomalous"].sum())
    m["condition_met_events"] = int(alerted["condition_met"].sum())
    m["fired_alerts"] = int(alerted["fire"].sum())
    m["consecutive_alert_reduction_pct"] = (
        round(100 * (1 - m["fired_alerts"] / m["condition_met_events"]), 1)
        if m["condition_met_events"] else 0.0
    )

    per_entity = (
        alerted.groupby(["entity_type", "entity_id", "entity_name", "metric_name"])
        .agg(observations=("value", "size"), fired=("fire", "sum"), anomalous=("anomalous", "sum"))
        .reset_index()
    )
    per_entity["alert_rate_pct"] = (100 * per_entity["fired"] / per_entity["observations"]).round(2)
    m["per_entity_metric"] = per_entity

    coverage = (
        alerted.groupby("entity_type")["entity_id"].nunique().rename("entities_evaluated").reset_index()
    )
    m["coverage_by_entity_type"] = coverage

    fires = alerted[alerted["fire"]].sort_values("timestamp")
    if len(fires) >= 2:
        deltas = fires.groupby(["entity_type", "entity_id", "metric_name"])["timestamp"].diff().dropna()
        m["mean_time_between_alerts_hours"] = (
            round(deltas.dt.total_seconds().mean() / 3600, 2) if not deltas.empty else None
        )
    else:
        m["mean_time_between_alerts_hours"] = None

    if incidents is not None and not incidents.empty:
        m["incident_labels"] = _label_against_incidents(alerted, incidents)

    return m


def _label_against_incidents(alerted: pd.DataFrame, incidents: pd.DataFrame) -> pd.DataFrame:
    incidents = incidents.copy()
    incidents["timestamp_start"] = pd.to_datetime(incidents["timestamp_start"], utc=True)
    incidents["timestamp_end"] = pd.to_datetime(incidents["timestamp_end"], utc=True)

    rows = []
    for _, inc in incidents.iterrows():
        mask = (
            (alerted["entity_id"].astype(str) == str(inc["entity_id"]))
            & (alerted["metric_name"] == inc["metric_name"])
            & (alerted["timestamp"] >= inc["timestamp_start"])
            & (alerted["timestamp"] <= inc["timestamp_end"])
        )
        window = alerted[mask]
        caught = bool(window["fire"].any()) if not window.empty else False
        rows.append({
            "entity_id": inc["entity_id"], "metric_name": inc["metric_name"],
            "label": inc["label"], "window_start": inc["timestamp_start"],
            "window_end": inc["timestamp_end"], "caught_by_script": caught,
            "notes": inc.get("notes", ""),
        })
    return pd.DataFrame(rows)


def write_report(metrics: dict, cfg: Config, report_path: Path, csv_path: Path) -> None:
    metrics["per_entity_metric"].to_csv(csv_path, index=False)

    lines = [
        "# ABA-like backtest report",
        "",
        "This is an ABA-like (NOR-based) customer-owned anomaly detection backtest. "
        "It is not SolarWinds ABA and does not reproduce SolarWinds' cloud AIOps model.",
        "",
        "## Configuration",
        f"- Lookback: {cfg.lookback_days} days",
        f"- Seasonal slot: {cfg.seasonal_slot}",
        f"- Min points to train: {cfg.min_points}",
        f"- NOR method: {cfg.nor_method}, alpha={cfg.alpha} "
        "(engineering starting point, not a SolarWinds-matched constant)",
        f"- Alert mode: {cfg.alert.mode}, bound: {cfg.alert.bound}",
        f"- Consecutive breaches required: {cfg.alert.consecutive_breaches}, "
        f"cooldown: {cfg.alert.cooldown_minutes}min, recovery margin: {cfg.alert.recovery_margin}",
        "",
        "## Summary",
        f"- Total observations: {metrics['total_observations']}",
        f"- Trained observations: {metrics['trained_observations']} "
        f"({metrics['untrained_observations']} untrained)",
        f"- Anomaly events (breached NOR): {metrics['anomaly_events']}",
        f"- Condition-met events (pre consecutive/cooldown gating): {metrics['condition_met_events']}",
        f"- Fired alerts: {metrics['fired_alerts']}",
        f"- Consecutive/cooldown reduction: {metrics['consecutive_alert_reduction_pct']}% fewer fires "
        "than a single-sample trigger would have produced",
        f"- Mean time between alerts: {metrics['mean_time_between_alerts_hours']} hours",
        "",
        "## Coverage by entity type",
        metrics["coverage_by_entity_type"].to_markdown(index=False),
        "",
        f"## Per-entity/metric alert rate (see also `{csv_path.name}`)",
        metrics["per_entity_metric"].sort_values("fired", ascending=False).head(20).to_markdown(index=False),
    ]

    if "incident_labels" in metrics:
        lines += ["", "## Incident comparison", metrics["incident_labels"].to_markdown(index=False)]

    report_path.write_text("\n".join(lines), encoding="utf-8")
