from proofmap.examples import (
    build_dynamic_cosmology_map,
    build_minimal_conops_map,
    build_strong_weak_interface_map,
)
from proofmap.metrics import analyze, identify_defects, metrics_over_epochs


def test_minimal_conops_detects_intentional_gap():
    pm = build_minimal_conops_map()
    m = analyze(pm)
    assert m.node_count == 5
    assert m.gap_count == 1
    assert m.seam_count >= 1
    defects = identify_defects(pm)
    assert defects[0].id == "boundary.drag_residual"


def test_strong_weak_metrics_have_expected_defects():
    pm = build_strong_weak_interface_map()
    m = analyze(pm)
    assert m.node_count >= 10
    assert m.gap_count >= 3
    assert m.seam_count >= 1
    assert 0 <= m.roundness <= 1
    defects = identify_defects(pm)
    ids = {d.id for d in defects}
    assert "qcd.confinement" in ids
    assert "qcd.yang_mills_mass_gap" in ids


def test_cosmology_dynamic_metrics():
    pm = build_dynamic_cosmology_map()
    rows = metrics_over_epochs(pm)
    assert len(rows) >= 5
    assert rows[0]["epoch_id"] == "planck_boundary"
    assert any(row["gap_count"] >= 1 for row in rows)


def test_json_roundtrip(tmp_path):
    pm = build_strong_weak_interface_map()
    p = tmp_path / "map.json"
    pm.to_json(p)
    from proofmap import ProofMap

    loaded = ProofMap.from_json(p)
    assert loaded.title == pm.title
    assert len(loaded.nodes) == len(pm.nodes)
    assert len(loaded.edges) == len(pm.edges)
