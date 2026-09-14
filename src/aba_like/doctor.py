"""Connectivity + schema self-check against a real SWIS instance.

Run this once against your lab before trusting `fetch` output. This validates
by actually running the same queries `fetch` will run (with a harmless dummy
ID and a tiny time window), not by introspecting `Metadata.Property` — on at
least one real SWOSH instance that metadata table itself throws
("Data type Metadata.Entity not found"), so empirical probing turned out to
be the more reliable check anyway.
"""
from __future__ import annotations

import logging

import pandas as pd

from .config import Config
from .grouping import discover_in_scope_entities
from .swis_client import SwisClient, in_clause
from .swis_queries import QUERIES

log = logging.getLogger(__name__)

_DUMMY_ID = 1


def run_doctor(client: SwisClient, cfg: Config) -> bool:
    ok = True

    try:
        client.query("SELECT TOP 1 NodeID FROM Orion.Nodes")
        print("[OK]   SWIS connection and authentication succeeded")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Could not query SWIS at all: {exc}")
        return False

    print("\n-- Entity discovery (custom-property filter) --")
    for name, et in cfg.entity_types.items():
        try:
            entities = discover_in_scope_entities(client, et)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {name}: discovery query failed ({exc})")
            ok = False
            continue
        if not entities:
            print(
                f"[WARN] {name}: 0 entities matched CustomProperties.{et.in_scope_property} "
                f"- confirm the property name/value and that some {name}s are flagged"
            )
        else:
            sample = ", ".join(e.entity_name for e in entities[:5])
            print(f"[OK]   {name}: {len(entities)} in scope (e.g. {sample})")

    print("\n-- Metric queries (run for real, with a dummy ID and a 1-minute window) --")
    now = pd.Timestamp.now(tz="UTC")
    start = now - pd.Timedelta(minutes=1)
    swis_dt_fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    params = {"start": start.strftime(swis_dt_fmt), "end": now.strftime(swis_dt_fmt)}

    for metric in cfg.metrics:
        builder = QUERIES.get(metric.source)
        if builder is None:
            print(f"[FAIL] metric '{metric.name}': unknown source '{metric.source}'")
            ok = False
            continue
        et = cfg.entity_types.get(metric.entity_type)
        if et is None:
            print(f"[FAIL] metric '{metric.name}': unknown entity_type '{metric.entity_type}'")
            ok = False
            continue
        swql = builder(et, metric, in_clause([_DUMMY_ID]))
        try:
            client.query(swql, params)
            print(f"[OK]   metric '{metric.name}' ({metric.source}): query is valid")
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] metric '{metric.name}' ({metric.source}): {exc}")
            ok = False

    return ok
