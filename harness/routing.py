"""C6 — retention-class routing.

Confidential or privileged text may only reach an endpoint whose registry entry
says zdr: true with a verified_on date. Public and synthetic text can go
anywhere. A route is a named policy over the registry:

  best-quality  any endpoint; refuses confidential/privileged data
  zdr           verified-ZDR endpoints only
  local         local endpoints only
  split         redact locally, reason anywhere, re-identify locally

The run refuses, with the endpoint and its verified_on named, rather than
sending. Silence is not an option here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from harness.spec import AgentSpec, DataClass

REGISTRY_PATH = Path(__file__).parent / "providers" / "registry.yaml"
Route = Literal["best-quality", "zdr", "local", "split"]
ROUTES: tuple[Route, ...] = ("best-quality", "zdr", "local", "split")
SENSITIVE: set[str] = {"confidential", "privileged"}


class RoutingRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class Endpoint:
    name: str
    adapter: str
    host: str
    preset: str | None
    zdr: bool | str
    local: bool
    verified_on: str | None
    retention_days: int | None
    note: str

    @property
    def is_zdr(self) -> bool:
        return self.zdr is True and bool(self.verified_on)

    def describe(self) -> str:
        z = "ZDR verified " + self.verified_on if self.is_zdr else f"zdr={self.zdr}, verified_on={self.verified_on}"
        return f"{self.name} ({self.host}; {z}; retention_days={self.retention_days})"


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Endpoint]:
    raw = yaml.safe_load(path.read_text()) or {}
    out: dict[str, Endpoint] = {}
    for name, e in raw.items():
        out[name] = Endpoint(
            name=name, adapter=e["adapter"], host=str(e.get("host", "")),
            preset=e.get("preset"), zdr=e.get("zdr", "unverified"), local=bool(e.get("local")),
            verified_on=e.get("verified_on"), retention_days=e.get("retention_days"),
            note=e.get("note", ""))
    return out


def endpoint_allows(endpoint: Endpoint, data_class: DataClass) -> tuple[bool, str]:
    if data_class in SENSITIVE and not endpoint.is_zdr:
        return False, (f"{data_class} text may not be sent to {endpoint.describe()}. "
                       "Only endpoints with zdr: true and a verified_on date qualify (C6).")
    return True, "ok"


def check_route(route: Route, endpoint: Endpoint, data_class: DataClass,
                stage_retention: str = "any") -> None:
    """Raise RoutingRefused if this endpoint may not serve this stage."""
    if route not in ROUTES:
        raise RoutingRefused(f"unknown route {route!r}; choose from {ROUTES}")
    if route == "local" and not endpoint.local:
        raise RoutingRefused(f"route=local but {endpoint.describe()} is not local")
    if route == "zdr" and not endpoint.is_zdr:
        raise RoutingRefused(f"route=zdr but {endpoint.describe()} is not verified ZDR")
    if stage_retention == "local" and not endpoint.local:
        raise RoutingRefused(f"stage requires local retention; {endpoint.describe()} is not local")
    if stage_retention == "zdr" and not endpoint.is_zdr:
        raise RoutingRefused(f"stage requires ZDR; {endpoint.describe()} is not verified ZDR")
    # On the split route the model only ever sees redacted text, so the
    # effective data class of the model stage is `synthetic`.
    effective = "synthetic" if route == "split" else data_class
    ok, why = endpoint_allows(endpoint, effective)
    if not ok:
        raise RoutingRefused(why)


def stage_retention(spec: AgentSpec, stage_name: str) -> str:
    for s in spec.stages:
        if s.name == stage_name:
            return s.retention
    return "any"
