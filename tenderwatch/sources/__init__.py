from __future__ import annotations

from datetime import datetime

from ..http import Http
from .base import Result, Source
from .epads import EpadsSource
from .epms import EpmsTendersSource
from .generic import GenericTableSource
from .ungm import UngmSource
from .worldbank import WorldBankSource

REGISTRY: dict[str, type[Source]] = {
    cls.type_name: cls
    for cls in (WorldBankSource, EpmsTendersSource, EpadsSource, GenericTableSource, UngmSource)
}


def build_sources(cfg: dict, http: Http, now: datetime) -> list[Source]:
    sources: list[Source] = []
    for entry in cfg.get("sources", []):
        if not entry.get("enabled", True):
            continue
        cls = REGISTRY.get(entry["type"])
        if cls is None:
            raise ValueError(f"unknown source type: {entry['type']}")
        params = {k: v for k, v in entry.items() if k not in ("name", "type", "enabled")}
        sources.append(cls(entry["name"], params, http, now))
    return sources


__all__ = ["Result", "Source", "build_sources", "REGISTRY"]
