from pathlib import Path

from proofmap.examples import build_dynamic_cosmology_map, build_strong_weak_interface_map
from proofmap.surface import build_surface_layout, write_surface_points_csv
from proofmap.surface_visualize import render_surface_atlas_svg, render_surface_explorer_html


def test_surface_layout_uses_time_for_dynamic_map():
    pm = build_dynamic_cosmology_map()
    layout = build_surface_layout(pm)
    assert layout.coordinate_mode == "time"
    assert len(layout.points) == len(pm.nodes)
    assert any(edge.is_flow for edge in layout.edges)
    assert any(point.thickness > 0.8 for point in layout.points.values())


def test_surface_layout_uses_proof_depth_for_static_map():
    pm = build_strong_weak_interface_map()
    layout = build_surface_layout(pm)
    assert layout.coordinate_mode == "proof_depth"
    assert "qcd" in layout.domain_order
    assert layout.points["qcd.confinement"].proof_distance is not None


def test_surface_assets_write(tmp_path: Path):
    pm = build_strong_weak_interface_map()
    svg = tmp_path / "surface.svg"
    html = tmp_path / "surface.html"
    csv = tmp_path / "surface_points.csv"
    render_surface_atlas_svg(pm, svg)
    render_surface_explorer_html(pm, html)
    write_surface_points_csv(build_surface_layout(pm), csv)
    assert "Proof Surface Atlas" in svg.read_text(encoding="utf-8")
    html_text = html.read_text(encoding="utf-8")
    assert "Proof Surface Explorer" in html_text
    assert 'id="theoryFilter"' in html_text
    csv_header = csv.read_text(encoding="utf-8").splitlines()[0]
    assert "longitude_deg" in csv_header
    assert "theory_ids" in csv_header
