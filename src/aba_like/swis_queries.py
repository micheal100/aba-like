"""SWQL query builders.

IMPORTANT — validated against the lab, but confirm before trusting output
in a different environment: field/entity names below were confirmed by
running `aba-like doctor` against a real SWOSH instance, which turned out to
differ from generic Orion NPM documentation in a few ways:

- No `CustomProperties` navigation property on `Orion.Nodes` /
  `Orion.NPM.Interfaces` here — custom properties must be reached with an
  explicit JOIN to `Orion.NodesCustomProperties` / `Orion.NPM.InterfacesCustomProperties`.
- `Metadata.Property` itself errors on this instance ("Data type
  Metadata.Entity not found"), so `doctor` validates by running the real
  queries below with a harmless dummy ID/time range instead of introspecting
  metadata.
- Interface traffic bps columns are `InAverageBps`/`OutAverageBps` (no
  underscore, capital B), not the commonly-documented `In_Averagebps`.
- There is no generic per-node historical memory table (`Orion.MemoryUsage`
  doesn't exist here; the only memory history table is
  `Orion.APM.HistoricalMemory`, which is keyed by APM component, not NodeID,
  and requires the APM module to be monitoring that component). Memory is
  therefore NOT wired up as a default metric — see README.

If you point this at a different SolarWinds instance, re-run `doctor` before
trusting it — table/column availability clearly varies by module/version.
"""
from __future__ import annotations

from typing import Callable

from .config import EntityTypeConfig, MetricConfig

# (entity_type_config, metric, ids) -> SWQL string returning
# columns: EntityID, DateTime, Value
QueryBuilder = Callable[[EntityTypeConfig, MetricConfig, str], str]


def _literal(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def custom_properties_entity(swql_entity: str) -> str:
    """e.g. 'Orion.Nodes' -> 'Orion.NodesCustomProperties'."""
    if "." not in swql_entity:
        raise ValueError(f"Unexpected SWQL entity name: {swql_entity}")
    namespace, base_name = swql_entity.rsplit(".", 1)
    return f"{namespace}.{base_name}CustomProperties"


def build_entity_discovery_query(et: EntityTypeConfig) -> str:
    cp_entity = custom_properties_entity(et.swql_entity)
    # None means "the property is truthy" — on this instance the in-scope
    # properties are booleans, so that means `= true`. If your custom
    # property is text-typed instead, set `in_scope_value` explicitly
    # (e.g. "Yes") in config.
    value = True if et.in_scope_value is None else et.in_scope_value
    predicate = f"cp.{et.in_scope_property} = {_literal(value)}"
    return (
        f"SELECT e.{et.id_field} AS EntityID, e.{et.name_field} AS EntityName "
        f"FROM {et.swql_entity} e "
        f"JOIN {cp_entity} cp ON cp.{et.id_field} = e.{et.id_field} "
        f"WHERE {predicate}"
    )


def _cpu_load(et: EntityTypeConfig, metric: MetricConfig, ids_in_clause: str) -> str:
    return (
        "SELECT NodeID AS EntityID, DateTime, AvgLoad AS Value "
        "FROM Orion.CPULoad "
        f"WHERE NodeID IN {ids_in_clause} "
        "AND DateTime >= @start AND DateTime < @end"
    )


def _response_time(et: EntityTypeConfig, metric: MetricConfig, ids_in_clause: str) -> str:
    return (
        "SELECT NodeID AS EntityID, DateTime, AvgResponseTime AS Value "
        "FROM Orion.ResponseTime "
        f"WHERE NodeID IN {ids_in_clause} "
        "AND DateTime >= @start AND DateTime < @end"
    )


def _packet_loss(et: EntityTypeConfig, metric: MetricConfig, ids_in_clause: str) -> str:
    return (
        "SELECT NodeID AS EntityID, DateTime, PercentLoss AS Value "
        "FROM Orion.ResponseTime "
        f"WHERE NodeID IN {ids_in_clause} "
        "AND DateTime >= @start AND DateTime < @end"
    )


def _interface_in_util(et: EntityTypeConfig, metric: MetricConfig, ids_in_clause: str) -> str:
    return (
        "SELECT t.InterfaceID AS EntityID, t.DateTime, "
        "(t.InAverageBps / i.InBandwidth) * 100 AS Value "
        "FROM Orion.NPM.InterfaceTraffic t "
        "JOIN Orion.NPM.Interfaces i ON i.InterfaceID = t.InterfaceID "
        f"WHERE t.InterfaceID IN {ids_in_clause} "
        "AND t.DateTime >= @start AND t.DateTime < @end "
        "AND i.InBandwidth > 0"
    )


def _interface_out_util(et: EntityTypeConfig, metric: MetricConfig, ids_in_clause: str) -> str:
    return (
        "SELECT t.InterfaceID AS EntityID, t.DateTime, "
        "(t.OutAverageBps / i.OutBandwidth) * 100 AS Value "
        "FROM Orion.NPM.InterfaceTraffic t "
        "JOIN Orion.NPM.Interfaces i ON i.InterfaceID = t.InterfaceID "
        f"WHERE t.InterfaceID IN {ids_in_clause} "
        "AND t.DateTime >= @start AND t.DateTime < @end "
        "AND i.OutBandwidth > 0"
    )


QUERIES: dict[str, QueryBuilder] = {
    "orion_cpu_load": _cpu_load,
    "orion_response_time": _response_time,
    "orion_packet_loss": _packet_loss,
    "orion_interface_in_util": _interface_in_util,
    "orion_interface_out_util": _interface_out_util,
}


def build_alert_history_query(node_ids_in_clause: str, name_like: str | None) -> str:
    """Best-effort: native alert (incl. ABA-generated) trigger/reset history for
    the given nodes, for comparing against this script's own fired events.
    Uses an explicit JOIN (not a `.` navigation property — confirmed unreliable
    on this instance's SWIS). Not yet validated against a real lab alert
    definition; validate with `doctor` or a manual query before trusting it.
    Bind `@name_like` in the query parameters when `name_like` is not None.
    """
    where = [f"o.RelatedNodeId IN {node_ids_in_clause}"]
    if name_like:
        where.append("ac.Name LIKE @name_like")
    return (
        "SELECT h.TimeStamp, h.EventType, h.Message, o.RelatedNodeId, "
        "o.RelatedNodeCaption, ac.Name AS AlertName "
        "FROM Orion.AlertHistory h "
        "JOIN Orion.AlertObjects o ON o.AlertObjID = h.AlertObjID "
        "JOIN Orion.AlertConfigurations ac ON ac.AlertID = o.AlertID "
        f"WHERE {' AND '.join(where)} "
        "AND h.TimeStamp >= @start AND h.TimeStamp < @end "
        "ORDER BY h.TimeStamp"
    )
