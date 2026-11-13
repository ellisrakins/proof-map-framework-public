"""Emit a Lean-oriented sketch from a proof map.

The output is a scaffold for proof engineering, not a guaranteed compiling Lean file.
It turns proof-map nodes into named obligations and marks gaplike nodes explicitly.
"""

from __future__ import annotations

import re
from pathlib import Path

from .model import NodeKind, NodeStatus, ProofMap


def lean_ident(node_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", node_id)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "n_" + cleaned
    return cleaned


def render_lean_skeleton(pm: ProofMap, namespace: str = "ProofMapBoundary") -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", namespace):
        raise ValueError("Invalid Lean namespace")

    def comment(text: str) -> str:
        return text.replace("/-", "/ -").replace("-/", "- /")

    lines: list[str] = []
    lines.append("/-")
    lines.append(f"Generated scaffold for: {comment(pm.title)}")
    lines.append("")
    lines.append("This file is a proof-engineering sketch. It is intentionally abstract:")
    lines.append(
        "replace Prop placeholders with actual definitions, then eliminate axioms/sorries."
    )
    lines.append("-/")
    lines.append("")
    lines.append(f"namespace {namespace}")
    lines.append("")
    lines.append("-- Abstract placeholder domains. Refine these into actual formal definitions.")
    lines.append("axiom Claim : Type")
    lines.append("axiom proves : Claim → Claim → Prop")
    lines.append("axiom bridges : Claim → Claim → Prop")
    lines.append("axiom approximates : Claim → Claim → Prop")
    lines.append("")

    for node in sorted(pm.nodes.values(), key=lambda n: n.id):
        ident = lean_ident(node.id)
        lines.append(f"/-- {comment(node.label)}")
        if node.statement:
            lines.append(f"    Statement: {comment(node.statement)}")
        if node.notes:
            lines.append(f"    Notes: {comment(node.notes)}")
        lines.append(
            f"    Kind/status/layer: {node.kind.value} / {node.status.value} / {node.layer.value} -/"
        )
        lines.append(f"axiom {ident} : Claim")
        if (
            node.status in {NodeStatus.GAP, NodeStatus.BLOCKED, NodeStatus.EXTERNAL}
            or node.kind == NodeKind.GAP
        ):
            lines.append(
                f"-- GAP: replace `{ident}` with a theorem or mark as an explicit external assumption."
            )
        elif node.status in {
            NodeStatus.ASSUMPTION,
            NodeStatus.APPROXIMATION,
            NodeStatus.EMPIRICAL,
            NodeStatus.PROBABILISTIC,
        }:
            lines.append(
                f"-- BOUNDARY: classify `{ident}` as theorem, empirical bridge, probabilistic law, or approximation theorem."
            )
        lines.append("")

    for i, edge in enumerate(pm.edges, start=1):
        src = lean_ident(edge.source)
        tgt = lean_ident(edge.target)
        rel = {
            "BRIDGES": "bridges",
            "INTERFACE": "bridges",
            "LIMITS_TO": "bridges",
            "APPROXIMATES": "approximates",
            "EMPIRICALLY_CONSTRAINS": "bridges",
        }.get(edge.kind.value, "proves")
        name = f"edge_{i}_{src}_to_{tgt}"
        lines.append(f"/-- {edge.kind.value} / {edge.status.value}. {comment(edge.notes)} -/")
        if edge.status.value in {"GAP", "BLOCKED", "ASSUMED", "APPROXIMATE", "EMPIRICAL"}:
            lines.append(f"axiom {name} : {rel} {src} {tgt} -- boundary edge")
        else:
            lines.append(f"axiom {name} : {rel} {src} {tgt}")
        lines.append("")

    lines.append(f"end {namespace}")
    lines.append("")
    return "\n".join(lines)


def write_lean_skeleton(
    pm: ProofMap, path: str | Path, namespace: str = "ProofMapBoundary"
) -> None:
    Path(path).write_text(render_lean_skeleton(pm, namespace=namespace), encoding="utf-8")
