"""Surface renderers for Proof Map Boundary Analysis.

The radial renderer shows the full proof-volume. This module shows the *surface*:
which boundary phenomena sit on which domain chart, how entropy/time/energy
flows traverse the surface, and where proof fibers, seams, holes, and uncertainty
thickness appear.
"""

from __future__ import annotations

import json
from math import pi
from pathlib import Path
from typing import Any

from .integrity import html_json
from .model import ProofMap
from .surface import (
    build_surface_layout,
    write_surface_layout_json,
    write_surface_points_csv,
)

STATUS_COLORS: dict[str, str] = {
    "CORE": "#FFD166",
    "PROVED": "#63D471",
    "DERIVED": "#4CC9F0",
    "COMPUTED": "#84DCC6",
    "EMPIRICAL": "#B9D6FF",
    "PROBABILISTIC": "#B8A7FF",
    "ASSUMPTION": "#FFE8A3",
    "APPROXIMATION": "#F8B26A",
    "GAP": "#FF6B6B",
    "BLOCKED": "#C1121F",
    "EXTERNAL": "#D7D7D7",
    "INDEPENDENT": "#D8C3A5",
}

LAYER_OPACITY = {
    "CORE": 0.78,
    "INTERIOR": 0.60,
    "BOUNDARY": 0.95,
    "EXTERIOR": 0.88,
}


def _escape(text: Any) -> str:
    s = str(text)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _wrap(text: str, max_chars: int = 38, max_lines: int = 3) -> list[str]:
    words = text.replace("/", "/ ").replace("–", "– ").split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def _atlas_xy(
    lon: float, lat: float, x: float, y: float, w: float, h: float
) -> tuple[float, float]:
    # Longitude [-pi, pi] -> x; latitude [+pi/2, -pi/2] -> y.
    px = x + ((lon + pi) / (2.0 * pi)) * w
    py = y + ((pi / 2.0 - lat) / pi) * h
    return px, py


def _node_radius(point: dict[str, Any]) -> float:
    layer = point["layer"]
    base = {"CORE": 5.5, "INTERIOR": 6.5, "BOUNDARY": 9.0, "EXTERIOR": 8.0}.get(layer, 7.0)
    return base + min(5.0, 1.25 * float(point.get("boundary_weight") or 1.0))


def _edge_style(edge: dict[str, Any]) -> tuple[str, float, str, str]:
    if edge.get("is_gaplike"):
        return "#b00020", 2.8, " stroke-dasharray='3 4'", "url(#arrowGap)"
    if edge.get("is_flow"):
        return "#0b6efd", 2.5, "", "url(#arrowFlow)"
    if edge.get("is_seam"):
        return "#d97706", 2.2, " stroke-dasharray='7 5'", "url(#arrowSeam)"
    return "#8395a7", 1.2, "", "url(#arrowDefault)"


def render_surface_atlas_svg(
    pm: ProofMap,
    path: str | Path,
    *,
    width: int = 1680,
    height: int = 1080,
    coordinate_mode: str = "auto",
) -> None:
    """Render a static SVG proof-surface atlas.

    The atlas is an unwrapped sphere. Longitude is domain / local theory chart.
    Latitude is time when available, otherwise proof depth. Uncertainty appears
    as halos around surface nodes, while flows, seams, and proof fibers are
    different line styles.
    """

    layout = build_surface_layout(pm, coordinate_mode=coordinate_mode)
    data = layout.to_dict()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    atlas_x, atlas_y, atlas_w, atlas_h = 70, 150, 1080, 650
    side_x, side_y, side_w = 1190, 150, 420
    bottom_y = 835

    lines: list[str] = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
    )
    lines.append("<defs>")
    lines.append(
        "  <linearGradient id='bg' x1='0' y1='0' x2='1' y2='1'><stop offset='0%' stop-color='#fbfdff'/><stop offset='100%' stop-color='#eef6ff'/></linearGradient>"
    )
    lines.append(
        "  <filter id='shadow'><feDropShadow dx='0' dy='4' stdDeviation='7' flood-opacity='0.15'/></filter>"
    )
    for name, color in [
        ("Default", "#8395a7"),
        ("Flow", "#0b6efd"),
        ("Seam", "#d97706"),
        ("Gap", "#b00020"),
    ]:
        lines.append(
            f"  <marker id='arrow{name}' markerWidth='10' markerHeight='8' refX='9' refY='4' orient='auto' markerUnits='strokeWidth'><path d='M 0 0 L 10 4 L 0 8 z' fill='{color}'/></marker>"
        )
    lines.append("</defs>")
    lines.append("<rect width='100%' height='100%' fill='url(#bg)'/>")
    lines.append(
        f"<text x='{width / 2}' y='58' text-anchor='middle' font-family='Helvetica, Arial, sans-serif' font-size='36' font-weight='800' fill='#0b1f4d'>{_escape(pm.title)} — Proof Surface Atlas</text>"
    )
    subtitle = "longitude = domain/local chart; latitude = " + (
        "cosmic time / active epoch"
        if layout.coordinate_mode == "time"
        else "derivational distance from core"
    )
    lines.append(
        f"<text x='{width / 2}' y='88' text-anchor='middle' font-family='Helvetica, Arial, sans-serif' font-size='16' fill='#4b5d78'>{_escape(subtitle)}</text>"
    )

    # Atlas panel.
    lines.append(
        f"<rect x='{atlas_x}' y='{atlas_y}' width='{atlas_w}' height='{atlas_h}' rx='20' fill='#ffffff' stroke='#234f8d' stroke-width='2' filter='url(#shadow)'/>"
    )
    lines.append(
        f"<clipPath id='atlasClip'><rect x='{atlas_x}' y='{atlas_y}' width='{atlas_w}' height='{atlas_h}' rx='20'/></clipPath>"
    )
    # Ocean/halo background.
    lines.append(
        f"<rect x='{atlas_x}' y='{atlas_y}' width='{atlas_w}' height='{atlas_h}' rx='20' fill='#f3f8ff'/>"
    )
    # Graticule.
    for i in range(1, 12):
        x = atlas_x + atlas_w * i / 12
        lines.append(
            f"<line x1='{x:.1f}' y1='{atlas_y}' x2='{x:.1f}' y2='{atlas_y + atlas_h}' stroke='#d7e4f5' stroke-width='1'/>"
        )
    for i in range(1, 6):
        y = atlas_y + atlas_h * i / 6
        lines.append(
            f"<line x1='{atlas_x}' y1='{y:.1f}' x2='{atlas_x + atlas_w}' y2='{y:.1f}' stroke='#d7e4f5' stroke-width='1'/>"
        )
    # Equator and pole-ish guide lines.
    equator_y = atlas_y + atlas_h / 2
    lines.append(
        f"<line x1='{atlas_x}' y1='{equator_y:.1f}' x2='{atlas_x + atlas_w}' y2='{equator_y:.1f}' stroke='#9fb9dc' stroke-width='1.6' stroke-dasharray='8 6'/>"
    )

    # Domain sector labels.
    n_domains = max(1, len(data["domain_order"]))
    for i, domain in enumerate(data["domain_order"]):
        x = atlas_x + atlas_w * (i + 0.5) / n_domains
        lines.append(
            f"<text x='{x:.1f}' y='{atlas_y - 15}' text-anchor='middle' font-family='Helvetica, Arial, sans-serif' font-size='12' font-weight='700' fill='#234f8d'>{_escape(domain)}</text>"
        )
        if i > 0:
            sx = atlas_x + atlas_w * i / n_domains
            lines.append(
                f"<line x1='{sx:.1f}' y1='{atlas_y}' x2='{sx:.1f}' y2='{atlas_y + atlas_h}' stroke='#b9cdea' stroke-width='1.4' stroke-dasharray='5 5'/>"
            )

    # Edges, clipped to atlas.
    lines.append("<g clip-path='url(#atlasClip)'>")
    points = data["points"]
    for edge in data["edges"]:
        if edge["source"] not in points or edge["target"] not in points:
            continue
        src = points[edge["source"]]
        tgt = points[edge["target"]]
        x1, y1 = _atlas_xy(src["longitude"], src["latitude"], atlas_x, atlas_y, atlas_w, atlas_h)
        x2, y2 = _atlas_xy(tgt["longitude"], tgt["latitude"], atlas_x, atlas_y, atlas_w, atlas_h)
        # Avoid drawing wrap-around lines across the whole atlas; splitless long lines are visually misleading.
        if abs(x2 - x1) > atlas_w * 0.55:
            continue
        color, sw, dash, marker = _edge_style(edge)
        opacity = 0.25 + 0.62 * (1.0 - min(1.0, float(edge["uncertainty"])))
        # Curved quadratic path to reduce overlaps.
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0 - 20.0 * (1 if edge.get("is_flow") else -0.5)
        lines.append(
            f"<path d='M {x1:.1f},{y1:.1f} Q {cx:.1f},{cy:.1f} {x2:.1f},{y2:.1f}' fill='none' stroke='{color}' stroke-width='{sw}' opacity='{opacity:.2f}' marker-end='{marker}'{dash}/>"
        )
    lines.append("</g>")

    # Uncertainty halos.
    for p in sorted(points.values(), key=lambda q: (q["layer"], q["uncertainty"])):
        if p["layer"] not in {"BOUNDARY", "EXTERIOR"}:
            continue
        x, y = _atlas_xy(p["longitude"], p["latitude"], atlas_x, atlas_y, atlas_w, atlas_h)
        halo = 8 + 24 * float(p["thickness"])
        color = STATUS_COLORS.get(p["status"], "#cccccc")
        lines.append(
            f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{halo:.1f}' fill='{color}' fill-opacity='0.17' stroke='{color}' stroke-opacity='0.22' stroke-width='1.2'/>"
        )

    # Nodes.
    for p in sorted(points.values(), key=lambda q: (q["layer"], q["status"], q["id"])):
        x, y = _atlas_xy(p["longitude"], p["latitude"], atlas_x, atlas_y, atlas_w, atlas_h)
        r = _node_radius(p)
        fill = STATUS_COLORS.get(p["status"], "#cccccc")
        opacity = LAYER_OPACITY.get(p["layer"], 0.8)
        stroke = "#1b2a41"
        sw = 1.2
        if p["status"] in {"GAP", "BLOCKED", "EXTERNAL"}:
            stroke, sw = "#831c1c", 2.2
        elif p["status"] in {"ASSUMPTION", "APPROXIMATION"}:
            stroke, sw = "#9a5a00", 2.0
        lines.append(
            f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r:.1f}' fill='{fill}' opacity='{opacity}' stroke='{stroke}' stroke-width='{sw}' filter='url(#shadow)'/>"
        )
        if p["layer"] in {"BOUNDARY", "EXTERIOR"} or p["status"] in {
            "GAP",
            "BLOCKED",
            "ASSUMPTION",
        }:
            label = p["label"]
            labels = _wrap(label, max_chars=22, max_lines=2)
            anchor = "start" if x < atlas_x + atlas_w * 0.72 else "end"
            tx = x + (13 if anchor == "start" else -13)
            ty = y - 3 * (len(labels) - 1)
            for j, line in enumerate(labels):
                lines.append(
                    f"<text x='{tx:.1f}' y='{ty + j * 12:.1f}' text-anchor='{anchor}' font-family='Helvetica, Arial, sans-serif' font-size='10.5' fill='#17223b'>{_escape(line)}</text>"
                )

    # Axis labels live inside the atlas panel so long labels are never clipped.
    if layout.coordinate_mode == "time":
        axis_top = "earlier / high-energy boundary"
        axis_mid = "transition belt / all-era support"
        axis_bottom = "later / emergent observers"
    else:
        axis_top = "near core"
        axis_mid = "interior derivation belt"
        axis_bottom = "boundary / disconnected gaps"
    for y, text in [
        (atlas_y + 24, axis_top),
        (equator_y - 8, axis_mid),
        (atlas_y + atlas_h - 16, axis_bottom),
    ]:
        lines.append(
            f"<rect x='{atlas_x + 8}' y='{y - 15:.1f}' width='188' height='21' rx='8' fill='#f8fbff' fill-opacity='0.82'/>"
        )
        lines.append(
            f"<text x='{atlas_x + 18}' y='{y:.1f}' text-anchor='start' font-family='Helvetica, Arial, sans-serif' font-size='12' fill='#53627a'>{_escape(text)}</text>"
        )

    # Side panel: metrics.
    lines.append(
        f"<rect x='{side_x}' y='{side_y}' width='{side_w}' height='330' rx='18' fill='#ffffff' stroke='#234f8d' stroke-width='2' filter='url(#shadow)'/>"
    )
    lines.append(
        f"<rect x='{side_x}' y='{side_y}' width='{side_w}' height='56' rx='18' fill='#123b79'/>"
    )
    lines.append(
        f"<text x='{side_x + side_w / 2}' y='{side_y + 36}' text-anchor='middle' font-family='Helvetica, Arial, sans-serif' font-size='20' font-weight='800' fill='white'>Surface Diagnostics</text>"
    )
    metric_rows = [
        ("Volume", data["metrics"].get("explanatory_volume")),
        ("Surface area", data["metrics"].get("surface_area")),
        ("Roundness", data["metrics"].get("roundness")),
        ("Closure", data["metrics"].get("closure_ratio")),
        ("Thickness", data["metrics"].get("uncertainty_thickness")),
        (
            "Gaps / seams / holes",
            f"{data['metrics'].get('gap_count')} / {data['metrics'].get('seam_count')} / {data['metrics'].get('hole_count')}",
        ),
    ]
    for i, (label, value) in enumerate(metric_rows):
        y = side_y + 88 + i * 36
        lines.append(
            f"<text x='{side_x + 24}' y='{y}' font-family='Helvetica, Arial, sans-serif' font-size='14' font-weight='700' fill='#0b1f4d'>{_escape(label)}</text>"
        )
        lines.append(
            f"<text x='{side_x + side_w - 24}' y='{y}' text-anchor='end' font-family='Helvetica, Arial, sans-serif' font-size='14' fill='#1f5eb8'>{_escape(value)}</text>"
        )
        lines.append(
            f"<line x1='{side_x + 20}' y1='{y + 12}' x2='{side_x + side_w - 20}' y2='{y + 12}' stroke='#e1e8f5'/>"
        )

    # Side panel: visual grammar.
    legend_y = side_y + 365
    lines.append(
        f"<rect x='{side_x}' y='{legend_y}' width='{side_w}' height='300' rx='18' fill='#ffffff' stroke='#58677d' stroke-width='1.7' filter='url(#shadow)'/>"
    )
    lines.append(
        f"<text x='{side_x + 22}' y='{legend_y + 34}' font-family='Helvetica, Arial, sans-serif' font-size='19' font-weight='800' fill='#0b1f4d'>Visual grammar</text>"
    )
    grammar = [
        ("#0b6efd", "solid arrow", "entropy/time or physical flow along surface"),
        ("#d97706", "dashed arrow", "seam: bridge, approximation, interface tension"),
        ("#b00020", "red dashed", "gap/blockage that deforms the boundary"),
        ("#8395a7", "thin fiber", "proof dependency or radial support"),
    ]
    for i, (color, label, desc) in enumerate(grammar):
        y = legend_y + 70 + i * 47
        dash = " stroke-dasharray='7 5'" if "dashed" in label else ""
        lines.append(
            f"<line x1='{side_x + 24}' y1='{y}' x2='{side_x + 90}' y2='{y}' stroke='{color}' stroke-width='3' marker-end='url(#arrowDefault)'{dash}/>"
        )
        lines.append(
            f"<text x='{side_x + 105}' y='{y - 5}' font-family='Helvetica, Arial, sans-serif' font-size='13' font-weight='700' fill='#17223b'>{_escape(label)}</text>"
        )
        lines.append(
            f"<text x='{side_x + 105}' y='{y + 12}' font-family='Helvetica, Arial, sans-serif' font-size='11.5' fill='#53627a'>{_escape(desc)}</text>"
        )

    # Bottom strip: domain surface balance.
    lines.append(
        f"<rect x='70' y='{bottom_y}' width='1540' height='175' rx='18' fill='#ffffff' stroke='#c7d6eb' stroke-width='1.6' filter='url(#shadow)'/>"
    )
    lines.append(
        f"<text x='95' y='{bottom_y + 34}' font-family='Helvetica, Arial, sans-serif' font-size='20' font-weight='800' fill='#0b1f4d'>Surface interpretation</text>"
    )
    statements = [
        "Boundary nodes are surface contact points: observations, phenomena, interfaces, gaps, or empirical attachments.",
        "Halos are uncertainty thickness: probability, approximation, measurement, computation, or proof debt.",
        "A rounder map would show shorter, more uniform proof fibers and fewer thick seams or disconnected holes.",
    ]
    for i, statement in enumerate(statements):
        lines.append(
            f"<text x='95' y='{bottom_y + 67 + i * 25}' font-family='Helvetica, Arial, sans-serif' font-size='14' fill='#32425f'>• {_escape(statement)}</text>"
        )
    if layout.coordinate_mode == "time":
        lines.append(
            f"<text x='95' y='{bottom_y + 147}' font-family='Helvetica, Arial, sans-serif' font-size='14' font-weight='700' fill='#14539a'>Dynamic read:</text>"
        )
        lines.append(
            f"<text x='205' y='{bottom_y + 147}' font-family='Helvetica, Arial, sans-serif' font-size='14' fill='#32425f'>phase transitions appear as folds/creases where the surface rule-texture changes over cosmic time.</text>"
        )
    else:
        lines.append(
            f"<text x='95' y='{bottom_y + 147}' font-family='Helvetica, Arial, sans-serif' font-size='14' font-weight='700' fill='#14539a'>Proof-depth read:</text>"
        )
        lines.append(
            f"<text x='220' y='{bottom_y + 147}' font-family='Helvetica, Arial, sans-serif' font-size='14' fill='#32425f'>deep boundary points are farther from the compact core; exterior points are unclosed or speculative attachments.</text>"
        )

    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_surface_explorer_html(
    pm: ProofMap, path: str | Path, *, coordinate_mode: str = "auto"
) -> None:
    """Render a standalone HTML proof-surface explorer.

    The explorer uses only embedded HTML/CSS/JavaScript and needs no network
    libraries. It provides a rotatable spherical projection, toggles for flows,
    seams, and uncertainty halos, an optional epoch slider, and a point table.
    """

    layout = build_surface_layout(pm, coordinate_mode=coordinate_mode)
    data = layout.to_dict()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    json_data = html_json(data)

    html = f"""<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
<title>{_escape(pm.title)} — Proof Surface Explorer</title>
<style>
:root {{
  --ink: #0b1f4d;
  --muted: #53627a;
  --panel: #ffffff;
  --line: #d9e5f6;
  --blue: #0b6efd;
  --orange: #d97706;
  --red: #b00020;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif; background: linear-gradient(135deg,#fbfdff,#eef6ff); color: var(--ink); }}
header {{ padding: 24px 32px 12px; }}
h1 {{ margin: 0; font-size: clamp(28px, 4vw, 44px); line-height: 1.05; }}
.subtitle {{ margin-top: 8px; color: var(--muted); max-width: 1050px; }}
main {{ display: grid; grid-template-columns: minmax(620px, 1fr) 390px; gap: 20px; padding: 12px 28px 30px; }}
.card {{ background: rgba(255,255,255,0.92); border: 1px solid var(--line); box-shadow: 0 12px 30px rgba(24,51,92,.10); border-radius: 20px; }}
#stageCard {{ padding: 18px; min-height: 720px; }}
canvas {{ width: 100%; height: 650px; display: block; border-radius: 16px; background: radial-gradient(circle at 35% 30%, #ffffff 0%, #f4f9ff 55%, #e9f2ff 100%); }}
.controls {{ display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; margin-top: 12px; align-items: center; }}
.control {{ background: #f7faff; border: 1px solid #d9e5f6; padding: 10px 12px; border-radius: 12px; font-size: 13px; }}
.control label {{ display: block; font-weight: 700; margin-bottom: 4px; }}
input[type=range] {{ width: 100%; }}
.side {{ display: grid; gap: 16px; align-content: start; }}
.panel {{ padding: 18px; }}
.panel h2 {{ margin: 0 0 10px; font-size: 18px; }}
.metric {{ display:flex; justify-content:space-between; gap:10px; padding: 8px 0; border-bottom: 1px solid #edf2fb; font-size:14px; }}
.metric b {{ color:#17376c; }}
.legendRow {{ display:grid; grid-template-columns: 76px 1fr; gap:10px; align-items:center; margin: 12px 0; color:var(--muted); font-size: 13px; }}
.swatchLine {{ height:0; border-top: 4px solid #8395a7; position:relative; }}
.swatchLine.flow {{ border-color: var(--blue); }}
.swatchLine.seam {{ border-color: var(--orange); border-top-style:dashed; }}
.swatchLine.gap {{ border-color: var(--red); border-top-style:dashed; }}
.swatchNode {{ width: 18px; height: 18px; border-radius: 50%; background:#ff6b6b; border:2px solid #831c1c; }}
#infoBox {{ min-height: 148px; line-height: 1.45; color: var(--muted); }}
#infoBox strong {{ color: var(--ink); }}
.tableCard {{ grid-column: 1 / -1; padding: 16px 18px; }}
table {{ width:100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ text-align:left; padding: 8px 7px; border-bottom: 1px solid #edf2fb; vertical-align:top; }}
th {{ color:#17376c; background:#f7faff; position: sticky; top: 0; }}
.badge {{ display:inline-block; padding:2px 7px; border-radius: 999px; background:#edf2fb; color:#17376c; font-weight:700; font-size:11px; }}
select {{ min-width: 190px; padding: 6px 8px; border: 1px solid #bdcbe0; background: #fff; color: var(--ink); }}
@media (max-width: 1100px) {{ main {{ grid-template-columns: 1fr; }} canvas {{ height: 560px; }} }}
</style>
</head>
<body>
<header>
  <h1>{_escape(pm.title)} — Proof Surface Explorer</h1>
  <div class=\"subtitle\">Interactive rendering of the theory surface. Longitude clusters domains/local charts; latitude is {_escape("cosmic time / active epoch" if layout.coordinate_mode == "time" else "derivational distance from the core")}. Energy/entropy flow is tangent to the surface; proof fibers point through the explanatory volume.</div>
</header>
<main>
  <section id=\"stageCard\" class=\"card\">
    <canvas id=\"globe\" width=\"1180\" height=\"760\" aria-label=\"Rotatable proof surface\"></canvas>
    <div class=\"controls\">
      <div class=\"control\"><label for=\"rot\">rotation</label><input id=\"rot\" type=\"range\" min=\"-180\" max=\"180\" value=\"0\" /></div>
      <div class=\"control\"><label for=\"tilt\">tilt</label><input id=\"tilt\" type=\"range\" min=\"-60\" max=\"60\" value=\"0\" /></div>
      <div class=\"control\"><label>layers</label><label><input id=\"boundaryOnly\" type=\"checkbox\" /> boundary only</label></div>
      <div class=\"control\"><label for=\"theoryFilter\">theory chart</label><select id=\"theoryFilter\"><option value=\"\">all theories</option></select></div>
      <div class=\"control\"><label>overlays</label><label><input id=\"showFlows\" type=\"checkbox\" checked /> flows</label> <label><input id=\"showSeams\" type=\"checkbox\" checked /> seams/gaps</label> <label><input id=\"showHalos\" type=\"checkbox\" checked /> uncertainty halos</label></div>
      <div class=\"control\" id=\"epochControl\"><label for=\"epoch\">epoch filter</label><input id=\"epoch\" type=\"range\" min=\"0\" max=\"0\" value=\"0\" /><div id=\"epochLabel\">all epochs</div></div>
      <div class=\"control\"><label>hover / click</label><span>Inspect a node to see its status, layer, uncertainty, and proof distance.</span></div>
    </div>
  </section>
  <aside class=\"side\">
    <section class=\"card panel\"><h2>Geometry metrics</h2><div id=\"metrics\"></div></section>
    <section class=\"card panel\"><h2>Visual grammar</h2>
      <div class=\"legendRow\"><div class=\"swatchLine flow\"></div><div>surface flow: entropy/time/physical sequence</div></div>
      <div class=\"legendRow\"><div class=\"swatchLine seam\"></div><div>seam: approximation, bridge, force/domain interface</div></div>
      <div class=\"legendRow\"><div class=\"swatchLine gap\"></div><div>gap/block: boundary defect or missing proof path</div></div>
      <div class=\"legendRow\"><div class=\"swatchLine\"></div><div>proof fiber: dependency from core/interior to surface</div></div>
      <div class=\"legendRow\"><div class=\"swatchNode\"></div><div>red node: open gap / blocked / external</div></div>
    </section>
    <section class=\"card panel\"><h2>Selected point</h2><div id=\"infoBox\">Move over a point on the surface.</div></section>
  </aside>
  <section class=\"card tableCard\"><h2>Surface ledger</h2><div style=\"max-height:420px; overflow:auto\"><table id=\"ledger\"></table></div></section>
</main>
<script id="proofmap-data" type="application/json">{json_data}</script>
<script>
const DATA = JSON.parse(document.getElementById('proofmap-data').textContent);
const colors = {json.dumps(STATUS_COLORS)};
const canvas = document.getElementById('globe');
const ctx = canvas.getContext('2d');
const rot = document.getElementById('rot');
const tilt = document.getElementById('tilt');
const boundaryOnly = document.getElementById('boundaryOnly');
const showFlows = document.getElementById('showFlows');
const showSeams = document.getElementById('showSeams');
const showHalos = document.getElementById('showHalos');
const theoryFilter = document.getElementById('theoryFilter');
const epoch = document.getElementById('epoch');
const epochLabel = document.getElementById('epochLabel');
const infoBox = document.getElementById('infoBox');
let selected = null;
let projected = [];
const points = Object.values(DATA.points);
const edges = DATA.edges;
const epochs = DATA.epochs || [];

function fmt(x) {{
  if (x === null || x === undefined) return '—';
  if (typeof x === 'number') {{
    if (Math.abs(x) >= 1e4 || (Math.abs(x) > 0 && Math.abs(x) < 1e-3)) return x.toExponential(2);
    return String(Math.round(x * 1000) / 1000);
  }}
  return String(x);
}}
function activeAt(p) {{
  if (theoryFilter.value && !(p.theory_ids || []).includes(theoryFilter.value)) return false;
  if (!epochs.length || Number(epoch.value) === 0) return true;
  const t = epochs[Number(epoch.value)-1].t;
  if (p.active_start !== null && p.active_start !== undefined && t < p.active_start) return false;
  if (p.active_end !== null && p.active_end !== undefined && t > p.active_end) return false;
  return true;
}}
function project(p) {{
  const lambda = p.longitude + Number(rot.value) * Math.PI / 180;
  const phi = p.latitude + Number(tilt.value) * Math.PI / 180;
  const r = Math.min(1.16, Math.max(0.15, p.radius));
  const cosPhi = Math.cos(phi), sinPhi = Math.sin(phi);
  const cosLam = Math.cos(lambda), sinLam = Math.sin(lambda);
  let x = r * cosPhi * sinLam;
  let y = r * sinPhi;
  let z = r * cosPhi * cosLam;
  const R = Math.min(canvas.width, canvas.height) * 0.38;
  return {{ id:p.id, x: canvas.width*0.47 + R*x, y: canvas.height*0.50 - R*y, z, visible: z > -0.08, p }};
}}
function drawGlobe() {{
  ctx.clearRect(0,0,canvas.width,canvas.height);
  const cx = canvas.width*0.47, cy = canvas.height*0.50, R = Math.min(canvas.width, canvas.height)*0.38;
  // sphere body
  const grad = ctx.createRadialGradient(cx-R*0.32, cy-R*0.34, R*0.05, cx, cy, R*1.08);
  grad.addColorStop(0, '#ffffff'); grad.addColorStop(0.55, '#f4f9ff'); grad.addColorStop(1, '#dfeeff');
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI*2); ctx.fillStyle = grad; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = '#234f8d'; ctx.stroke();
  // graticule
  ctx.save(); ctx.globalAlpha = 0.26; ctx.strokeStyle = '#6f91c5'; ctx.lineWidth = 1;
  for (let lat=-60; lat<=60; lat+=30) {{
    ctx.beginPath(); const yy = cy - R*Math.sin(lat*Math.PI/180); const rr = R*Math.cos(lat*Math.PI/180); ctx.ellipse(cx, yy, rr, rr*0.18, 0, 0, Math.PI*2); ctx.stroke();
  }}
  for (let lon=0; lon<180; lon+=30) {{
    ctx.beginPath(); ctx.ellipse(cx, cy, R*Math.abs(Math.cos(lon*Math.PI/180)), R, 0, 0, Math.PI*2); ctx.stroke();
  }}
  ctx.restore();

  projected = points.map(project).filter(q => activeAt(q.p) && (!boundaryOnly.checked || q.p.layer === 'BOUNDARY' || q.p.layer === 'EXTERIOR'));
  const byId = new Map(projected.map(q => [q.id, q]));
  // edges behind nodes
  for (const e of edges) {{
    if (e.is_flow && !showFlows.checked) continue;
    if ((e.is_seam || e.is_gaplike) && !showSeams.checked) continue;
    const a = byId.get(e.source), b = byId.get(e.target);
    if (!a || !b || !a.visible || !b.visible) continue;
    const ordinary = !e.is_flow && !e.is_seam && !e.is_gaplike;
    if (ordinary && boundaryOnly.checked) continue;
    ctx.save();
    ctx.globalAlpha = 0.25 + 0.55*(1-Math.min(1,e.uncertainty));
    ctx.lineWidth = e.is_gaplike ? 3 : e.is_flow ? 2.5 : e.is_seam ? 2.2 : 1.2;
    ctx.strokeStyle = e.is_gaplike ? '#b00020' : e.is_flow ? '#0b6efd' : e.is_seam ? '#d97706' : '#8395a7';
    if (e.is_gaplike || e.is_seam) ctx.setLineDash([8,6]);
    ctx.beginPath();
    ctx.moveTo(a.x,a.y);
    const mx=(a.x+b.x)/2, my=(a.y+b.y)/2 - (e.is_flow?20:-8);
    ctx.quadraticCurveTo(mx,my,b.x,b.y); ctx.stroke();
    ctx.restore();
  }}
  // halos and nodes
  const ordered = projected.slice().sort((a,b)=>a.z-b.z);
  for (const q of ordered) {{
    if (!q.visible) continue;
    const p=q.p; const col=colors[p.status] || '#cccccc';
    const base = p.layer==='CORE'?6:p.layer==='INTERIOR'?7:p.layer==='BOUNDARY'?10:9;
    const nr = base + Math.min(5, 1.2*(p.boundary_weight||1));
    if (showHalos.checked && (p.layer==='BOUNDARY' || p.layer==='EXTERIOR')) {{
      ctx.save(); ctx.globalAlpha = 0.14 + 0.10*p.thickness; ctx.fillStyle = col; ctx.beginPath(); ctx.arc(q.x,q.y, nr + 28*p.thickness,0,Math.PI*2); ctx.fill(); ctx.restore();
    }}
    ctx.save(); ctx.globalAlpha = p.layer==='INTERIOR'?0.68:p.layer==='CORE'?0.82:1;
    ctx.beginPath(); ctx.arc(q.x,q.y,nr,0,Math.PI*2); ctx.fillStyle=col; ctx.fill();
    ctx.lineWidth = (p.status==='GAP'||p.status==='BLOCKED'||p.status==='EXTERNAL')?2.6:(p.status==='ASSUMPTION'||p.status==='APPROXIMATION')?2.1:1.2;
    ctx.strokeStyle = (p.status==='GAP'||p.status==='BLOCKED'||p.status==='EXTERNAL')?'#831c1c':'#1b2a41'; ctx.stroke();
    if (selected && selected.id === p.id) {{ ctx.lineWidth=3.5; ctx.strokeStyle='#111827'; ctx.stroke(); }}
    ctx.restore();
  }}
  // title note inside canvas
  ctx.fillStyle = '#0b1f4d'; ctx.font = '700 22px system-ui, sans-serif'; ctx.fillText('rotatable proof surface', 26, 38);
  ctx.fillStyle = '#53627a'; ctx.font = '14px system-ui, sans-serif';
  ctx.fillText('time/entropy/energy flow moves tangent to surface; proof fibers point through the volume', 26, 63);
}}
function nearestNode(evt) {{
  const rect = canvas.getBoundingClientRect();
  const x = (evt.clientX - rect.left) * canvas.width / rect.width;
  const y = (evt.clientY - rect.top) * canvas.height / rect.height;
  let best=null, bestD=1e9;
  for (const q of projected) {{
    if (!q.visible) continue;
    const dx=q.x-x, dy=q.y-y; const d=Math.sqrt(dx*dx+dy*dy);
    if (d<bestD && d<24) {{ best=q.p; bestD=d; }}
  }}
  return best;
}}
function showInfo(p) {{
  if (!p) {{ infoBox.textContent = 'Move over a point on the surface.'; return; }}
  infoBox.textContent = [p.label, p.status, p.layer, p.domain,
    'theories: ' + (p.theory_ids || []).join(', '),
    'uncertainty: ' + fmt(p.uncertainty), 'thickness: ' + fmt(p.thickness),
    'graph distance: ' + fmt(p.proof_distance), p.statement || ''].join(' · ');
}}
function renderMetrics() {{
  const m = DATA.metrics; const rows = [
    ['explanatory volume', m.explanatory_volume], ['surface area', m.surface_area], ['roundness', m.roundness], ['closure ratio', m.closure_ratio], ['uncertainty thickness', m.uncertainty_thickness], ['gaps / seams / holes', `${{m.gap_count}} / ${{m.seam_count}} / ${{m.hole_count}}`]
  ];
  const container = document.getElementById('metrics'); container.replaceChildren();
  for (const r of rows) {{
    const row = document.createElement('div'); row.className = 'metric';
    const label = document.createElement('b'); label.textContent = r[0];
    const value = document.createElement('span'); value.textContent = fmt(r[1]);
    row.append(label, value); container.append(row);
  }}
}}
function renderLedger() {{
  const boundary = points.filter(p=>activeAt(p) && (p.layer==='BOUNDARY'||p.layer==='EXTERIOR'||p.status==='GAP'||p.status==='BLOCKED')).sort((a,b)=>(b.thickness-a.thickness));
  const table = document.getElementById('ledger'); table.replaceChildren();
  const head = table.createTHead().insertRow();
  for (const name of ['point','domain','theories','authored status','layer','graph distance','uncertainty','thickness','statement']) {{
    const cell = document.createElement('th'); cell.textContent = name; head.append(cell);
  }}
  const body = table.createTBody();
  for (const p of boundary) {{
    const row = body.insertRow(); row.tabIndex = 0;
    for (const value of [p.id + ' — ' + p.label,p.domain,(p.theory_ids||[]).join(', '),p.status,p.layer,fmt(p.proof_distance),fmt(p.uncertainty),fmt(p.thickness),p.statement||'']) {{
      row.insertCell().textContent = value;
    }}
    row.addEventListener('focus', () => {{ selected = p; showInfo(p); drawGlobe(); }});
  }}
}}
function setupTheories() {{
  const theoryIds = [...new Set(points.flatMap(p => p.theory_ids || []))].sort();
  for (const theoryId of theoryIds) {{
    const option = document.createElement('option');
    option.value = theoryId;
    option.textContent = theoryId;
    theoryFilter.appendChild(option);
  }}
  if (!theoryIds.length) theoryFilter.parentElement.style.display = 'none';
  theoryFilter.addEventListener('change', () => {{ selected=null; showInfo(null); renderLedger(); drawGlobe(); }});
}}
function setupEpochs() {{
  if (!epochs.length) {{ document.getElementById('epochControl').style.display='none'; return; }}
  epoch.max = String(epochs.length);
  epochLabel.textContent = 'all epochs';
  epoch.addEventListener('input', () => {{
    const i = Number(epoch.value);
    epochLabel.textContent = i===0 ? 'all epochs' : `${{epochs[i-1].label}} · t=${{fmt(epochs[i-1].t)}}`;
    drawGlobe();
  }});
}}
[rot, tilt, boundaryOnly, showFlows, showSeams, showHalos].forEach(el => el.addEventListener('input', drawGlobe));
canvas.addEventListener('mousemove', evt => {{ const p=nearestNode(evt); if (p) {{ selected=p; showInfo(p); }} drawGlobe(); }});
canvas.addEventListener('mouseleave', () => {{ selected=null; showInfo(null); drawGlobe(); }});
renderMetrics(); setupTheories(); renderLedger(); setupEpochs(); drawGlobe();
</script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def render_surface_bundle(
    pm: ProofMap, out_dir: str | Path, *, basename: str = "proof_map", coordinate_mode: str = "auto"
) -> dict[str, Path]:
    """Generate all proof-surface visualization artifacts for a proof map."""

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    layout = build_surface_layout(pm, coordinate_mode=coordinate_mode)
    paths = {
        "surface_svg": out / f"{basename}_surface_atlas.svg",
        "surface_html": out / f"{basename}_surface_explorer.html",
        "surface_points": out / f"{basename}_surface_points.csv",
        "surface_layout": out / f"{basename}_surface_layout.json",
    }
    render_surface_atlas_svg(pm, paths["surface_svg"], coordinate_mode=coordinate_mode)
    render_surface_explorer_html(pm, paths["surface_html"], coordinate_mode=coordinate_mode)
    write_surface_points_csv(layout, paths["surface_points"])
    write_surface_layout_json(layout, paths["surface_layout"])
    return paths
