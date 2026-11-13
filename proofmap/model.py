"""
Typed proof-map data model.

A ProofMap is a directed dependency graph whose edges point from more primitive
or explanatory claims toward dependent claims/phenomena:

    core axiom -> definition -> theorem/model -> boundary phenomenon

The package does not prove physics. It makes the proof boundary explicit, ranks
open gaps, and computes geometry-inspired diagnostics.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from .integrity import atomic_write, finite_number, json_value, load_json


def _validate_fields(obj: Any) -> None:
    payload = asdict(obj)
    json_value(payload)
    numeric = {
        "explanatory_weight",
        "proof_cost",
        "uncertainty",
        "boundary_weight",
        "weight",
        "epoch_start",
        "epoch_end",
        "energy_scale_gev",
        "t",
    }
    collections = {"tags", "theory_ids", "formal_systems", "source_ids"}
    for name, value in payload.items():
        if name in numeric:
            if value is not None or name not in {"epoch_start", "epoch_end", "energy_scale_gev"}:
                finite_number(value, name, minimum=0)
        elif name in collections:
            if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                raise ValueError(f"TYPE {name}: expected list of strings")
        elif name == "regime_dimensions":
            if not isinstance(value, dict):
                raise ValueError("TYPE regime_dimensions: expected object")
        elif not isinstance(value, str):
            raise ValueError(f"TYPE {name}: expected string")
    start, end = payload.get("epoch_start"), payload.get("epoch_end")
    if start is not None and end is not None and start > end:
        raise ValueError("RANGE epoch_start must not exceed epoch_end")


class NodeKind(str, Enum):
    AXIOM = "AXIOM"
    PRIMITIVE_LAW = "PRIMITIVE_LAW"
    DEFINITION = "DEFINITION"
    THEOREM = "THEOREM"
    MODEL = "MODEL"
    REGIME = "REGIME"
    INTERFACE = "INTERFACE"
    BRIDGE = "BRIDGE"
    CONSTANT = "CONSTANT"
    OBSERVATION = "OBSERVATION"
    PHENOMENON = "PHENOMENON"
    UNCERTAINTY = "UNCERTAINTY"
    GAP = "GAP"
    FLOW = "FLOW"


class NodeStatus(str, Enum):
    CORE = "CORE"
    PROVED = "PROVED"
    DERIVED = "DERIVED"
    COMPUTED = "COMPUTED"
    EMPIRICAL = "EMPIRICAL"
    PROBABILISTIC = "PROBABILISTIC"
    ASSUMPTION = "ASSUMPTION"
    APPROXIMATION = "APPROXIMATION"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    EXTERNAL = "EXTERNAL"
    INDEPENDENT = "INDEPENDENT"


class Layer(str, Enum):
    CORE = "CORE"
    INTERIOR = "INTERIOR"
    BOUNDARY = "BOUNDARY"
    EXTERIOR = "EXTERIOR"


class EdgeKind(str, Enum):
    PROVES = "PROVES"
    DEPENDS_ON = "DEPENDS_ON"
    DEFINES = "DEFINES"
    BRIDGES = "BRIDGES"
    INTERFACE = "INTERFACE"
    LIMITS_TO = "LIMITS_TO"
    APPROXIMATES = "APPROXIMATES"
    EMPIRICALLY_CONSTRAINS = "EMPIRICALLY_CONSTRAINS"
    FLOWS_TO = "FLOWS_TO"
    TRANSFORMS_TO = "TRANSFORMS_TO"
    BLOCKS = "BLOCKS"


class EdgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROVED = "PROVED"
    COMPUTED = "COMPUTED"
    EMPIRICAL = "EMPIRICAL"
    ASSUMED = "ASSUMED"
    APPROXIMATE = "APPROXIMATE"
    GAP = "GAP"
    BLOCKED = "BLOCKED"


@dataclass
class Node:
    id: str
    label: str
    kind: NodeKind | str
    status: NodeStatus | str
    layer: Layer | str
    domain: str = "general"
    explanatory_weight: float = 1.0
    proof_cost: float = 1.0
    uncertainty: float = 0.0
    boundary_weight: float = 1.0
    epoch_start: float | None = None
    epoch_end: float | None = None
    energy_scale_gev: float | None = None
    statement: str = ""
    notes: str = ""
    tags: list[str] = field(default_factory=list)
    theory_ids: list[str] = field(default_factory=list)
    formal_systems: list[str] = field(default_factory=list)
    regime_dimensions: dict[str, Any] = field(default_factory=dict)
    source_ids: list[str] = field(default_factory=list)
    evidence_class: str = ""
    last_verified: str = ""
    validity_regime: str = ""
    uncertainty_kind: str = ""
    formalization_status: str = "none"

    def __post_init__(self) -> None:
        _validate_fields(self)
        self.kind = NodeKind(self.kind)
        self.status = NodeStatus(self.status)
        self.layer = Layer(self.layer)
        if not self.id:
            raise ValueError("Node id cannot be empty")
        for field_name in ("explanatory_weight", "proof_cost", "uncertainty", "boundary_weight"):
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(f"{field_name} must be nonnegative for node {self.id}")
        if self.uncertainty > 1:
            raise ValueError(f"uncertainty must be in [0, 1] for node {self.id}")
        self.theory_ids = sorted(set(self.theory_ids))
        self.formal_systems = sorted(set(self.formal_systems))

    def active_at(self, t: float) -> bool:
        if self.epoch_start is not None and t < self.epoch_start:
            return False
        if self.epoch_end is not None and t > self.epoch_end:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["kind"] = self.kind.value
        out["status"] = self.status.value
        out["layer"] = self.layer.value
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Node":
        return cls(**dict(data))


@dataclass
class Edge:
    source: str
    target: str
    kind: EdgeKind | str = EdgeKind.PROVES
    status: EdgeStatus | str = EdgeStatus.ACTIVE
    weight: float = 1.0
    proof_cost: float = 1.0
    uncertainty: float = 0.0
    statement: str = ""
    notes: str = ""
    tags: list[str] = field(default_factory=list)
    theory_ids: list[str] = field(default_factory=list)
    formal_systems: list[str] = field(default_factory=list)
    regime_dimensions: dict[str, Any] = field(default_factory=dict)
    source_ids: list[str] = field(default_factory=list)
    evidence_class: str = ""
    last_verified: str = ""
    validity_regime: str = ""
    uncertainty_kind: str = ""
    formalization_status: str = "none"

    def __post_init__(self) -> None:
        _validate_fields(self)
        self.kind = EdgeKind(self.kind)
        self.status = EdgeStatus(self.status)
        if not self.source or not self.target:
            raise ValueError("Edge source/target cannot be empty")
        for field_name in ("weight", "proof_cost", "uncertainty"):
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(
                    f"{field_name} must be nonnegative for edge {self.source}->{self.target}"
                )
        if self.uncertainty > 1:
            raise ValueError(f"edge uncertainty must be in [0, 1] for {self.source}->{self.target}")
        self.theory_ids = sorted(set(self.theory_ids))
        self.formal_systems = sorted(set(self.formal_systems))

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["kind"] = self.kind.value
        out["status"] = self.status.value
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Edge":
        return cls(**dict(data))


@dataclass
class Epoch:
    id: str
    label: str
    t: float
    notes: str = ""

    def __post_init__(self) -> None:
        _validate_fields(self)
        if not self.id:
            raise ValueError("Epoch id cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Epoch":
        return cls(**dict(data))


@dataclass
class ProofMap:
    title: str
    description: str = ""
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    epochs: list[Epoch] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: Node) -> None:
        if node.id in self.nodes:
            raise ValueError(f"Duplicate node id: {node.id}")
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        if edge.source not in self.nodes:
            raise KeyError(f"Edge source does not exist: {edge.source}")
        if edge.target not in self.nodes:
            raise KeyError(f"Edge target does not exist: {edge.target}")
        self.edges.append(edge)

    def add_epoch(self, epoch: Epoch) -> None:
        if any(existing.id == epoch.id for existing in self.epochs):
            raise ValueError(f"Duplicate epoch id: {epoch.id}")
        self.epochs.append(epoch)
        self.epochs.sort(key=lambda e: e.t)

    def validate(self) -> list[str]:
        errors: list[str] = []
        for key, node in self.nodes.items():
            try:
                Node.from_dict(node.to_dict())
                if key != node.id:
                    errors.append(f"ID_KEY_MISMATCH: {key}")
            except (ValueError, TypeError) as exc:
                errors.append(f"NODE_INVALID {key}: {exc}")
        if len({epoch.id for epoch in self.epochs}) != len(self.epochs):
            errors.append("DUPLICATE_EPOCH")
        for epoch in self.epochs:
            try:
                Epoch.from_dict(epoch.to_dict())
            except (ValueError, TypeError) as exc:
                errors.append(f"EPOCH_INVALID: {exc}")
        for edge in self.edges:
            try:
                Edge.from_dict(edge.to_dict())
            except (ValueError, TypeError) as exc:
                errors.append(f"EDGE_INVALID: {exc}")
            if edge.source not in self.nodes:
                errors.append(f"Missing source {edge.source} for edge to {edge.target}")
            if edge.target not in self.nodes:
                errors.append(f"Missing target {edge.target} for edge from {edge.source}")
        return errors

    def core_node_ids(self) -> list[str]:
        cores = [
            n.id
            for n in self.nodes.values()
            if n.layer == Layer.CORE or n.status == NodeStatus.CORE
        ]
        return sorted(cores)

    def boundary_node_ids(self) -> list[str]:
        boundary_kinds = {
            NodeKind.PHENOMENON,
            NodeKind.OBSERVATION,
            NodeKind.INTERFACE,
            NodeKind.UNCERTAINTY,
            NodeKind.GAP,
        }
        return sorted(
            n.id
            for n in self.nodes.values()
            if n.layer == Layer.BOUNDARY or n.kind in boundary_kinds
        )

    def exterior_node_ids(self) -> list[str]:
        return sorted(n.id for n in self.nodes.values() if n.layer == Layer.EXTERIOR)

    def outgoing(self) -> dict[str, list[Edge]]:
        out: dict[str, list[Edge]] = defaultdict(list)
        for edge in self.edges:
            out[edge.source].append(edge)
        return dict(out)

    def incoming(self) -> dict[str, list[Edge]]:
        inc: dict[str, list[Edge]] = defaultdict(list)
        for edge in self.edges:
            inc[edge.target].append(edge)
        return dict(inc)

    def successors(self, node_id: str) -> list[str]:
        return [edge.target for edge in self.outgoing().get(node_id, [])]

    def predecessors(self, node_id: str) -> list[str]:
        return [edge.source for edge in self.incoming().get(node_id, [])]

    def shortest_distances_from_core(
        self, edge_statuses: Iterable[EdgeStatus] | None = None
    ) -> dict[str, int]:
        if edge_statuses is None:
            allowed_statuses = set(EdgeStatus)
        else:
            allowed_statuses = {EdgeStatus(s) for s in edge_statuses}
        out = self.outgoing()
        distances: dict[str, int] = {}
        q: deque[str] = deque()
        for core in self.core_node_ids():
            distances[core] = 0
            q.append(core)
        while q:
            current = q.popleft()
            for edge in out.get(current, []):
                if edge.status not in allowed_statuses:
                    continue
                candidate = distances[current] + 1
                if edge.target not in distances or candidate < distances[edge.target]:
                    distances[edge.target] = candidate
                    q.append(edge.target)
        return distances

    def reachable_from_core(self, edge_statuses: Iterable[EdgeStatus] | None = None) -> set[str]:
        return set(self.shortest_distances_from_core(edge_statuses=edge_statuses).keys())

    def transitive_dependents(self, node_id: str) -> set[str]:
        seen: set[str] = set()
        q: deque[str] = deque([node_id])
        out = self.outgoing()
        while q:
            current = q.popleft()
            for edge in out.get(current, []):
                if edge.target not in seen:
                    seen.add(edge.target)
                    q.append(edge.target)
        seen.discard(node_id)
        return seen

    def induced_submap(self, node_ids: Iterable[str], title_suffix: str = "") -> "ProofMap":
        keep = set(node_ids)
        sub = ProofMap(
            title=f"{self.title}{title_suffix}",
            description=self.description,
            metadata=dict(self.metadata),
        )
        for node_id in sorted(keep):
            if node_id in self.nodes:
                sub.add_node(Node.from_dict(self.nodes[node_id].to_dict()))
        for edge in self.edges:
            if edge.source in keep and edge.target in keep:
                sub.add_edge(Edge.from_dict(edge.to_dict()))
        sub.epochs = list(self.epochs)
        return sub

    def time_slice(self, t: float, title_suffix: str | None = None) -> "ProofMap":
        active = {node.id for node in self.nodes.values() if node.active_at(t)}
        suffix = title_suffix if title_suffix is not None else f" @ t={t:g}"
        return self.induced_submap(active, title_suffix=suffix)

    def theory_slice(
        self,
        theory_ids: Iterable[str],
        *,
        include_shared: bool = True,
        title_suffix: str | None = None,
    ) -> "ProofMap":
        selected = set(theory_ids)
        if not selected:
            raise ValueError("theory_slice requires at least one theory id")
        keep = {node.id for node in self.nodes.values() if selected.intersection(node.theory_ids)}
        if include_shared and keep:
            changed = True
            while changed:
                changed = False
                for edge in self.edges:
                    if edge.theory_ids and not selected.intersection(edge.theory_ids):
                        continue
                    if (
                        edge.source in keep
                        and edge.target not in keep
                        and not self.nodes[edge.target].theory_ids
                    ):
                        keep.add(edge.target)
                        changed = True
                    if (
                        edge.target in keep
                        and edge.source not in keep
                        and not self.nodes[edge.source].theory_ids
                    ):
                        keep.add(edge.source)
                        changed = True
        suffix = title_suffix or f" [{', '.join(sorted(selected))}]"
        sliced = self.induced_submap(keep, title_suffix=suffix)
        sliced.edges = [
            edge
            for edge in sliced.edges
            if selected.intersection(edge.theory_ids) or (include_shared and not edge.theory_ids)
        ]
        sliced.metadata["theory_profile_ids"] = sorted(selected)
        return sliced

    def detect_cycles(self) -> list[list[str]]:
        # DFS cycle detector; returns representative simple cycles, deduplicated by set+start.
        out = self.outgoing()
        color: dict[str, int] = {node_id: 0 for node_id in self.nodes}
        stack: list[str] = []
        cycles: list[list[str]] = []
        seen_keys: set[tuple[str, ...]] = set()

        positions: dict[str, int] = {}
        for start in sorted(self.nodes):
            if color[start]:
                continue
            color[start] = 1
            stack.append(start)
            positions[start] = 0
            frames = [(start, iter(out.get(start, [])))]
            while frames:
                node_id, successors = frames[-1]
                edge = next(successors, None)
                if edge is None:
                    frames.pop()
                    positions.pop(node_id)
                    stack.pop()
                    color[node_id] = 2
                    continue
                nxt = edge.target
                if color[nxt] == 0:
                    color[nxt] = 1
                    positions[nxt] = len(stack)
                    stack.append(nxt)
                    frames.append((nxt, iter(out.get(nxt, []))))
                elif color[nxt] == 1:
                    cyc = stack[positions[nxt] :] + [nxt]
                    key = tuple(sorted(set(cyc)))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        cycles.append(cyc)
        return cycles

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "metadata": self.metadata,
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges],
            "epochs": [epoch.to_dict() for epoch in self.epochs],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProofMap":
        json_value(data)
        if not isinstance(data, dict) or set(data) - {
            "title",
            "description",
            "metadata",
            "nodes",
            "edges",
            "epochs",
        }:
            raise ValueError("UNKNOWN_FIELD or unsupported map version; explicitly migrate first")
        for key in ("title", "description"):
            if key in data and not isinstance(data[key], str):
                raise ValueError(f"TYPE {key}: expected string")
        for key in ("nodes", "edges", "epochs"):
            if not isinstance(data.get(key, []), list):
                raise ValueError(f"TYPE {key}: expected array")
        if not isinstance(data.get("metadata", {}), dict):
            raise ValueError("TYPE metadata: expected object")
        proof_map = cls(
            title=str(data.get("title", "Untitled ProofMap")),
            description=str(data.get("description", "")),
            metadata=dict(data.get("metadata", {})),
        )
        for node_data in data.get("nodes", []):
            proof_map.add_node(Node.from_dict(node_data))
        for edge_data in data.get("edges", []):
            proof_map.add_edge(Edge.from_dict(edge_data))
        for epoch_data in data.get("epochs", []):
            proof_map.add_epoch(Epoch.from_dict(epoch_data))
        return proof_map

    def to_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        text = json.dumps(self.to_dict(), indent=indent, sort_keys=True, allow_nan=False)
        if path is not None:
            atomic_write(path, text + "\n")
        return text

    @classmethod
    def from_json(cls, path_or_text: str | Path) -> "ProofMap":
        return cls.from_dict(load_json(path_or_text))

    def to_adjacency_text(self) -> str:
        out = self.outgoing()
        lines: list[str] = []
        for node_id in sorted(self.nodes):
            successors = ", ".join(edge.target for edge in out.get(node_id, [])) or "—"
            lines.append(f"{node_id} -> {successors}")
        return "\n".join(lines)
