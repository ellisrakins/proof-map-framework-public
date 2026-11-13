"""Compatibility adapter for evidence-action planning.

Legacy geometry deltas are zero: requesting evidence does not reduce measured
uncertainty or change authored statuses. Use paper_actions for exact subjects,
prerequisites and explicitly conditional closure witnesses.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .kernel import migrate
from .metrics import analyze
from .model import NodeStatus, ProofMap
from .paper_actions import plan_evidence_actions, simulate_evidence_actions


@dataclass(frozen=True)
class ScenarioOverlay:
    target: str
    action: str
    requested_status: str
    assumptions: tuple[str, ...] = ()


@dataclass
class ClosureCandidate:
    node_id: str
    label: str
    current_status: str
    proposed_status: str
    current_uncertainty: float
    proposed_uncertainty: float
    delta_volume: float
    delta_surface_area: float
    delta_roundness: float
    delta_density: float
    delta_closure_ratio: float
    delta_thickness: float
    score: float
    rationale: str
    action_ids: tuple[str, ...] = ()
    heuristic: str = "conditional-closure-planning.v1"
    expected_gain: float | None = None
    estimated_cost: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _actions_by_node(pm: ProofMap) -> tuple[Any, dict[str, list[dict[str, Any]]]]:
    graph = migrate(pm.to_dict())
    plan = plan_evidence_actions(graph)
    conclusions = {i.id: i.conclusion for i in graph.inferences}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for action in plan["actions"]:
        subject = action["subject"]["id"]
        node_id = conclusions.get(subject, subject)
        if node_id in pm.nodes:
            grouped.setdefault(node_id, []).append(action)
    return graph, grouped


def simulate_closure(
    pm: ProofMap,
    node_id: str,
    *,
    proposed_status: NodeStatus = NodeStatus.PROVED,
    proposed_uncertainty: float = 0.08,
) -> tuple[Any, Any, ProofMap]:
    """Return unchanged actual metrics and an explicitly hypothetical overlay.

    proposed_uncertainty is retained for call compatibility and has no effect;
    an unknown empirical outcome cannot justify lowering source uncertainty.
    """
    if node_id not in pm.nodes:
        raise KeyError(node_id)
    baseline = analyze(pm)
    mutated = ProofMap.from_dict(pm.to_dict())
    graph, grouped = _actions_by_node(pm)
    selected = [a["id"] for a in grouped.get(node_id, [])]
    overlay = ScenarioOverlay(
        node_id, "obtain and independently validate evidence", proposed_status.value
    )
    mutated.metadata["scenario_overlay"] = {
        **asdict(overlay),
        "authority": "PLANNING_ONLY",
        "execution": "NOT_RUN",
        "counterfactual": simulate_evidence_actions(graph, selected),
        "uncertainty": "UNCHANGED; proposed_uncertainty is a deprecated planning input",
    }
    after = analyze(mutated)
    return baseline, after, mutated


def rank_closure_candidates(pm: ProofMap, limit: int | None = None) -> list[ClosureCandidate]:
    """Legacy view ranked by declared blocker count, never geometric truth gain."""
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
        raise ValueError("ACTION_INVALID_LIMIT")
    candidates: list[ClosureCandidate] = []
    _, grouped = _actions_by_node(pm)
    for node_id, actions in grouped.items():
        node = pm.nodes[node_id]
        candidates.append(
            ClosureCandidate(
                node_id=node.id,
                label=node.label,
                current_status=NodeStatus(node.status).value,
                proposed_status=NodeStatus(node.status).value,
                current_uncertainty=node.uncertainty,
                proposed_uncertainty=node.uncertainty,
                delta_volume=0.0,
                delta_surface_area=0.0,
                delta_roundness=0.0,
                delta_density=0.0,
                delta_closure_ratio=0.0,
                delta_thickness=0.0,
                score=float(sum(len(a["reason_codes"]) for a in actions)),
                rationale="Proposed evidence actions: "
                + ", ".join(sorted({a["kind"] for a in actions}))
                + "; blocker-count planning heuristic; expected gain and cost unknown",
                action_ids=tuple(a["id"] for a in actions),
            )
        )
    candidates.sort(key=lambda c: (-c.score, c.node_id))
    if limit is not None:
        return candidates[:limit]
    return candidates
