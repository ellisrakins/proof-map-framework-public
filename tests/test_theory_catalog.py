import json
from pathlib import Path

from proofmap import Edge, Layer, Node, NodeKind, NodeStatus, ProofMap
from proofmap.current_physics import build_current_physics_backbone_map
from proofmap.physics_catalog import (
    build_physics_theory_catalog,
    build_physics_theory_source_registry,
)
from proofmap.theories import (
    EvidenceStatus,
    TheoryCatalog,
    TheoryKind,
    TheoryMaturity,
    TheoryProfile,
    TheoryRelation,
    TheoryRelationKind,
    ValidityRegime,
    build_theory_scaffold,
    validate_theory_bindings,
    validate_theory_catalog,
)


def test_bundled_catalog_covers_standard_effective_and_emerging_families():
    catalog = build_physics_theory_catalog()
    validation = validate_theory_catalog(
        catalog,
        build_physics_theory_source_registry(),
        require_sources=True,
    )
    assert validation.ok
    assert not validation.warnings
    assert validation.profile_count >= 35
    assert validation.family_count >= 8
    assert validation.domain_count >= 20
    assert validation.maturity_counts["ESTABLISHED"] >= 10
    assert validation.maturity_counts["EFFECTIVE"] >= 4
    assert validation.maturity_counts["ACTIVE_RESEARCH"] >= 15
    assert validation.maturity_counts["SPECULATIVE"] >= 1


def test_theory_catalog_roundtrip_preserves_profiles_relations_and_regimes(tmp_path: Path):
    catalog = build_physics_theory_catalog()
    path = tmp_path / "theories.json"
    catalog.to_json(path)
    loaded = TheoryCatalog.from_json(path)
    assert set(loaded.profiles) == set(catalog.profiles)
    assert len(loaded.relations) == len(catalog.relations)
    profile = loaded.profiles["general_relativity"]
    assert profile.maturity == TheoryMaturity.ESTABLISHED
    assert profile.validity_regimes[0].id == "primary"
    assert "lorentzian_geometry" in profile.mathematical_frameworks


def test_semantic_validation_rejects_unknown_relations_and_hierarchy_cycles():
    def profile(profile_id: str) -> TheoryProfile:
        return TheoryProfile(
            id=profile_id,
            name=profile_id,
            kind=TheoryKind.THEORY,
            maturity=TheoryMaturity.ACTIVE_RESEARCH,
            evidence_status=EvidenceStatus.UNCONFIRMED,
            family="test",
            summary="test",
            domains=["test"],
            foundations=["foundation"],
            mathematical_frameworks=["algebra"],
            validity_regimes=[ValidityRegime("test", "test regime")],
            source_ids=["source.test"],
            last_verified="2026-07-26",
        )

    catalog = TheoryCatalog("Invalid", "1", "test")
    catalog.add_profile(profile("a"))
    catalog.add_profile(profile("b"))
    catalog.add_relation(TheoryRelation("a", "b", TheoryRelationKind.EXTENDS))
    catalog.add_relation(TheoryRelation("b", "a", TheoryRelationKind.EXTENDS))
    catalog.add_relation(TheoryRelation("a", "missing", TheoryRelationKind.USES))
    result = validate_theory_catalog(catalog)
    assert not result.ok
    assert "Unknown relation target: missing" in result.errors
    assert any(error.startswith("Theory hierarchy cycle:") for error in result.errors)


def test_current_physics_map_has_valid_many_to_many_theory_bindings():
    catalog = build_physics_theory_catalog()
    proof_map = build_current_physics_backbone_map()
    result = validate_theory_bindings(proof_map, catalog, require_any=True)
    assert result.ok
    assert not result.warnings
    assert result.node_counts["standard_model"] >= 8
    assert result.node_counts["lambda_cdm"] >= 6
    assert "string_m_theory" in proof_map.nodes["gap.quantum_gravity"].theory_ids
    assert "loop_quantum_gravity" in proof_map.nodes["gap.quantum_gravity"].theory_ids
    assert set(proof_map.metadata["theory_profile_ids"]).issubset(catalog.profiles)


def test_theory_slice_keeps_selected_and_shared_graph_elements():
    proof_map = ProofMap("Bound map")
    proof_map.add_node(Node("shared", "Shared", NodeKind.AXIOM, NodeStatus.CORE, Layer.CORE))
    proof_map.add_node(
        Node(
            "a",
            "Theory A",
            NodeKind.MODEL,
            NodeStatus.DERIVED,
            Layer.INTERIOR,
            theory_ids=["a"],
        )
    )
    proof_map.add_node(
        Node(
            "unrelated", "Unrelated shared", NodeKind.DEFINITION, NodeStatus.DERIVED, Layer.INTERIOR
        )
    )
    proof_map.add_node(
        Node(
            "b",
            "Theory B",
            NodeKind.MODEL,
            NodeStatus.DERIVED,
            Layer.INTERIOR,
            theory_ids=["b"],
        )
    )
    proof_map.add_edge(Edge("shared", "a", theory_ids=["a"]))
    proof_map.add_edge(Edge("shared", "b", theory_ids=["b"]))

    sliced = proof_map.theory_slice(["a"])
    assert set(sliced.nodes) == {"shared", "a"}
    assert [(edge.source, edge.target) for edge in sliced.edges] == [("shared", "a")]
    assert sliced.metadata["theory_profile_ids"] == ["a"]


def test_scaffold_turns_any_profile_into_a_runnable_proof_map(tmp_path: Path):
    catalog = build_physics_theory_catalog()
    proof_map = build_theory_scaffold(catalog, "loop_quantum_gravity")
    assert proof_map.validate() == []
    assert proof_map.core_node_ids()
    assert any(node.kind == NodeKind.GAP for node in proof_map.nodes.values())
    assert all(node.theory_ids == ["loop_quantum_gravity"] for node in proof_map.nodes.values())

    path = tmp_path / "lqg.json"
    proof_map.to_json(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    model = next(node for node in payload["nodes"] if node["id"] == "model.loop_quantum_gravity")
    assert model["formal_systems"]
    assert model["regime_dimensions"]["primary"] == {}

    established = build_theory_scaffold(catalog, "general_relativity")
    assert any(
        node.id.startswith("result.general_relativity") for node in established.nodes.values()
    )
