"""Entity selection via custom-property predicates.

Per the build brief: don't assume a group/custom-property API beyond what
SWIS exposes. Each entity type declares its own custom property name (config-
driven — see config.example.yaml `entity_types`), so adding a new entity type
later (e.g. virtualization hosts) is a config change, not a code change,
as long as it exposes a `CustomProperties` navigation property in SWQL.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import EntityTypeConfig
from .swis_client import SwisClient
from .swis_queries import build_entity_discovery_query

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Entity:
    entity_type: str
    entity_id: int
    entity_name: str


def discover_in_scope_entities(client: SwisClient, et: EntityTypeConfig) -> list[Entity]:
    swql = build_entity_discovery_query(et)
    rows = client.query(swql)
    entities = [
        Entity(entity_type=et.name, entity_id=int(r["EntityID"]), entity_name=r["EntityName"])
        for r in rows
    ]
    log.info(
        "Discovered %d in-scope %s entities via CustomProperties.%s",
        len(entities), et.name, et.in_scope_property,
    )
    return entities
