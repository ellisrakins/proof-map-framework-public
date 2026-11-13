"""SVG rendering utilities for proof maps."""

from __future__ import annotations

from math import cos, pi, sin
from pathlib import Path
from typing import Any

from .metrics import analyze, identify_defects, identify_seam_edges
from .model import Layer, NodeStatus, ProofMap

STATUS_COLORS = {
    NodeStatus.CORE: "#FFD166",
    NodeStatus.PROVED: "#63D471",
    NodeStatus.DERIVED: "#7AD7F0",
    NodeStatus.COMPUTED: "#9BE7C6",
    NodeStatus.EMPIRICAL: "#B9D6FF",
    NodeStatus.PROBABILISTIC: "#C6B8FF",
    NodeStatus.ASSUMPTION: "#FFE8A3",
    NodeStatus.APPROXIMATION: "#FFD6A5",
    NodeStatus.GAP: "#FF7B72",
    NodeStatus.BLOCKED: "#D1495B",
    NodeStatus.EXTERNAL: "#D7D7D7",
    NodeStatus.INDEPENDENT: "#D8C3A5",
}

LAYER_RADII = {
    Layer.CORE: 55,
    Layer.INTERIOR: 170,
    Layer.BOUNDARY: 275,
    Layer.EXTERIOR: 355,
}


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _wrap_text(text: str, max_chars: int = 24) -> list[str]:
    words = text.replace("/", "/ ").split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= max_chars:
            current = f"{current} {word}".strip()
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:3]


def radial_layout(
    pm: ProofMap, width: int = 1400, height: int = 1000
) -> dict[str, tuple[float, float]]:
    cx, cy = width * 0.42, height * 0.50
    domains = sorted({n.domain for n in pm.nodes.values()})
    domain_index = {domain: i for i, domain in enumerate(domains)}
    by_domain_layer: dict[tuple[str, Layer], list[str]] = {}
    for node in pm.nodes.values():
        by_domain_layer.setdefault((node.domain, node.layer), []).append(node.id)
    for ids in by_domain_layer.values():
        ids.sort()

    positions: dict[str, tuple[float, float]] = {}
    n_domains = max(1, len(domains))
    for node in pm.nodes.values():
        base = 2 * pi * (domain_index[node.domain] / n_domains) - pi / 2
        ids = by_domain_layer[(node.domain, node.layer)]
        idx = ids.index(node.id)
        spread = min(pi / max(3, n_domains), 0.55)
        offset = 0.0 if len(ids) == 1 else spread * ((idx / (len(ids) - 1)) - 0.5)
        angle = base + offset
        radius = LAYER_RADII[node.layer]
        if node.layer == Layer.CORE:
            radius = 25 + 12 * idx
        x = cx + radius * cos(angle)
        y = cy + radius * sin(angle)
        positions[node.id] = (x, y)
    return positions


def render_radial_svg(
    pm: ProofMap, path: str | Path, *, width: int = 1400, height: int = 1000
) -> None:
    metrics = analyze(pm)
    defects = identify_defects(pm)
    seam_keys = {f"{edge.source}->{edge.target}" for edge in identify_seam_edges(pm)}
    positions = radial_layout(pm, width, height)
    cx, cy = width * 0.42, height * 0.50
    path = Path(path)

    lines: list[str] = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
    )
    lines.append("<defs>")
    lines.append(
        "  <radialGradient id='coreGlow' cx='50%' cy='50%' r='50%'><stop offset='0%' stop-color='#fff4b8'/><stop offset='60%' stop-color='#ffd166'/><stop offset='100%' stop-color='#f4a261'/></radialGradient>"
    )
    lines.append(
        "  <filter id='softShadow'><feDropShadow dx='0' dy='3' stdDeviation='5' flood-opacity='0.18'/></filter>"
    )
    lines.append("</defs>")
    lines.append("<rect width='100%' height='100%' fill='#fbfdff'/>")
    lines.append(
        f"<text x='{width / 2}' y='58' text-anchor='middle' font-size='34' font-family='Helvetica, Arial' font-weight='700' fill='#0b1f4d'>{_escape(pm.title)}</text>"
    )
    if pm.description:
        desc = _wrap_text(pm.description, max_chars=95)
        for i, line in enumerate(desc):
            lines.append(
                f"<text x='{width / 2}' y='{88 + i * 18}' text-anchor='middle' font-size='14' font-family='Helvetica, Arial' fill='#3c4a66'>{_escape(line)}</text>"
            )

    # Layer rings and labels.
    rings = [
        (Layer.EXTERIOR, "Unexplained / speculative exterior", "#e8eef8", "#8ca6d9"),
        (Layer.BOUNDARY, "Proof boundary / phenomena", "#edf5ff", "#3867c8"),
        (Layer.INTERIOR, "Explanatory volume", "#eaf9f4", "#00a38a"),
        (Layer.CORE, "Core axioms / primitive laws", "#fff4cc", "#f4a100"),
    ]
    for layer, label, fill, stroke in rings:
        radius = LAYER_RADII[layer]
        opacity = 0.42 if layer != Layer.CORE else 0.85
        dash = " stroke-dasharray='8 6'" if layer == Layer.EXTERIOR else ""
        lines.append(
            f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='{radius}' fill='{fill}' fill-opacity='{opacity}' stroke='{stroke}' stroke-width='2'{dash}/>"
        )
        if layer != Layer.CORE:
            lines.append(
                f"<text x='{cx + radius + 16:.1f}' y='{cy - radius + 26:.1f}' font-size='15' font-family='Helvetica, Arial' font-weight='700' fill='{stroke}'>{_escape(label)}</text>"
            )
    lines.append(
        f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='46' fill='url(#coreGlow)' stroke='#a66a00' stroke-width='2' filter='url(#softShadow)'/>"
    )

    # Edges first.
    for edge in pm.edges:
        x1, y1 = positions[edge.source]
        x2, y2 = positions[edge.target]
        key = f"{edge.source}->{edge.target}"
        src = pm.nodes[edge.source]
        tgt = pm.nodes[edge.target]
        if key in seam_keys:
            stroke = "#c0392b"
            sw = 2.4
            dash = " stroke-dasharray='6 4'"
        elif src.domain != tgt.domain:
            stroke = "#7f8c8d"
            sw = 1.6
            dash = " stroke-dasharray='4 4'"
        else:
            stroke = "#8aa3bd"
            sw = 1.1
            dash = ""
        opacity = 0.28 + 0.60 * max(0.0, 1.0 - edge.uncertainty)
        lines.append(
            f"<line x1='{x1:.1f}' y1='{y1:.1f}' x2='{x2:.1f}' y2='{y2:.1f}' stroke='{stroke}' stroke-width='{sw}' opacity='{opacity:.2f}'{dash}/>"
        )

    # Nodes.
    for node_id, node in pm.nodes.items():
        x, y = positions[node_id]
        fill = STATUS_COLORS[node.status]
        r = 11 if node.layer != Layer.CORE else 15
        if node.status in {NodeStatus.GAP, NodeStatus.BLOCKED, NodeStatus.EXTERNAL}:
            stroke = "#831c1c"
            sw = 2.5
        elif node.status in {NodeStatus.ASSUMPTION, NodeStatus.APPROXIMATION}:
            stroke = "#b36b00"
            sw = 2
        else:
            stroke = "#24415f"
            sw = 1.2
        lines.append(
            f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r}' fill='{fill}' stroke='{stroke}' stroke-width='{sw}' filter='url(#softShadow)'/>"
        )
        label_lines = _wrap_text(node.label, max_chars=19)
        anchor = "start" if x >= cx else "end"
        text_x = x + (16 if x >= cx else -16)
        text_y = y - 4 * (len(label_lines) - 1)
        for i, label_line in enumerate(label_lines):
            lines.append(
                f"<text x='{text_x:.1f}' y='{text_y + i * 13:.1f}' text-anchor='{anchor}' font-size='11' font-family='Helvetica, Arial' fill='#17223b'>{_escape(label_line)}</text>"
            )

    # Right metrics panel.
    panel_x = width - 390
    panel_y = 135
    panel_w = 340
    panel_h = 390
    lines.append(
        f"<rect x='{panel_x}' y='{panel_y}' width='{panel_w}' height='{panel_h}' rx='18' fill='#ffffff' stroke='#194b96' stroke-width='2' filter='url(#softShadow)'/>"
    )
    lines.append(
        f"<rect x='{panel_x}' y='{panel_y}' width='{panel_w}' height='56' rx='18' fill='#123b79'/>"
    )
    lines.append(
        f"<text x='{panel_x + panel_w / 2}' y='{panel_y + 36}' text-anchor='middle' font-size='20' font-family='Helvetica, Arial' font-weight='700' fill='white'>Boundary Metrics</text>"
    )
    metric_rows = [
        ("Explanatory volume", metrics.explanatory_volume),
        ("Surface area", metrics.surface_area),
        ("Roundness", metrics.roundness),
        ("Density", metrics.density),
        ("Closure ratio", metrics.closure_ratio),
        ("Uncertainty thickness", metrics.uncertainty_thickness),
        (
            "Gaps / seams / holes",
            f"{metrics.gap_count} / {metrics.seam_count} / {metrics.hole_count}",
        ),
    ]
    for i, (label, value) in enumerate(metric_rows):
        y = panel_y + 86 + i * 39
        lines.append(
            f"<text x='{panel_x + 24}' y='{y}' font-size='14' font-family='Helvetica, Arial' font-weight='700' fill='#0b1f4d'>{_escape(label)}</text>"
        )
        lines.append(
            f"<text x='{panel_x + panel_w - 24}' y='{y}' text-anchor='end' font-size='14' font-family='Helvetica, Arial' fill='#1f5eb8'>{_escape(str(value))}</text>"
        )
        lines.append(
            f"<line x1='{panel_x + 20}' y1='{y + 12}' x2='{panel_x + panel_w - 20}' y2='{y + 12}' stroke='#e1e8f5'/>"
        )

    # Defect ledger panel.
    defect_x = width - 390
    defect_y = 555
    defect_h = 365
    lines.append(
        f"<rect x='{defect_x}' y='{defect_y}' width='{panel_w}' height='{defect_h}' rx='18' fill='#ffffff' stroke='#9b1c31' stroke-width='2' filter='url(#softShadow)'/>"
    )
    lines.append(
        f"<text x='{defect_x + 22}' y='{defect_y + 36}' font-size='19' font-family='Helvetica, Arial' font-weight='700' fill='#9b1c31'>Highest-severity defects</text>"
    )
    if defects:
        for i, defect in enumerate(defects[:7]):
            y = defect_y + 68 + i * 39
            label = f"{defect.defect_type}: {defect.id}"
            label = label[:44] + "…" if len(label) > 45 else label
            lines.append(
                f"<text x='{defect_x + 22}' y='{y}' font-size='12' font-family='Helvetica, Arial' font-weight='700' fill='#17223b'>{_escape(label)}</text>"
            )
            lines.append(
                f"<text x='{defect_x + panel_w - 24}' y='{y}' text-anchor='end' font-size='12' font-family='Helvetica, Arial' fill='#9b1c31'>sev {defect.severity:g}</text>"
            )
            lines.append(
                f"<text x='{defect_x + 22}' y='{y + 15}' font-size='10' font-family='Helvetica, Arial' fill='#53627a'>{_escape(defect.suggested_closure_path[:55])}</text>"
            )
    else:
        lines.append(
            f"<text x='{defect_x + 22}' y='{defect_y + 72}' font-size='13' font-family='Helvetica, Arial' fill='#53627a'>No defects detected.</text>"
        )

    # Legend.
    legend_x = 60
    legend_y = height - 145
    lines.append(
        f"<rect x='{legend_x}' y='{legend_y}' width='720' height='94' rx='14' fill='#ffffff' stroke='#bdcbe6' filter='url(#softShadow)'/>"
    )
    lines.append(
        f"<text x='{legend_x + 18}' y='{legend_y + 30}' font-size='16' font-family='Helvetica, Arial' font-weight='700' fill='#0b1f4d'>Interpretation</text>"
    )
    interp = [
        "Time/entropy flow is tangent to boundary phenomena.",
        "Proof/explanation flow is radial from core to surface.",
        "Seams mark cross-domain or approximation interfaces.",
        "Holes mark unreachable or unresolved regions.",
    ]
    for i, text in enumerate(interp):
        lines.append(
            f"<text x='{legend_x + 18}' y='{legend_y + 54 + i * 16}' font-size='12' font-family='Helvetica, Arial' fill='#2e3d55'>{_escape(text)}</text>"
        )

    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def render_dynamic_csv(rows: list[dict[str, Any]], path: str | Path) -> None:
    import csv

    path = Path(path)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        from .integrity import csv_cell

        writer.writerows({key: csv_cell(value) for key, value in row.items()} for row in rows)
