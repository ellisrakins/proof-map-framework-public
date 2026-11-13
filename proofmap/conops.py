"""End-to-end CONOPS validation workflow for a minimal proof map."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .examples import build_minimal_conops_map
from .lean_check import check_lean_file, resolve_lean_executable
from .lean_export import write_lean_skeleton
from .metrics import analyze, identify_defects
from .report import write_full_report
from .surface_visualize import render_surface_bundle
from .visualize import render_radial_svg

EXPECTED_GAP_ID = "boundary.drag_residual"


@dataclass(frozen=True)
class ConopsValidationResult:
    ok: bool
    summary_path: Path
    out_dir: Path
    metrics: dict[str, Any]
    defect_ids: list[str]
    artifact_paths: dict[str, Path]
    lean_checked: bool
    lean_ok: bool | None
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["summary_path"] = str(self.summary_path)
        data["out_dir"] = str(self.out_dir)
        data["artifact_paths"] = {key: str(path) for key, path in self.artifact_paths.items()}
        return data


def run_conops_validation(
    out_dir: str | Path,
    *,
    lean_executable: str | None = None,
    require_lean: bool = False,
    timeout: float = 120.0,
) -> ConopsValidationResult:
    """Generate and validate the minimal CONOPS proof-map artifact bundle."""

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pm = build_minimal_conops_map()
    basename = "minimal_conops"

    map_path = out / f"{basename}.json"
    pm.to_json(map_path)
    report_paths = write_full_report(pm, out, basename=basename)
    sphere_path = out / f"{basename}_sphere.svg"
    render_radial_svg(pm, sphere_path)
    lean_path = out / f"{basename}_LeanSketch.lean"
    write_lean_skeleton(pm, lean_path)
    surface_paths = render_surface_bundle(pm, out, basename=basename)

    artifact_paths = {
        "map": map_path,
        "sphere": sphere_path,
        "lean": lean_path,
        **report_paths,
        **surface_paths,
    }

    metrics = analyze(pm).to_dict()
    defects = identify_defects(pm)
    defect_ids = [defect.id for defect in defects]

    notes: list[str] = []
    ok = True
    if metrics["node_count"] != 5:
        ok = False
        notes.append(f"expected 5 nodes, saw {metrics['node_count']}")
    if metrics["gap_count"] != 1:
        ok = False
        notes.append(f"expected 1 gap, saw {metrics['gap_count']}")
    if EXPECTED_GAP_ID not in defect_ids:
        ok = False
        notes.append(f"expected defect {EXPECTED_GAP_ID!r} was not detected")

    missing_or_empty = [
        key for key, path in artifact_paths.items() if not path.exists() or path.stat().st_size == 0
    ]
    if missing_or_empty:
        ok = False
        notes.append("missing or empty artifacts: " + ", ".join(sorted(missing_or_empty)))

    lean_checked = False
    lean_ok: bool | None = None
    lean = resolve_lean_executable(lean_executable)
    if lean is not None:
        lean_checked = True
        lean_result = check_lean_file(lean_path, lean_executable=lean, timeout=timeout)
        lean_ok = lean_result.ok
        if not lean_result.ok:
            ok = False
            notes.append("Lean scaffold did not compile")
            if lean_result.stderr:
                notes.append(lean_result.stderr.strip())
    elif require_lean:
        ok = False
        lean_ok = False
        notes.append("Lean executable not found")
    else:
        notes.append("Lean executable not found; skipped Lean scaffold check")

    if ok and not notes:
        notes.append("CONOPS validation passed")

    summary_path = out / f"{basename}_validation_summary.json"
    result = ConopsValidationResult(
        ok=ok,
        summary_path=summary_path,
        out_dir=out,
        metrics=metrics,
        defect_ids=defect_ids,
        artifact_paths=artifact_paths,
        lean_checked=lean_checked,
        lean_ok=lean_ok,
        notes=notes,
    )
    summary_path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
