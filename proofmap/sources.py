"""Source registry utilities for source-backed proof maps."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .integrity import atomic_write, load_json


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    url: str
    source_type: str
    publisher: str = ""
    publication_date: str = ""
    checked_date: str = ""
    notes: str = ""
    domains: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Source":
        return cls(**dict(data))


@dataclass
class SourceRegistry:
    sources: dict[str, Source] = field(default_factory=dict)

    def add(self, source: Source) -> None:
        if source.id in self.sources:
            raise ValueError(f"Duplicate source id: {source.id}")
        self.sources[source.id] = source

    def missing(self, source_ids: Iterable[str]) -> list[str]:
        return sorted({source_id for source_id in source_ids if source_id not in self.sources})

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": [
                source.to_dict() for source in sorted(self.sources.values(), key=lambda s: s.id)
            ]
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceRegistry":
        registry = cls()
        for source_data in data.get("sources", []):
            registry.add(Source.from_dict(source_data))
        return registry

    def to_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        text = json.dumps(self.to_dict(), indent=indent, sort_keys=True)
        if path is not None:
            atomic_write(path, text + "\n")
        return text

    @classmethod
    def from_json(cls, path_or_text: str | Path) -> "SourceRegistry":
        return cls.from_dict(load_json(path_or_text))


def collect_source_ids_from_map(proof_map: Any) -> set[str]:
    """Collect source IDs from all source-aware nodes and edges in a proof map."""

    source_ids: set[str] = set()
    for node in proof_map.nodes.values():
        source_ids.update(getattr(node, "source_ids", []))
    for edge in proof_map.edges:
        source_ids.update(getattr(edge, "source_ids", []))
    return source_ids


def validate_source_coverage(proof_map: Any, registry: SourceRegistry) -> list[str]:
    """Return source coverage errors for a proof map."""

    errors: list[str] = []
    referenced = collect_source_ids_from_map(proof_map)
    missing = registry.missing(referenced)
    if missing:
        errors.append("Missing source registry entries: " + ", ".join(missing))
    for node in proof_map.nodes.values():
        if not getattr(node, "source_ids", []):
            errors.append(f"Node has no source_ids: {node.id}")
        if not getattr(node, "last_verified", ""):
            errors.append(f"Node has no last_verified date: {node.id}")
    for edge in proof_map.edges:
        if not getattr(edge, "source_ids", []):
            errors.append(f"Edge has no source_ids: {edge.source}->{edge.target}")
    return errors
