"""Minimal SWIS (SolarWinds Information Service) REST client.

Deliberately dependency-light (just `requests`) so this is portable across
Windows and Linux without needing the orionsdk package or its pywin32/.NET
ties. Implements only the standard, documented SWIS v3 REST surface:
Query, Create, Read, Update. This is the normal supported way to read Orion
data and to set custom property values — it is NOT a write path into any
internal ABA table or anomaly object.

`update()`'s URL shape was cross-checked against orionsdk-python's own
swisclient.py (POST straight to the entity's URI, no "/Update/" segment) to
resolve a write failure this instance's SwisUriParser reported unhelpfully.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

import requests
import urllib3

from .config import SwisConfig

log = logging.getLogger(__name__)


class SwisError(RuntimeError):
    pass


class SwisClient:
    def __init__(self, cfg: SwisConfig):
        self._cfg = cfg
        self._base = f"https://{cfg.host}:{cfg.port}/SolarWinds/InformationService/v3/Json"
        self._session = requests.Session()
        self._session.auth = (cfg.user, cfg.password)
        self._session.verify = cfg.verify_ssl
        if not cfg.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def query(self, swql: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        log.debug("SWQL query: %s | params=%s", swql, parameters)
        resp = self._session.post(
            f"{self._base}/Query",
            json={"query": swql, "parameters": parameters or {}},
            timeout=120,
        )
        self._raise_for_status(resp)
        return resp.json().get("results", [])

    def create(self, entity: str, properties: dict[str, Any]) -> str:
        resp = self._session.post(f"{self._base}/Create/{entity}", json=properties, timeout=60)
        self._raise_for_status(resp)
        return resp.json()

    def update(self, entity_uri: str, properties: dict[str, Any]) -> None:
        # No "/Update/" path segment — you POST directly to the entity's own URI
        # (this matches orionsdk-python's swisclient.py; an earlier version of
        # this method incorrectly prepended "Update/", which made the server's
        # own SwisUriParser fail with a confusing "Invalid scheme" error).
        resp = self._session.post(f"{self._base}/{entity_uri}", json=properties, timeout=60)
        self._raise_for_status(resp)

    def read(self, entity_uri: str) -> dict[str, Any]:
        resp = self._session.get(f"{self._base}/{entity_uri}", timeout=60)
        self._raise_for_status(resp)
        return resp.json()

    def get_entity_uri(self, swql_entity: str, id_field: str, entity_id: Any) -> str:
        """Ask SWIS for an object's own canonical `swis://` URI.

        Querying for it (rather than constructing it from the entity/id
        namespace ourselves) is what makes this work uniformly for both
        top-level entities (Orion.Nodes) and entities nested under a parent
        (Orion.NPM.Interfaces, whose real URI is nested under its owning
        Orion.Nodes) without this code needing to know each entity's nesting.
        """
        rows = self.query(
            f"SELECT Uri FROM {swql_entity} WHERE {id_field}=@id", {"id": entity_id}
        )
        if not rows:
            raise SwisError(f"No {swql_entity} row found for {id_field}={entity_id}")
        return rows[0]["Uri"]

    def custom_property_uri(self, swql_entity: str, id_field: str, entity_id: Any) -> str:
        """URI of an object's CustomProperties row, suitable for `update()`."""
        return self.get_entity_uri(swql_entity, id_field, entity_id) + "/CustomProperties"

    def _raise_for_status(self, resp: requests.Response) -> None:
        if resp.status_code >= 400:
            message = resp.text[:2000]
            try:
                message = resp.json().get("Message", message)
            except ValueError:
                pass
            log.debug("SWIS %s error body: %s", resp.status_code, resp.text[:4000])
            raise SwisError(f"SWIS {resp.status_code} for {resp.url}: {message}")


def in_clause(values: Iterable[Any]) -> str:
    """Render a SWQL-safe IN (...) list for numeric IDs only.

    Only ever call this with IDs that came back from a prior SWIS query
    (numeric NodeID/InterfaceID), never with free-text user input.
    """
    ids = [str(int(v)) for v in values]
    return "(" + ", ".join(ids) + ")"
