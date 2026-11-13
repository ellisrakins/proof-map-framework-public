"""Conditional search over candidate mechanisms for open proof-map defects."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .integrity import atomic_write, load_json
from .metrics import ProofMapMetrics, analyze
from .model import Edge, EdgeKind, EdgeStatus, Layer, Node, NodeKind, NodeStatus, ProofMap


@dataclass
class HypothesisProposal:
    id: str
    label: str
    description: str
    target_nodes: list[str]
    input_nodes: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    predictions: list[str] = field(default_factory=list)
    proposed_status: NodeStatus | str = NodeStatus.APPROXIMATION
    proposed_uncertainty: float = 0.25
    complexity: float = 1.0
    falsifiability: float = 0.5
    prior_plausibility: float = 0.5
    domain: str = "hypothesis"
    source_ids: list[str] = field(default_factory=list)
    last_verified: str = ""

    def __post_init__(self) -> None:
        self.proposed_status = NodeStatus(self.proposed_status)
        if not self.id:
            raise ValueError("Hypothesis id cannot be empty")
        if not self.target_nodes:
            raise ValueError(f"Hypothesis {self.id} must target at least one node")
        if self.complexity < 0:
            raise ValueError(f"Hypothesis complexity must be nonnegative: {self.id}")
        for name in ("proposed_uncertainty", "falsifiability", "prior_plausibility"):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1] for hypothesis {self.id}")

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["proposed_status"] = self.proposed_status.value
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HypothesisProposal":
        return cls(**dict(data))


@dataclass
class HypothesisCatalog:
    title: str
    hypotheses: list[HypothesisProposal]
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "metadata": self.metadata,
            "hypotheses": [hypothesis.to_dict() for hypothesis in self.hypotheses],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HypothesisCatalog":
        return cls(
            title=str(data.get("title", "Untitled hypothesis catalog")),
            description=str(data.get("description", "")),
            metadata=dict(data.get("metadata", {})),
            hypotheses=[HypothesisProposal.from_dict(item) for item in data.get("hypotheses", [])],
        )

    def to_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        text = json.dumps(self.to_dict(), indent=indent, sort_keys=True)
        if path is not None:
            atomic_write(path, text + "\n")
        return text

    @classmethod
    def from_json(cls, path_or_text: str | Path) -> "HypothesisCatalog":
        return cls.from_dict(load_json(path_or_text))


@dataclass(frozen=True)
class HypothesisEvaluation:
    hypothesis_id: str
    label: str
    target_nodes: list[str]
    predictions: list[str]
    assumptions: list[str]
    proposed_status: str
    proposed_uncertainty: float
    delta_volume: float
    delta_surface_area: float
    delta_roundness: float
    delta_density: float
    delta_closure_ratio: float
    delta_thickness: float
    structural_gain: float
    testability_bonus: float
    plausibility_bonus: float
    complexity_penalty: float
    score: float
    valid: bool
    validation_errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_hypothesis(pm: ProofMap, proposal: HypothesisProposal) -> list[str]:
    errors: list[str] = []
    if proposal.id in pm.nodes:
        errors.append(f"Hypothesis node already exists: {proposal.id}")
    for node_id in proposal.input_nodes:
        if node_id not in pm.nodes:
            errors.append(f"Missing input node: {node_id}")
    for node_id in proposal.target_nodes:
        if node_id not in pm.nodes:
            errors.append(f"Missing target node: {node_id}")
    if proposal.proposed_status in {
        NodeStatus.CORE,
        NodeStatus.EXTERNAL,
        NodeStatus.GAP,
        NodeStatus.BLOCKED,
    }:
        errors.append(f"Unsupported conditional target status: {proposal.proposed_status.value}")
    return errors


def simulate_hypothesis(
    pm: ProofMap, proposal: HypothesisProposal
) -> tuple[ProofMapMetrics, ProofMapMetrics, ProofMap]:
    errors = validate_hypothesis(pm, proposal)
    if errors:
        raise ValueError("Invalid hypothesis:\n" + "\n".join(errors))

    baseline = analyze(pm)
    mutated = ProofMap.from_dict(pm.to_dict())
    candidate_uncertainty = max(0.05, 1.0 - proposal.prior_plausibility)
    mutated.add_node(
        Node(
            id=proposal.id,
            label=proposal.label,
            kind=NodeKind.MODEL,
            status=NodeStatus.ASSUMPTION,
            layer=Layer.INTERIOR,
            domain=proposal.domain,
            explanatory_weight=max(1.0, 0.5 * len(proposal.target_nodes)),
            proof_cost=max(0.1, proposal.complexity),
            uncertainty=candidate_uncertainty,
            statement=proposal.description,
            notes="Conditional hypothesis under comparison; not an established closure.",
            tags=["candidate_hypothesis"],
            source_ids=list(proposal.source_ids),
            evidence_class="hypothesis",
            last_verified=proposal.last_verified,
            uncertainty_kind="theoretical",
            formalization_status="none",
        )
    )

    for input_id in proposal.input_nodes:
        mutated.add_edge(
            Edge(
                source=input_id,
                target=proposal.id,
                kind=EdgeKind.BRIDGES,
                status=EdgeStatus.ASSUMED,
                proof_cost=max(0.1, proposal.complexity / max(1, len(proposal.input_nodes))),
                uncertainty=candidate_uncertainty,
                notes="Input used by candidate hypothesis.",
                tags=["candidate_hypothesis"],
                source_ids=list(proposal.source_ids),
                evidence_class="hypothesis",
                last_verified=proposal.last_verified,
                uncertainty_kind="theoretical",
            )
        )

    edge_status = EdgeStatus.APPROXIMATE
    if proposal.proposed_status in {NodeStatus.PROVED, NodeStatus.DERIVED, NodeStatus.COMPUTED}:
        edge_status = EdgeStatus.ACTIVE
    elif proposal.proposed_status == NodeStatus.EMPIRICAL:
        edge_status = EdgeStatus.EMPIRICAL

    for target_id in proposal.target_nodes:
        target = mutated.nodes[target_id]
        # A hypothetical plan never changes the authored or accepted status.
        mutated.metadata.setdefault("scenario_overlays", []).append(
            {
                "target": target_id,
                "requested_status": proposal.proposed_status.value,
                "assumptions": list(proposal.assumptions),
                "evidence": "NOT_RUN",
            }
        )
        target.uncertainty = min(target.uncertainty, proposal.proposed_uncertainty)
        mutated.add_edge(
            Edge(
                source=proposal.id,
                target=target_id,
                kind=EdgeKind.BRIDGES,
                status=edge_status,
                proof_cost=max(0.1, proposal.complexity / max(1, len(proposal.target_nodes))),
                uncertainty=proposal.proposed_uncertainty,
                notes="Conditional explanatory bridge; must survive listed predictions.",
                tags=["candidate_hypothesis"],
                source_ids=list(proposal.source_ids),
                evidence_class="hypothesis",
                last_verified=proposal.last_verified,
                uncertainty_kind="theoretical",
            )
        )

    return baseline, analyze(mutated), mutated


def evaluate_hypothesis(pm: ProofMap, proposal: HypothesisProposal) -> HypothesisEvaluation:
    errors = validate_hypothesis(pm, proposal)
    if errors:
        return HypothesisEvaluation(
            hypothesis_id=proposal.id,
            label=proposal.label,
            target_nodes=list(proposal.target_nodes),
            predictions=list(proposal.predictions),
            assumptions=list(proposal.assumptions),
            proposed_status=proposal.proposed_status.value,
            proposed_uncertainty=proposal.proposed_uncertainty,
            delta_volume=0.0,
            delta_surface_area=0.0,
            delta_roundness=0.0,
            delta_density=0.0,
            delta_closure_ratio=0.0,
            delta_thickness=0.0,
            structural_gain=0.0,
            testability_bonus=0.0,
            plausibility_bonus=0.0,
            complexity_penalty=0.0,
            score=-1_000_000_000.0,
            valid=False,
            validation_errors=errors,
        )

    before, after, _ = simulate_hypothesis(pm, proposal)
    delta_volume = after.explanatory_volume - before.explanatory_volume
    delta_surface = after.surface_area - before.surface_area
    delta_roundness = after.roundness - before.roundness
    delta_density = after.density - before.density
    delta_closure = after.closure_ratio - before.closure_ratio
    delta_thickness = after.uncertainty_thickness - before.uncertainty_thickness

    structural_gain = (
        4.0 * delta_roundness
        + 3.0 * delta_closure
        + 0.12 * delta_volume
        + 1.5 * delta_density
        - 0.03 * delta_surface
        - 2.0 * delta_thickness
    )
    prediction_bonus = 0.18 * min(5, len(proposal.predictions))
    testability_bonus = 1.4 * proposal.falsifiability + prediction_bonus
    plausibility_bonus = 0.7 * proposal.prior_plausibility
    complexity_penalty = 0.22 * proposal.complexity + 0.12 * len(proposal.assumptions)
    if not proposal.predictions:
        complexity_penalty += 0.8
    score = structural_gain + testability_bonus + plausibility_bonus - complexity_penalty

    return HypothesisEvaluation(
        hypothesis_id=proposal.id,
        label=proposal.label,
        target_nodes=list(proposal.target_nodes),
        predictions=list(proposal.predictions),
        assumptions=list(proposal.assumptions),
        proposed_status=proposal.proposed_status.value,
        proposed_uncertainty=proposal.proposed_uncertainty,
        delta_volume=round(delta_volume, 4),
        delta_surface_area=round(delta_surface, 4),
        delta_roundness=round(delta_roundness, 4),
        delta_density=round(delta_density, 4),
        delta_closure_ratio=round(delta_closure, 4),
        delta_thickness=round(delta_thickness, 4),
        structural_gain=round(structural_gain, 4),
        testability_bonus=round(testability_bonus, 4),
        plausibility_bonus=round(plausibility_bonus, 4),
        complexity_penalty=round(complexity_penalty, 4),
        score=round(score, 4),
        valid=True,
        validation_errors=[],
    )


def rank_hypotheses(
    pm: ProofMap, proposals: Iterable[HypothesisProposal]
) -> list[HypothesisEvaluation]:
    evaluations = [evaluate_hypothesis(pm, proposal) for proposal in proposals]
    evaluations.sort(key=lambda item: (not item.valid, -item.score, item.hypothesis_id))
    return evaluations


def render_hypothesis_report(pm: ProofMap, catalog: HypothesisCatalog) -> str:
    baseline = analyze(pm)
    evaluations = rank_hypotheses(pm, catalog.hypotheses)
    lines = [
        f"# {catalog.title}",
        "",
        catalog.description,
        "",
        "> Scores are conditional value-of-information estimates. They do not establish that a candidate is true.",
        "",
        "## Baseline",
        "",
        f"- Map: `{pm.title}`",
        f"- Gaps: {baseline.gap_count}",
        f"- Seams: {baseline.seam_count}",
        f"- Closure ratio: {baseline.closure_ratio}",
        "",
        "## Ranking",
        "",
        "| Rank | Hypothesis | Score | Structural gain | Testability | Complexity penalty | Targets |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for index, item in enumerate(evaluations, start=1):
        score = f"{item.score:.4g}" if item.valid else "invalid"
        targets = ", ".join(f"`{target}`" for target in item.target_nodes)
        lines.append(
            f"| {index} | `{item.hypothesis_id}` | {score} | {item.structural_gain:.4g} | "
            f"{item.testability_bonus:.4g} | {item.complexity_penalty:.4g} | {targets} |"
        )
    lines.extend(["", "## Candidate details", ""])
    for item in evaluations:
        lines.append(f"### {item.label}")
        lines.append("")
        lines.append(
            f"- Conditional status: `{item.proposed_status}` at uncertainty {item.proposed_uncertainty:.3g}"
        )
        lines.append(f"- Assumptions: {('; '.join(item.assumptions)) or 'none stated'}")
        lines.append(f"- Predictions: {('; '.join(item.predictions)) or 'none stated'}")
        if item.validation_errors:
            lines.append(f"- Validation errors: {'; '.join(item.validation_errors)}")
        lines.append("")
    return "\n".join(lines)


def write_hypothesis_search(
    pm: ProofMap,
    catalog: HypothesisCatalog,
    out_dir: str | Path,
    *,
    basename: str = "hypothesis_search",
) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    evaluations = rank_hypotheses(pm, catalog.hypotheses)
    paths = {
        "json": out / f"{basename}_ranking.json",
        "report": out / f"{basename}_report.md",
    }
    payload = {
        "map_title": pm.title,
        "catalog_title": catalog.title,
        "warning": "Conditional value-of-information ranking; not evidence that a hypothesis is true.",
        "baseline_metrics": analyze(pm).to_dict(),
        "evaluations": [evaluation.to_dict() for evaluation in evaluations],
    }
    paths["json"].write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths["report"].write_text(render_hypothesis_report(pm, catalog), encoding="utf-8")
    return paths
