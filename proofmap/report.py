"""Markdown/CSV report generation for proof-map boundary analysis."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .integrity import csv_cell, markdown_text
from .metrics import analyze, identify_defects, metrics_over_epochs
from .model import ProofMap
from .optimizer import rank_closure_candidates


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def render_markdown_report(pm: ProofMap, *, include_dynamic: bool = True) -> str:
    metrics = analyze(pm)
    defects = identify_defects(pm)
    distances = pm.shortest_distances_from_core()

    lines: list[str] = []
    lines.append(f"# {markdown_text(pm.title)} - Proof Boundary Analysis")
    lines.append("")
    if pm.description:
        lines.append(markdown_text(pm.description))
        lines.append("")

    lines.append("## Geometry metrics")
    lines.append("")
    lines.append("| Metric | Value | Interpretation |")
    lines.append("|---|---:|---|")
    interpretations = {
        "explanatory_volume": "Weighted amount of nontrivial content currently enclosed by the proof map.",
        "surface_area": "Boundary complexity: open interfaces, assumptions, empirical patches, and uncertainty.",
        "roundness": "Uniform derivability from the core; higher means less jagged proof distance across the boundary.",
        "density": "Explanatory volume per unit proof/derivation cost.",
        "closure_ratio": "Weighted share accepted under deductive-strict-v1; authored labels are not evidence.",
        "uncertainty_thickness": "Average thickness of probabilistic, empirical, approximate, or unresolved boundary regions.",
        "hole_count": "Boundary/exterior nodes not derivably connected to the core or still gaplike.",
        "seam_count": "Cross-domain or approximation interfaces with tension/uncertainty.",
        "gap_count": "Nodes explicitly marked as gap, blocked, or external.",
        "unexplained_parameter_count": "Empirical/assumed constants that remain boundary defects.",
    }
    for key in [
        "explanatory_volume",
        "surface_area",
        "roundness",
        "density",
        "closure_ratio",
        "uncertainty_thickness",
        "hole_count",
        "seam_count",
        "gap_count",
        "unexplained_parameter_count",
    ]:
        lines.append(f"| `{key}` | {_fmt(getattr(metrics, key))} | {interpretations[key]} |")

    lines.append("")
    lines.append("## Diagnosis")
    lines.append("")
    for note in metrics.notes:
        lines.append(f"- {markdown_text(note)}")
    lines.append("")

    lines.append("## Highest-severity proof-boundary defects")
    lines.append("")
    if defects:
        lines.append(
            "| Rank | Defect | Type | Severity | Closure path | Affected downstream nodes |"
        )
        lines.append("|---:|---|---|---:|---|---|")
        for i, defect in enumerate(defects[:12], start=1):
            affected = ", ".join(defect.affected_nodes[:6])
            if len(defect.affected_nodes) > 6:
                affected += f", +{len(defect.affected_nodes) - 6} more"
            lines.append(
                f"| {i} | {markdown_text(defect.id)} | {markdown_text(defect.defect_type)} | {_fmt(defect.severity)} | "
                f"{markdown_text(defect.suggested_closure_path)} | {markdown_text(affected or '-')} |"
            )
    else:
        lines.append("No proof-boundary defects detected by the current heuristic pass.")
    lines.append("")

    lines.append("## Evidence-action priorities")
    lines.append("")
    candidates = rank_closure_candidates(pm, limit=8)
    if candidates:
        lines.append(
            "The conditional-closure-planning.v1 heuristic ranks declared evidence blockers. Requests do not execute checks, reduce uncertainty, or change accepted closure. Expected empirical gain and effort remain unknown. Exact subjects, prerequisites and conditional witnesses are available through proofmap.paper_actions; legacy geometric deltas remain zero."
        )
        lines.append("")
        lines.append(
            "| Rank | Candidate | Current → proposed | Δ volume | Δ surface | Δ roundness | Δ closure | Δ thickness | Score | Rationale |"
        )
        lines.append("|---:|---|---|---:|---:|---:|---:|---:|---:|---|")
        for i, c in enumerate(candidates, start=1):
            lines.append(
                f"| {i} | {markdown_text(c.node_id)} | {c.current_status} → {c.proposed_status} | "
                f"{_fmt(c.delta_volume)} | {_fmt(c.delta_surface_area)} | {_fmt(c.delta_roundness)} | "
                f"{_fmt(c.delta_closure_ratio)} | {_fmt(c.delta_thickness)} | {_fmt(c.score)} | {markdown_text(c.rationale)} |"
            )
    else:
        lines.append("No closure candidates found.")
    lines.append("")

    lines.append("## Boundary ledger")
    lines.append("")
    lines.append(
        "| Node | Layer | Status | Domain | Theories | Proof distance | Uncertainty | Statement |"
    )
    lines.append("|---|---|---|---|---|---:|---:|---|")
    for node_id in pm.boundary_node_ids():
        node = pm.nodes[node_id]
        dist = distances.get(node_id, "∞")
        statement = node.statement or node.notes or node.label
        if len(statement) > 110:
            statement = statement[:107] + "…"
        theories = ", ".join(node.theory_ids) or "—"
        lines.append(
            f"| {markdown_text(node.id)} | {node.layer.value} | {node.status.value} | {markdown_text(node.domain)} | "
            f"{markdown_text(theories)} | {dist} | {_fmt(node.uncertainty)} | {markdown_text(statement)} |"
        )
    lines.append("")

    lines.append("## Proof map nodes")
    lines.append("")
    lines.append(
        "| Node | Kind | Status | Layer | Domain | Theories | Weight | Cost | Sources | Notes |"
    )
    lines.append("|---|---|---|---|---|---|---:|---:|---|---|")
    for node in sorted(pm.nodes.values(), key=lambda n: (n.layer.value, n.domain, n.id)):
        notes = node.notes or node.statement or "-"
        if len(notes) > 95:
            notes = notes[:92] + "…"
        sources = ", ".join(getattr(node, "source_ids", [])[:3]) or "—"
        lines.append(
            f"| {markdown_text(node.id)} | {node.kind.value} | {node.status.value} | {node.layer.value} | "
            f"{markdown_text(node.domain)} | {markdown_text(', '.join(node.theory_ids) or '-')} | "
            f"{_fmt(node.explanatory_weight)} | {_fmt(node.proof_cost)} | {markdown_text(sources)} | {markdown_text(notes)} |"
        )
    lines.append("")

    if include_dynamic and pm.epochs:
        rows = metrics_over_epochs(pm)
        lines.append("## Dynamic boundary by epoch")
        lines.append("")
        lines.append(
            "| Epoch | t | Volume | Surface area | Roundness | Closure | Thickness | Gaps | Seams |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for row in rows:
            lines.append(
                f"| {markdown_text(row['epoch_label'])} | {_fmt(row['t'])} | {_fmt(row['explanatory_volume'])} | "
                f"{_fmt(row['surface_area'])} | {_fmt(row['roundness'])} | {_fmt(row['closure_ratio'])} | "
                f"{_fmt(row['uncertainty_thickness'])} | {row['gap_count']} | {row['seam_count']} |"
            )
        lines.append("")

    lines.append("## How to read this map")
    lines.append("")
    lines.append("- **Volume** is explanatory content enclosed by the current formal structure.")
    lines.append(
        "- **Surface area** is boundary complexity: external assumptions, empirical attachments, patches, and open interfaces."
    )
    lines.append(
        "- **Roundness** is high when boundary phenomena have similar derivational distance from the compact core."
    )
    lines.append(
        "- **Thickness** is classified uncertainty: probabilistic law, approximation, measurement error, computational limits, or unresolved proof debt."
    )
    lines.append(
        "- **Seams** are force/domain/theory interfaces where local charts must be glued by bridge principles."
    )
    lines.append("")
    return "\n".join(lines)


def write_metrics_json(pm: ProofMap, path: str | Path) -> None:
    data = analyze(pm).to_dict()
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_defects_csv(pm: ProofMap, path: str | Path) -> None:
    defects = identify_defects(pm)
    fieldnames = [
        "id",
        "defect_type",
        "severity",
        "description",
        "affected_nodes",
        "suggested_closure_path",
    ]
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for defect in defects:
            row = defect.to_dict()
            row["affected_nodes"] = "; ".join(row["affected_nodes"])
            writer.writerow({key: csv_cell(value) for key, value in row.items()})


def write_boundary_csv(pm: ProofMap, path: str | Path) -> None:
    distances = pm.shortest_distances_from_core()
    fieldnames = [
        "id",
        "label",
        "kind",
        "status",
        "layer",
        "domain",
        "theory_ids",
        "formal_systems",
        "regime_dimensions",
        "proof_distance",
        "uncertainty",
        "boundary_weight",
        "source_ids",
        "evidence_class",
        "last_verified",
        "uncertainty_kind",
        "statement",
        "notes",
    ]
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for node_id in pm.boundary_node_ids():
            node = pm.nodes[node_id]
            row = {
                "id": node.id,
                "label": node.label,
                "kind": node.kind.value,
                "status": node.status.value,
                "layer": node.layer.value,
                "domain": node.domain,
                "theory_ids": "; ".join(node.theory_ids),
                "formal_systems": "; ".join(node.formal_systems),
                "regime_dimensions": json.dumps(node.regime_dimensions, sort_keys=True),
                "proof_distance": distances.get(node_id, "inf"),
                "uncertainty": node.uncertainty,
                "boundary_weight": node.boundary_weight,
                "source_ids": "; ".join(getattr(node, "source_ids", [])),
                "evidence_class": getattr(node, "evidence_class", ""),
                "last_verified": getattr(node, "last_verified", ""),
                "uncertainty_kind": getattr(node, "uncertainty_kind", ""),
                "statement": node.statement,
                "notes": node.notes,
            }
            writer.writerow({key: csv_cell(value) for key, value in row.items()})


def write_full_report(
    pm: ProofMap, out_dir: str | Path, basename: str = "proof_map"
) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "report": out / f"{basename}_report.md",
        "metrics": out / f"{basename}_metrics.json",
        "defects": out / f"{basename}_defects.csv",
        "boundary": out / f"{basename}_boundary_ledger.csv",
        "map_json": out / f"{basename}.json",
    }
    paths["report"].write_text(render_markdown_report(pm), encoding="utf-8")
    write_metrics_json(pm, paths["metrics"])
    write_defects_csv(pm, paths["defects"])
    write_boundary_csv(pm, paths["boundary"])
    pm.to_json(paths["map_json"])
    return paths
