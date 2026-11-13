"""Proof-surface layout model.

This module turns a typed proof map into a visualizable surface model.
The surface is not intended to be a physically literal sphere. It is a stable
coordinate system for asking where proof-boundary phenomena sit, how flows
move across them, and which interior proof fibers support them.

Coordinate convention
---------------------
- Longitude clusters nodes by domain / local theory chart.
- Latitude is temporal if the map has epoch metadata; otherwise it is proof
  distance from the core.
- Radius is layer depth: core < interior < boundary < exterior.
- Boundary uncertainty becomes surface thickness / halo radius.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from math import log10, pi
from pathlib import Path
from typing import Any

from .integrity import csv_cell
from .metrics import analyze, identify_seam_edges
from .model import EdgeKind, EdgeStatus, Layer, Node, NodeStatus, ProofMap


@dataclass(frozen=True)
class SurfacePoint:
    id: str
    label: str
    kind: str
    status: str
    layer: str
    domain: str
    longitude: float
    latitude: float
    radius: float
    uncertainty: float
    thickness: float
    proof_distance: int | None
    active_start: float | None
    active_end: float | None
    energy_scale_gev: float | None
    explanatory_weight: float
    boundary_weight: float
    statement: str
    theory_ids: list[str]
    formal_systems: list[str]
    regime_dimensions: dict[str, Any]

    @property
    def longitude_deg(self) -> float:
        return self.longitude * 180.0 / pi

    @property
    def latitude_deg(self) -> float:
        return self.latitude * 180.0 / pi

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["longitude_deg"] = self.longitude_deg
        out["latitude_deg"] = self.latitude_deg
        return out


@dataclass(frozen=True)
class SurfaceEdge:
    source: str
    target: str
    kind: str
    status: str
    uncertainty: float
    weight: float
    proof_cost: float
    is_flow: bool
    is_seam: bool
    is_gaplike: bool
    statement: str
    theory_ids: list[str]
    formal_systems: list[str]
    regime_dimensions: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SurfaceLayout:
    title: str
    description: str
    coordinate_mode: str
    domain_order: list[str]
    points: dict[str, SurfacePoint]
    edges: list[SurfaceEdge]
    metrics: dict[str, Any]
    epochs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "coordinate_mode": self.coordinate_mode,
            "domain_order": self.domain_order,
            "metrics": self.metrics,
            "epochs": self.epochs,
            "points": {k: v.to_dict() for k, v in self.points.items()},
            "edges": [e.to_dict() for e in self.edges],
        }

    def to_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        text = json.dumps(self.to_dict(), indent=indent, sort_keys=True)
        if path is not None:
            Path(path).write_text(text + "\n", encoding="utf-8")
        return text


STATUS_THICKNESS_BONUS = {
    NodeStatus.CORE: 0.00,
    NodeStatus.PROVED: 0.00,
    NodeStatus.DERIVED: 0.02,
    NodeStatus.COMPUTED: 0.04,
    NodeStatus.EMPIRICAL: 0.09,
    NodeStatus.PROBABILISTIC: 0.13,
    NodeStatus.ASSUMPTION: 0.20,
    NodeStatus.APPROXIMATION: 0.18,
    NodeStatus.GAP: 0.35,
    NodeStatus.BLOCKED: 0.40,
    NodeStatus.EXTERNAL: 0.32,
    NodeStatus.INDEPENDENT: 0.16,
}

LAYER_RADIUS = {
    Layer.CORE: 0.18,
    Layer.INTERIOR: 0.62,
    Layer.BOUNDARY: 1.00,
    Layer.EXTERIOR: 1.15,
}


def has_temporal_surface(pm: ProofMap) -> bool:
    """Return True when a proof map has enough epoch data to use time as latitude."""

    if pm.epochs:
        return True
    return any(n.epoch_start is not None or n.epoch_end is not None for n in pm.nodes.values())


def _node_mid_time(node: Node) -> float | None:
    """Return a representative time for a node, preserving t=0 when provided."""

    if node.epoch_start is None and node.epoch_end is None:
        return None
    if node.epoch_start is not None and node.epoch_end is not None:
        start = max(0.0, node.epoch_start)
        end = max(0.0, node.epoch_end)
        if start == 0.0:
            return end / 2.0
        if end == 0.0:
            return start / 2.0
        return (start * end) ** 0.5
    if node.epoch_start is not None:
        return max(0.0, node.epoch_start)
    if node.epoch_end is not None:
        return max(0.0, node.epoch_end)
    return None


def _log_normalize(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.5
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _temporal_latitude(node: Node, log_min: float, log_max: float) -> float:
    mid = _node_mid_time(node)
    if mid is None:
        # Non-epoch foundations sit near the equator because they support all eras.
        return 0.0
    log_value = log10(max(mid, 1e-45))
    # Earliest times at north/top, later times at south/bottom.
    norm = _log_normalize(log_value, log_min, log_max)
    return (70.0 - 140.0 * norm) * pi / 180.0


def _proof_depth_latitude(node: Node, distance: int | None, max_distance: int) -> float:
    if node.layer == Layer.CORE:
        return 65.0 * pi / 180.0
    if distance is None:
        # Exterior and disconnected gaps sit below the closed proof surface.
        return -70.0 * pi / 180.0
    norm = distance / max(1, max_distance)
    return (62.0 - 124.0 * norm) * pi / 180.0


def _domain_longitudes(pm: ProofMap) -> tuple[list[str], dict[str, float]]:
    domains = sorted({node.domain for node in pm.nodes.values()}) or ["general"]
    if len(domains) == 1:
        return domains, {domains[0]: 0.0}
    return domains, {
        domain: -pi + (2.0 * pi * (i + 0.5) / len(domains)) for i, domain in enumerate(domains)
    }


def _offset_within_domain(index: int, count: int, n_domains: int) -> float:
    if count <= 1:
        return 0.0
    sector = 2.0 * pi / max(1, n_domains)
    spread = min(sector * 0.72, 0.72)
    return ((index / (count - 1)) - 0.5) * spread


def _surface_thickness(node: Node) -> float:
    bonus = STATUS_THICKNESS_BONUS[node.status]
    boundary_factor = 1.0 if node.layer in {Layer.BOUNDARY, Layer.EXTERIOR} else 0.55
    weight_factor = min(1.0, max(0.0, node.boundary_weight / 4.0))
    return min(1.0, node.uncertainty * boundary_factor + bonus + 0.08 * weight_factor)


def build_surface_layout(pm: ProofMap, *, coordinate_mode: str = "auto") -> SurfaceLayout:
    """Build a deterministic spherical surface layout for a proof map.

    Parameters
    ----------
    coordinate_mode:
        "auto" chooses temporal latitude when epoch data exists, otherwise proof-depth latitude.
        "time" forces temporal coordinates.
        "proof_depth" forces proof-distance coordinates.
    """

    errors = pm.validate()
    if errors:
        raise ValueError("Invalid proof map:\n" + "\n".join(errors))

    if coordinate_mode == "auto":
        mode = "time" if has_temporal_surface(pm) else "proof_depth"
    elif coordinate_mode in {"time", "proof_depth"}:
        mode = coordinate_mode
    else:
        raise ValueError("coordinate_mode must be one of: auto, time, proof_depth")

    domains, base_lons = _domain_longitudes(pm)
    ids_by_domain: dict[str, list[str]] = {domain: [] for domain in domains}
    for node in pm.nodes.values():
        ids_by_domain.setdefault(node.domain, []).append(node.id)
    for ids in ids_by_domain.values():
        ids.sort(key=lambda nid: (pm.nodes[nid].layer.value, pm.nodes[nid].status.value, nid))

    distances = pm.shortest_distances_from_core()
    max_distance = max(distances.values(), default=1)

    time_values: list[float] = []
    for node in pm.nodes.values():
        mid = _node_mid_time(node)
        if mid is not None:
            time_values.append(log10(max(mid, 1e-45)))
    if pm.epochs:
        time_values.extend(log10(max(epoch.t, 1e-45)) for epoch in pm.epochs)
    log_min = min(time_values, default=-45.0)
    log_max = max(time_values, default=18.0)

    points: dict[str, SurfacePoint] = {}
    for node in pm.nodes.values():
        ids = ids_by_domain[node.domain]
        idx = ids.index(node.id)
        lon = base_lons[node.domain] + _offset_within_domain(idx, len(ids), len(domains))
        # Keep longitudes in [-pi, pi].
        while lon < -pi:
            lon += 2.0 * pi
        while lon > pi:
            lon -= 2.0 * pi

        dist = distances.get(node.id)
        if mode == "time":
            lat = _temporal_latitude(node, log_min, log_max)
        else:
            lat = _proof_depth_latitude(node, dist, max_distance)

        radius = LAYER_RADIUS[node.layer]
        if node.layer == Layer.EXTERIOR:
            radius += 0.08 * node.uncertainty
        statement = node.statement or node.notes or ""
        points[node.id] = SurfacePoint(
            id=node.id,
            label=node.label,
            kind=node.kind.value,
            status=node.status.value,
            layer=node.layer.value,
            domain=node.domain,
            longitude=lon,
            latitude=lat,
            radius=radius,
            uncertainty=node.uncertainty,
            thickness=_surface_thickness(node),
            proof_distance=dist,
            active_start=node.epoch_start,
            active_end=node.epoch_end,
            energy_scale_gev=node.energy_scale_gev,
            explanatory_weight=node.explanatory_weight,
            boundary_weight=node.boundary_weight,
            statement=statement,
            theory_ids=list(node.theory_ids),
            formal_systems=list(node.formal_systems),
            regime_dimensions=dict(node.regime_dimensions),
        )

    seam_keys = {f"{edge.source}->{edge.target}" for edge in identify_seam_edges(pm)}
    surface_edges: list[SurfaceEdge] = []
    for edge in pm.edges:
        key = f"{edge.source}->{edge.target}"
        surface_edges.append(
            SurfaceEdge(
                source=edge.source,
                target=edge.target,
                kind=edge.kind.value,
                status=edge.status.value,
                uncertainty=edge.uncertainty,
                weight=edge.weight,
                proof_cost=edge.proof_cost,
                is_flow=edge.kind == EdgeKind.FLOWS_TO,
                is_seam=key in seam_keys,
                is_gaplike=edge.status in {EdgeStatus.GAP, EdgeStatus.BLOCKED},
                statement=edge.statement or edge.notes or "",
                theory_ids=list(edge.theory_ids),
                formal_systems=list(edge.formal_systems),
                regime_dimensions=dict(edge.regime_dimensions),
            )
        )

    metric_data = analyze(pm).to_dict()
    epoch_data = [epoch.to_dict() for epoch in pm.epochs]
    return SurfaceLayout(
        title=pm.title,
        description=pm.description,
        coordinate_mode=mode,
        domain_order=domains,
        points=points,
        edges=surface_edges,
        metrics=metric_data,
        epochs=epoch_data,
    )


def write_surface_points_csv(layout: SurfaceLayout, path: str | Path) -> None:
    """Write the surface layout as a point ledger for downstream visualization."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id",
        "label",
        "domain",
        "layer",
        "kind",
        "status",
        "theory_ids",
        "formal_systems",
        "regime_dimensions",
        "longitude_deg",
        "latitude_deg",
        "radius",
        "proof_distance",
        "uncertainty",
        "thickness",
        "boundary_weight",
        "active_start",
        "active_end",
        "energy_scale_gev",
        "statement",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for point in sorted(layout.points.values(), key=lambda p: (p.domain, p.layer, p.id)):
            row = point.to_dict()
            row["theory_ids"] = "; ".join(point.theory_ids)
            row["formal_systems"] = "; ".join(point.formal_systems)
            row["regime_dimensions"] = json.dumps(point.regime_dimensions, sort_keys=True)
            writer.writerow({key: csv_cell(row.get(key)) for key in fieldnames})


def write_surface_layout_json(layout: SurfaceLayout, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    layout.to_json(path)
