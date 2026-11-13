"""Scientific distinctions and truth-boundary invariants for the curated example."""

from proofmap.gravity_example import SOURCES, build_gravity_transition_map
from proofmap.model import EdgeKind, EdgeStatus, NodeStatus, ProofMap
from proofmap.schema import validate


def test_gravity_map_schema_and_roundtrip():
    pm = build_gravity_transition_map()
    assert pm.validate() == []
    assert validate("proofmap", pm.to_dict()) == []
    assert ProofMap.from_dict(pm.to_dict()).to_dict() == pm.to_dict()
    assert len(pm.nodes) == 23
    assert len(pm.edges) == 36


def test_gravity_example_never_claims_formal_acceptance():
    pm = build_gravity_transition_map()
    assert pm.metadata["accepted_claims"] == 0
    assert pm.metadata["formal_verification"] == "NOT_RUN"
    assert all(n.status != NodeStatus.PROVED for n in pm.nodes.values())
    assert all(e.kind != EdgeKind.PROVES and e.status != EdgeStatus.PROVED for e in pm.edges)
    assert all(n.formalization_status == "not_formalized" for n in pm.nodes.values())
    assert all(n.uncertainty_kind == "NOT_ASSESSED" for n in pm.nodes.values())


def test_newton_limit_has_both_motion_and_field_equation_bridges():
    pm = build_gravity_transition_map()
    links = {(e.source, e.target, e.kind) for e in pm.edges}
    for bridge in ("bridge.geodesic", "bridge.poisson"):
        assert ("regime.newtonian", bridge, EdgeKind.DEPENDS_ON) in links
        assert (bridge, "newton.gravity", EdgeKind.APPROXIMATES) in links
    conditions = pm.nodes["regime.newtonian"].statement
    for condition in ("|Phi|/c^2", "v/c", "static", "pressure", "cosmological"):
        assert condition in conditions
    assert "(-,+,+,+)" in pm.nodes["bridge.geodesic"].statement


def test_sr_gr_and_observation_boundaries_are_not_conflated():
    pm = build_gravity_transition_map()
    assert "not by itself a theory of gravitation" in pm.nodes["sr.kinematics"].statement
    assert "not the total precession" in pm.nodes["boundary.mercury"].statement
    assert "v=c" in pm.nodes["boundary.light"].validity_regime
    assert "historical comparison" in pm.nodes["boundary.light"].statement
    assert "globally flat" in pm.nodes["boundary.tides"].statement
    assert "quantum gravity" in pm.nodes["limit.classical"].statement


def test_all_curated_content_has_traceable_sources():
    pm = build_gravity_transition_map()
    for row in [*pm.nodes.values(), *pm.edges]:
        assert row.source_ids
        assert set(row.source_ids) <= SOURCES.keys()
    assert all(source["url"].startswith("https://") for source in SOURCES.values())
    assert set(pm.metadata["guided_path"]) <= pm.nodes.keys()


def test_boundary_walkthrough_exposes_obligations_without_automatic_closure():
    pm = build_gravity_transition_map()
    stages = pm.metadata["boundary_walkthrough"]
    assert [s["id"] for s in stages[:6]] == [
        "scope",
        "frontier",
        "diagnose",
        "candidate",
        "test",
        "collapse",
    ]
    for stage in stages:
        assert all(
            stage[key] for key in ("title", "detail", "question", "evidence", "action", "outcome")
        )
        assert set(stage["node_ids"]) <= pm.nodes.keys()
        assert set(stage["source_ids"]) <= SOURCES.keys()
    for ident in ("gap.mercury", "gap.causality", "gap.light"):
        assert pm.nodes[ident].status == NodeStatus.GAP
        assert any(edge.source == ident and edge.target.startswith("gr.") for edge in pm.edges)
    assert "cannot derive GR" in stages[5]["outcome"]
    assert "NOT_FORMAL_PROOF" in pm.metadata["collapse_semantics"]


def test_entropy_research_branches_remain_distinct_and_conditional():
    pm = build_gravity_transition_map()
    stages = pm.metadata["boundary_walkthrough"]
    assert len(stages) == 9
    assert [s["id"] for s in stages[6:]] == [
        "entropy-frameworks",
        "entropy-assumptions",
        "entropy-tests",
    ]
    assert "Clausius" in pm.nodes["entropy.jacobson_assumptions"].statement
    assert "equipartition" in pm.nodes["entropy.verlinde2011"].statement
    assert "de Sitter" in pm.nodes["entropy.verlinde2016"].statement
    assert (
        "not proof that dark matter is unnecessary"
        in pm.nodes["entropy.verlinde2016"].validity_regime
    )
    assert pm.nodes["entropy.gap_microphysics"].status == NodeStatus.GAP
    assert pm.nodes["entropy.gap_tests"].status == NodeStatus.GAP
    assert "NOT_ESTABLISHED_REPLACEMENT" in pm.metadata["entropy_scope"]
    assert "remain open" in stages[-1]["outcome"]
