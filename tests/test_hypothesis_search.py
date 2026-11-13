import json
from pathlib import Path

from proofmap.examples import build_minimal_conops_map
from proofmap.hypothesis import (
    HypothesisCatalog,
    HypothesisProposal,
    rank_hypotheses,
    simulate_hypothesis,
    write_hypothesis_search,
)

CATALOG_PATH = Path("examples/hypotheses/minimal_conops_hypotheses.json")


def test_hypothesis_catalog_roundtrip():
    catalog = HypothesisCatalog.from_json(CATALOG_PATH)
    loaded = HypothesisCatalog.from_json(catalog.to_json())
    assert loaded.title == catalog.title
    assert [item.id for item in loaded.hypotheses] == [item.id for item in catalog.hypotheses]


def test_hypothesis_search_rewards_testable_mechanism():
    pm = build_minimal_conops_map()
    catalog = HypothesisCatalog.from_json(CATALOG_PATH)
    ranking = rank_hypotheses(pm, catalog.hypotheses)
    assert [item.hypothesis_id for item in ranking] == [
        "hypothesis.quadratic_drag",
        "hypothesis.clock_bias",
        "hypothesis.free_correction",
    ]
    assert ranking[0].score > ranking[1].score > ranking[2].score
    assert ranking[0].testability_bonus > ranking[2].testability_bonus


def test_hypothesis_simulation_does_not_mutate_original_map():
    pm = build_minimal_conops_map()
    catalog = HypothesisCatalog.from_json(CATALOG_PATH)
    proposal = catalog.hypotheses[0]
    before_status = pm.nodes["boundary.drag_residual"].status
    _, _, simulated = simulate_hypothesis(pm, proposal)
    assert pm.nodes["boundary.drag_residual"].status == before_status
    assert proposal.id not in pm.nodes
    assert proposal.id in simulated.nodes
    assert simulated.nodes["boundary.drag_residual"].status == before_status
    assert simulated.metadata["scenario_overlays"][0]["requested_status"] == "APPROXIMATION"


def test_invalid_hypothesis_is_reported_and_json_is_standard(tmp_path: Path):
    pm = build_minimal_conops_map()
    proposal = HypothesisProposal(
        id="hypothesis.invalid",
        label="Invalid candidate",
        description="Targets a missing node.",
        target_nodes=["missing.target"],
    )
    catalog = HypothesisCatalog(title="Invalid catalog", hypotheses=[proposal])
    ranking = rank_hypotheses(pm, catalog.hypotheses)
    assert not ranking[0].valid
    assert ranking[0].validation_errors == ["Missing target node: missing.target"]

    paths = write_hypothesis_search(pm, catalog, tmp_path)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["evaluations"][0]["score"] == -1_000_000_000.0
