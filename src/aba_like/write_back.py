"""Long-term write-back: set/clear a custom property so a standard (non-ABA)
SolarWinds alert can pick it up and keep firing/clearing there.

Deliberately generic and disabled by default (`write_back.enabled: false`) —
the real property name doesn't exist yet in SWOSH. This never touches
internal ABA tables/objects; it only calls the same documented
Update-a-CustomProperties-row pattern used elsewhere on this host
(see SwisClient.custom_property_uri).

An entity's aggregate state is "anomalous" if ANY of its in-scope metrics are
currently `active` (fired and not yet recovered) — a node with one alerting
interface should still show as flagged.
"""
from __future__ import annotations

import logging

import pandas as pd

from .config import Config
from .swis_client import SwisClient

log = logging.getLogger(__name__)


def compute_targets(alerted: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    wb = cfg.write_back
    scoped = alerted[alerted["entity_type"].isin(wb.entity_types)]
    if scoped.empty:
        return pd.DataFrame(columns=["entity_type", "entity_id", "entity_name", "anomalous", "causes"])

    latest = scoped.sort_values("timestamp").groupby(
        ["entity_type", "entity_id", "entity_name", "metric_name"], as_index=False
    ).tail(1)

    def _agg(g: pd.DataFrame) -> pd.Series:
        anomalous = bool(g["active"].any())
        causes = ", ".join(sorted(g.loc[g["active"], "metric_name"].unique())) if anomalous else ""
        return pd.Series({"anomalous": anomalous, "causes": causes})

    targets = latest.groupby(["entity_type", "entity_id", "entity_name"]).apply(_agg).reset_index()
    return targets


def apply_write_back(client: SwisClient, cfg: Config, alerted: pd.DataFrame, dry_run: bool) -> pd.DataFrame:
    """`client` is used even in dry-run mode — looking up an entity's real URI
    is a read, not a write, so dry-run previews still show the exact target."""
    wb = cfg.write_back
    targets = compute_targets(alerted, cfg)

    for _, row in targets.iterrows():
        et = cfg.entity_types[row["entity_type"]]
        value = wb.anomaly_value if row["anomalous"] else wb.normal_value
        uri = client.custom_property_uri(et.swql_entity, et.id_field, row["entity_id"])
        if dry_run or not wb.enabled:
            log.info(
                "[dry-run] would set %s.%s = %r on %s (%s)%s",
                et.swql_entity, wb.property_name, value, row["entity_name"], uri,
                f" - caused by: {row['causes']}" if row["causes"] else "",
            )
            continue
        client.update(uri, {wb.property_name: value})
        log.info(
            "Set %s.%s = %r on %s%s",
            et.swql_entity, wb.property_name, value, row["entity_name"],
            f" - caused by: {row['causes']}" if row["causes"] else "",
        )

    return targets
