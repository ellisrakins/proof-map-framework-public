"""Geometry-inspired diagnostics for typed proof maps."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .kernel import ClosureResult, closure, migrate, semantic_digest
from .model import (
    EdgeKind,
    EdgeStatus,
    Layer,
    NodeKind,
    NodeStatus,
    ProofMap,
)

GOOD_NODE_STATUSES = {
    NodeStatus.CORE,
    NodeStatus.PROVED,
    NodeStatus.DERIVED,
    NodeStatus.COMPUTED,
    NodeStatus.PROBABILISTIC,
    NodeStatus.EMPIRICAL,
    NodeStatus.INDEPENDENT,
}

GAPLIKE_NODE_STATUSES = {
    NodeStatus.GAP,
    NodeStatus.BLOCKED,
    NodeStatus.EXTERNAL,
}

ASSUMPTIONLIKE_NODE_STATUSES = {
    NodeStatus.ASSUMPTION,
    NodeStatus.APPROXIMATION,
}

INTERFACE_EDGE_KINDS = {
    EdgeKind.BRIDGES,
    EdgeKind.INTERFACE,
    EdgeKind.LIMITS_TO,
    EdgeKind.APPROXIMATES,
    EdgeKind.EMPIRICALLY_CONSTRAINS,
}


@dataclass
class Defect:
    id: str
    defect_type: str
    severity: float
    description: str
    affected_nodes: list[str]
    suggested_closure_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProofMapMetrics:
    node_count: int
    edge_count: int
    core_count: int
    boundary_count: int
    reachable_count: int
    explanatory_volume: float
    surface_area: float
    roundness: float
    density: float
    closure_ratio: float
    uncertainty_thickness: float
    hole_count: int
    seam_count: int
    gap_count: int
    assumption_count: int
    unexplained_parameter_count: int
    cycle_count: int
    proof_radius_mean: float
    proof_radius_variance: float
    proof_radius_max: float
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def status_confidence(status: NodeStatus) -> float:
    return {
        NodeStatus.CORE: 1.00,
        NodeStatus.PROVED: 1.00,
        NodeStatus.DERIVED: 0.95,
        NodeStatus.COMPUTED: 0.88,
        NodeStatus.PROBABILISTIC: 0.80,
        NodeStatus.EMPIRICAL: 0.65,
        NodeStatus.INDEPENDENT: 0.60,
        NodeStatus.APPROXIMATION: 0.45,
        NodeStatus.ASSUMPTION: 0.35,
        NodeStatus.EXTERNAL: 0.15,
        NodeStatus.GAP: 0.0,
        NodeStatus.BLOCKED: 0.0,
    }[status]


def edge_confidence(status: EdgeStatus) -> float:
    return {
        EdgeStatus.ACTIVE: 0.90,
        EdgeStatus.PROVED: 1.00,
        EdgeStatus.COMPUTED: 0.85,
        EdgeStatus.EMPIRICAL: 0.65,
        EdgeStatus.APPROXIMATE: 0.45,
        EdgeStatus.ASSUMED: 0.35,
        EdgeStatus.GAP: 0.0,
        EdgeStatus.BLOCKED: 0.0,
    }[status]


def _variance(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum((x - mean) ** 2 for x in values) / len(values)


def analyze(pm: ProofMap, *, accepted: ClosureResult | None = None) -> ProofMapMetrics:
    errors = pm.validate()
    if errors:
        raise ValueError("Invalid proof map:\n" + "\n".join(errors))

    distances = pm.shortest_distances_from_core()
    reachable = set(distances)
    boundary_ids = pm.boundary_node_ids()
    boundary_nodes = [pm.nodes[node_id] for node_id in boundary_ids]
    semantic = accepted if accepted is not None else closure(migrate(pm.to_dict()))
    if accepted is not None and accepted.graph_digest != semantic_digest(migrate(pm.to_dict())):
        raise ValueError("STALE_CLOSURE: result is bound to another graph")
    accepted_ids = set(semantic.closed)

    explanatory_volume = 0.0
    proof_cost_total = 0.0
    for node_id, node in pm.nodes.items():
        if node.layer == Layer.EXTERIOR:
            continue
        if node.layer == Layer.CORE:
            continue
        reachable_factor = 1.0 if node_id in reachable else 0.20
        uncertainty_discount = 1.0 - min(0.75, node.uncertainty)
        explanatory_volume += (
            node.explanatory_weight
            * status_confidence(node.status)
            * reachable_factor
            * uncertainty_discount
        )
        proof_cost_total += max(0.001, node.proof_cost)
    for edge in pm.edges:
        proof_cost_total += max(0.001, edge.proof_cost) * (1.0 + edge.uncertainty)

    surface_area = 0.0
    for node in boundary_nodes:
        status_penalty = 1.0
        if node.status in GAPLIKE_NODE_STATUSES:
            status_penalty = 1.75
        elif node.status in ASSUMPTIONLIKE_NODE_STATUSES:
            status_penalty = 1.35
        elif node.status in {
            NodeStatus.EMPIRICAL,
            NodeStatus.PROBABILISTIC,
            NodeStatus.APPROXIMATION,
        }:
            status_penalty = 1.10
        surface_area += node.boundary_weight * status_penalty * (1.0 + node.uncertainty)
    for edge in pm.edges:
        if edge.kind in INTERFACE_EDGE_KINDS or edge.status in {
            EdgeStatus.ASSUMED,
            EdgeStatus.APPROXIMATE,
            EdgeStatus.GAP,
            EdgeStatus.BLOCKED,
        }:
            surface_area += (
                0.40
                * edge.weight
                * (1.0 + edge.uncertainty)
                * (1.0 - edge_confidence(edge.status) + 0.50)
            )

    boundary_distances = [float(distances[nid]) for nid in boundary_ids if nid in distances]
    if boundary_distances:
        mean_radius = sum(boundary_distances) / len(boundary_distances)
        var_radius = _variance(boundary_distances)
        max_radius = max(boundary_distances)
        normalized_variance = var_radius / ((mean_radius * mean_radius) + 1e-9)
        uniformity = 1.0 / (1.0 + normalized_variance)
    else:
        mean_radius = var_radius = max_radius = 0.0
        uniformity = 0.0

    if boundary_nodes:
        closed_weight = sum(n.boundary_weight for n in boundary_nodes if n.id in accepted_ids)
        total_boundary_weight = sum(max(0.001, n.boundary_weight) for n in boundary_nodes)
        closure_ratio = min(1.0, closed_weight / total_boundary_weight)
    else:
        closure_ratio = 0.0  # empty denominator is not 100% evidence coverage

    roundness = max(0.0, min(1.0, uniformity * closure_ratio))
    density = explanatory_volume / max(0.001, proof_cost_total)

    if boundary_nodes:
        uncertainty_thickness = sum(
            n.uncertainty * n.boundary_weight for n in boundary_nodes
        ) / max(0.001, sum(n.boundary_weight for n in boundary_nodes))
    else:
        uncertainty_thickness = 0.0
    seam_edges = identify_seam_edges(pm)
    if seam_edges:
        uncertainty_thickness = min(
            1.0,
            uncertainty_thickness
            + 0.15 * sum(edge.uncertainty for edge in seam_edges) / len(seam_edges),
        )

    holes = identify_holes(pm)
    gaps = [
        n for n in pm.nodes.values() if n.status in GAPLIKE_NODE_STATUSES or n.kind == NodeKind.GAP
    ]
    assumptions = [n for n in pm.nodes.values() if n.status in ASSUMPTIONLIKE_NODE_STATUSES]
    unexplained_parameters = [
        n
        for n in pm.nodes.values()
        if n.kind == NodeKind.CONSTANT
        and n.status
        in {NodeStatus.EMPIRICAL, NodeStatus.ASSUMPTION, NodeStatus.GAP, NodeStatus.EXTERNAL}
    ]
    cycles = pm.detect_cycles()

    notes: list[str] = [
        "Authored statuses and graph reachability are not accepted proof evidence.",
        f"Closure uses {semantic.policy} ({semantic.dimension}); {len(semantic.closed)} accepted nodes.",
        "Volume, surface area, radii and hole_count are deprecated geometric heuristics, not topology or proof measures.",
    ]
    if holes:
        notes.append(
            f"{len(holes)} boundary/exterior nodes are gaplike or not reachable from the core."
        )
    if seam_edges:
        notes.append(f"{len(seam_edges)} interface or cross-domain seam edges detected.")
    if gaps:
        notes.append(f"{len(gaps)} gaplike nodes require closure work.")
    if cycles:
        notes.append(
            f"{len(cycles)} dependency cycles detected; confirm they are intentional feedback/coherence loops."
        )
    if not notes:
        notes.append("No structural defects detected by the current heuristic pass.")

    return ProofMapMetrics(
        node_count=len(pm.nodes),
        edge_count=len(pm.edges),
        core_count=len(pm.core_node_ids()),
        boundary_count=len(boundary_nodes),
        reachable_count=len(reachable),
        explanatory_volume=round(explanatory_volume, 4),
        surface_area=round(surface_area, 4),
        roundness=round(roundness, 4),
        density=round(density, 4),
        closure_ratio=round(closure_ratio, 4),
        uncertainty_thickness=round(uncertainty_thickness, 4),
        hole_count=len(holes),
        seam_count=len(seam_edges),
        gap_count=len(gaps),
        assumption_count=len(assumptions),
        unexplained_parameter_count=len(unexplained_parameters),
        cycle_count=len(cycles),
        proof_radius_mean=round(mean_radius, 4),
        proof_radius_variance=round(var_radius, 4),
        proof_radius_max=round(max_radius, 4),
        notes=notes,
    )


def identify_holes(pm: ProofMap) -> list[str]:
    reachable = pm.reachable_from_core()
    holes: list[str] = []
    for node_id in pm.boundary_node_ids() + pm.exterior_node_ids():
        node = pm.nodes[node_id]
        if node_id not in reachable or node.status in GAPLIKE_NODE_STATUSES:
            holes.append(node_id)
    return sorted(set(holes))


def identify_seam_edges(pm: ProofMap) -> list[Any]:
    seam_edges = []
    for edge in pm.edges:
        src = pm.nodes[edge.source]
        tgt = pm.nodes[edge.target]
        cross_domain = src.domain != tgt.domain
        seam_kind = edge.kind in INTERFACE_EDGE_KINDS
        uncertain = edge.uncertainty >= 0.35 or edge.status in {
            EdgeStatus.ASSUMED,
            EdgeStatus.APPROXIMATE,
            EdgeStatus.GAP,
            EdgeStatus.BLOCKED,
        }
        if (
            (cross_domain and seam_kind)
            or (cross_domain and uncertain)
            or (seam_kind and uncertain)
        ):
            seam_edges.append(edge)
    return seam_edges


def identify_defects(pm: ProofMap) -> list[Defect]:
    defects: list[Defect] = []

    for node in pm.nodes.values():
        if node.status in GAPLIKE_NODE_STATUSES or node.kind == NodeKind.GAP:
            downstream = pm.transitive_dependents(node.id)
            severity = (
                node.explanatory_weight
                + node.boundary_weight
                + sum(pm.nodes[n].explanatory_weight for n in downstream) * 0.25
            )
            closure = (
                "proof"
                if node.kind in {NodeKind.THEOREM, NodeKind.DEFINITION, NodeKind.PRIMITIVE_LAW}
                else "modeling + proof"
            )
            if node.kind in {NodeKind.OBSERVATION, NodeKind.PHENOMENON, NodeKind.CONSTANT}:
                closure = "experiment + bridge theorem"
            defects.append(
                Defect(
                    id=node.id,
                    defect_type="proof_gap"
                    if node.status == NodeStatus.GAP
                    else "blocked_or_external",
                    severity=round(severity, 4),
                    description=node.notes or node.statement or node.label,
                    affected_nodes=sorted(downstream),
                    suggested_closure_path=closure,
                )
            )

    for node_id in identify_holes(pm):
        node = pm.nodes[node_id]
        if node.status in GAPLIKE_NODE_STATUSES:
            continue  # already counted as a gap; avoid double reporting.
        defects.append(
            Defect(
                id=node_id,
                defect_type="hole_or_cavity",
                severity=round(node.boundary_weight * (1.0 + node.uncertainty), 4),
                description=f"Boundary/exterior node is not derivably connected to the core: {node.label}",
                affected_nodes=[node_id],
                suggested_closure_path="add bridge principles or derive from existing core",
            )
        )

    for edge in identify_seam_edges(pm):
        src = pm.nodes[edge.source]
        tgt = pm.nodes[edge.target]
        severity = (
            edge.weight * (1.0 + edge.uncertainty) * (1.0 - edge_confidence(edge.status) + 0.5)
        )
        defects.append(
            Defect(
                id=f"{edge.source}->{edge.target}",
                defect_type="seam_or_interface_tension",
                severity=round(severity, 4),
                description=edge.notes
                or f"Cross-domain/interface edge from {src.domain} to {tgt.domain}",
                affected_nodes=[edge.source, edge.target],
                suggested_closure_path="classify as proof, limit theorem, approximation theorem, empirical calibration, or independence result",
            )
        )

    for node in pm.nodes.values():
        if node.kind == NodeKind.CONSTANT and node.status in {
            NodeStatus.EMPIRICAL,
            NodeStatus.ASSUMPTION,
            NodeStatus.EXTERNAL,
            NodeStatus.GAP,
        }:
            defects.append(
                Defect(
                    id=node.id,
                    defect_type="unexplained_parameter",
                    severity=round(node.boundary_weight * (1.0 + node.uncertainty), 4),
                    description=node.notes or f"Parameter remains empirical/external: {node.label}",
                    affected_nodes=[node.id] + sorted(pm.transitive_dependents(node.id)),
                    suggested_closure_path="derive, constrain experimentally, or mark as irreducible boundary condition",
                )
            )

    defects.sort(key=lambda d: (-d.severity, d.defect_type, d.id))
    return defects


def metrics_over_epochs(pm: ProofMap) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for epoch in pm.epochs:
        sliced = pm.time_slice(epoch.t, title_suffix=f" — {epoch.label}")
        m = analyze(sliced)
        row = {
            "epoch_id": epoch.id,
            "epoch_label": epoch.label,
            "t": epoch.t,
            "epoch_notes": epoch.notes,
        }
        row.update(m.to_dict())
        rows.append(row)
    return rows
