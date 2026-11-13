"""Validation workflow for source-backed current-physics maps."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .current_physics import (
    build_current_physics_backbone_map,
    build_current_physics_source_registry,
)
from .lean_check import check_lean_file, resolve_lean_executable
from .lean_export import write_lean_skeleton
from .metrics import analyze, identify_defects
from .physics_catalog import build_physics_theory_catalog, build_physics_theory_source_registry
from .report import write_full_report
from .sources import validate_source_coverage
from .surface_visualize import render_surface_bundle
from .theories import (
    validate_theory_bindings,
    validate_theory_catalog,
    write_theory_catalog_report,
)
from .visualize import render_radial_svg

EXPECTED_BACKBONE_GAPS = {
    "gap.quantum_gravity",
    "gap.dark_matter_identity",
    "gap.dark_energy_microphysics",
    "gap.neutrino_mass_mechanism",
    "gap.baryon_asymmetry",
    "gap.confinement_mass_gap",
}


@dataclass(frozen=True)
class CurrentPhysicsValidationResult:
    ok: bool
    summary_path: Path
    out_dir: Path
    source_registry_path: Path
    theory_catalog_path: Path
    theory_source_registry_path: Path
    metrics: dict[str, Any]
    defect_ids: list[str]
    artifact_paths: dict[str, Path]
    source_coverage_errors: list[str]
    theory_catalog_errors: list[str]
    theory_binding_errors: list[str]
    theory_binding_warnings: list[str]
    lean_checked: bool
    lean_ok: bool | None
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["summary_path"] = str(self.summary_path)
        data["out_dir"] = str(self.out_dir)
        data["source_registry_path"] = str(self.source_registry_path)
        data["theory_catalog_path"] = str(self.theory_catalog_path)
        data["theory_source_registry_path"] = str(self.theory_source_registry_path)
        data["artifact_paths"] = {key: str(path) for key, path in self.artifact_paths.items()}
        return data


def run_current_physics_backbone_validation(
    out_dir: str | Path,
    *,
    lean_executable: str | None = None,
    require_lean: bool = False,
    timeout: float = 120.0,
) -> CurrentPhysicsValidationResult:
    """Generate and validate the source-backed current-physics backbone map."""

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pm = build_current_physics_backbone_map()
    registry = build_current_physics_source_registry()
    theory_catalog = build_physics_theory_catalog()
    theory_sources = build_physics_theory_source_registry()
    basename = "current_physics_backbone"

    source_registry_path = out / "current_physics_sources.json"
    registry.to_json(source_registry_path)
    theory_catalog_path = out / "physics_theory_catalog.json"
    theory_catalog.to_json(theory_catalog_path)
    theory_source_registry_path = out / "physics_theory_sources.json"
    theory_sources.to_json(theory_source_registry_path)
    theory_report_path = out / "physics_theory_catalog_report.md"

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
        "source_registry": source_registry_path,
        "theory_catalog": theory_catalog_path,
        "theory_source_registry": theory_source_registry_path,
        "theory_report": theory_report_path,
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

    missing_gaps = sorted(EXPECTED_BACKBONE_GAPS.difference(defect_ids))
    if missing_gaps:
        ok = False
        notes.append("Missing expected backbone gaps: " + ", ".join(missing_gaps))

    if metrics["node_count"] < 40:
        ok = False
        notes.append(f"expected at least 40 nodes, saw {metrics['node_count']}")
    if metrics["gap_count"] < len(EXPECTED_BACKBONE_GAPS):
        ok = False
        notes.append(
            f"expected at least {len(EXPECTED_BACKBONE_GAPS)} gaps, saw {metrics['gap_count']}"
        )
    if metrics["seam_count"] < 8:
        ok = False
        notes.append(f"expected at least 8 seams, saw {metrics['seam_count']}")

    source_coverage_errors = validate_source_coverage(pm, registry)
    if source_coverage_errors:
        ok = False
        notes.append(f"source coverage errors: {len(source_coverage_errors)}")

    theory_catalog_validation = validate_theory_catalog(
        theory_catalog,
        theory_sources,
        require_sources=True,
    )
    theory_catalog_errors = list(theory_catalog_validation.errors)
    if theory_catalog_errors:
        ok = False
        notes.append(f"theory catalog errors: {len(theory_catalog_errors)}")
    write_theory_catalog_report(
        theory_catalog,
        theory_report_path,
        theory_catalog_validation,
    )

    theory_binding_validation = validate_theory_bindings(pm, theory_catalog, require_any=True)
    theory_binding_errors = list(theory_binding_validation.errors)
    theory_binding_warnings = list(theory_binding_validation.warnings)
    if theory_binding_errors:
        ok = False
        notes.append(f"theory binding errors: {len(theory_binding_errors)}")

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
        notes.append("Current-physics backbone validation passed")

    summary_path = out / f"{basename}_validation_summary.json"
    result = CurrentPhysicsValidationResult(
        ok=ok,
        summary_path=summary_path,
        out_dir=out,
        source_registry_path=source_registry_path,
        theory_catalog_path=theory_catalog_path,
        theory_source_registry_path=theory_source_registry_path,
        metrics=metrics,
        defect_ids=defect_ids,
        artifact_paths=artifact_paths,
        source_coverage_errors=source_coverage_errors,
        theory_catalog_errors=theory_catalog_errors,
        theory_binding_errors=theory_binding_errors,
        theory_binding_warnings=theory_binding_warnings,
        lean_checked=lean_checked,
        lean_ok=lean_ok,
        notes=notes,
    )
    summary_path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
