import json
from pathlib import Path

from proofmap import Node, ProofMap
from proofmap.current_physics import (
    build_current_physics_backbone_map,
    build_current_physics_source_registry,
)
from proofmap.current_validation import (
    EXPECTED_BACKBONE_GAPS,
    run_current_physics_backbone_validation,
)
from proofmap.metrics import analyze, identify_defects
from proofmap.model import Layer, NodeKind, NodeStatus
from proofmap.sources import collect_source_ids_from_map, validate_source_coverage


def test_source_backed_node_roundtrip_preserves_provenance(tmp_path: Path):
    pm = ProofMap("Provenance Smoke")
    pm.add_node(
        Node(
            id="core.example",
            label="Example",
            kind=NodeKind.AXIOM,
            status=NodeStatus.CORE,
            layer=Layer.CORE,
            source_ids=["src.example"],
            evidence_class="review",
            last_verified="2026-06-05",
            validity_regime="test",
            uncertainty_kind="semantic",
            formalization_status="scaffold",
        )
    )
    path = tmp_path / "map.json"
    pm.to_json(path)
    loaded = ProofMap.from_json(path)
    node = loaded.nodes["core.example"]
    assert node.source_ids == ["src.example"]
    assert node.evidence_class == "review"
    assert node.last_verified == "2026-06-05"
    assert node.validity_regime == "test"
    assert node.uncertainty_kind == "semantic"
    assert node.formalization_status == "scaffold"


def test_current_physics_backbone_has_expected_source_coverage_and_gaps():
    pm = build_current_physics_backbone_map()
    registry = build_current_physics_source_registry()
    metrics = analyze(pm)
    defects = identify_defects(pm)
    defect_ids = {defect.id for defect in defects}

    assert metrics.node_count >= 40
    assert metrics.gap_count >= len(EXPECTED_BACKBONE_GAPS)
    assert metrics.seam_count >= 8
    assert EXPECTED_BACKBONE_GAPS.issubset(defect_ids)
    assert not validate_source_coverage(pm, registry)
    assert collect_source_ids_from_map(pm).issubset(registry.sources)


def test_current_physics_validation_writes_artifacts_and_summary(tmp_path: Path):
    result = run_current_physics_backbone_validation(tmp_path, require_lean=False)
    assert result.ok
    assert result.summary_path.exists()
    assert not result.source_coverage_errors
    assert not result.theory_catalog_errors
    assert not result.theory_binding_errors
    assert EXPECTED_BACKBONE_GAPS.issubset(result.defect_ids)

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert summary["metrics"]["node_count"] >= 40
    assert summary["source_coverage_errors"] == []
    assert summary["theory_catalog_errors"] == []
    assert summary["theory_binding_errors"] == []
    for path in summary["artifact_paths"].values():
        assert Path(path).exists()
