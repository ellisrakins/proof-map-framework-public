"""Command-line interface for proof-map boundary analysis."""

from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from pathlib import Path

from .attempts import AttemptOutcome, FormalObligation, ProofAttempt, check_proof_attempt
from .conops import run_conops_validation
from .current_physics import (
    build_current_physics_backbone_map,
    build_current_physics_source_registry,
)
from .current_validation import run_current_physics_backbone_validation
from .examples import (
    build_dynamic_cosmology_map,
    build_minimal_conops_map,
    build_strong_weak_interface_map,
)
from .hypothesis import HypothesisCatalog, rank_hypotheses, write_hypothesis_search
from .lean_check import check_lean_files, resolve_lean_executable
from .lean_export import write_lean_skeleton
from .metrics import analyze, metrics_over_epochs
from .model import ProofMap
from .physics_catalog import build_physics_theory_catalog, build_physics_theory_source_registry
from .report import write_full_report
from .sources import SourceRegistry
from .surface_visualize import render_surface_bundle
from .theories import (
    TheoryCatalog,
    TheoryKind,
    TheoryMaturity,
    build_theory_scaffold,
    validate_theory_bindings,
    validate_theory_catalog,
    write_theory_catalog_report,
)
from .visualize import render_dynamic_csv, render_radial_svg


def _load_example(name: str) -> ProofMap:
    if name == "conops":
        return build_minimal_conops_map()
    if name in {"current_physics", "current_physics_backbone"}:
        return build_current_physics_backbone_map()
    if name == "strong_weak":
        return build_strong_weak_interface_map()
    if name == "cosmology":
        return build_dynamic_cosmology_map()
    raise ValueError(f"Unknown example: {name}")


def cmd_examples(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    maps = {
        "minimal_conops": build_minimal_conops_map(),
        "current_physics_backbone": build_current_physics_backbone_map(),
        "strong_weak_interface": build_strong_weak_interface_map(),
        "dynamic_cosmology": build_dynamic_cosmology_map(),
    }
    for stem, pm in maps.items():
        pm.to_json(out / f"{stem}.json")
    sources_dir = out / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    build_current_physics_source_registry().to_json(sources_dir / "current_physics_sources.json")
    build_physics_theory_source_registry().to_json(sources_dir / "physics_theory_sources.json")
    theories_dir = out / "theories"
    theories_dir.mkdir(parents=True, exist_ok=True)
    build_physics_theory_catalog().to_json(theories_dir / "physics_theory_catalog.json")
    print(f"Wrote {len(maps)} example maps to {out}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    pm = ProofMap.from_json(args.input)
    metrics = analyze(pm)
    print(json.dumps(metrics.to_dict(), indent=2, sort_keys=True))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    pm = ProofMap.from_json(args.input)
    out = Path(args.out)
    basename = args.basename or Path(args.input).stem
    paths = write_full_report(pm, out, basename=basename)
    render_radial_svg(pm, out / f"{basename}_sphere.svg")
    write_lean_skeleton(pm, out / f"{basename}_LeanSketch.lean")
    if pm.epochs:
        render_dynamic_csv(metrics_over_epochs(pm), out / f"{basename}_dynamic_metrics.csv")
    surface_paths = render_surface_bundle(pm, out, basename=basename)
    for key, path in sorted(paths.items()):
        print(f"{key}: {path}")
    print(f"svg: {out / f'{basename}_sphere.svg'}")
    print(f"lean: {out / f'{basename}_LeanSketch.lean'}")
    if pm.epochs:
        print(f"dynamic: {out / f'{basename}_dynamic_metrics.csv'}")
    for key, path in sorted(surface_paths.items()):
        print(f"{key}: {path}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    out = Path(args.out)
    examples_dir = out / "examples"
    reports_dir = out / "outputs"
    examples_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    maps = {
        "minimal_conops": build_minimal_conops_map(),
        "current_physics_backbone": build_current_physics_backbone_map(),
        "strong_weak_interface": build_strong_weak_interface_map(),
        "dynamic_cosmology": build_dynamic_cosmology_map(),
    }
    for stem, pm in maps.items():
        json_path = examples_dir / f"{stem}.json"
        pm.to_json(json_path)
        paths = write_full_report(pm, reports_dir, basename=stem)
        render_radial_svg(pm, reports_dir / f"{stem}_sphere.svg")
        write_lean_skeleton(pm, reports_dir / f"{stem}_LeanSketch.lean")
        if pm.epochs:
            render_dynamic_csv(metrics_over_epochs(pm), reports_dir / f"{stem}_dynamic_metrics.csv")
        surface_paths = render_surface_bundle(pm, reports_dir, basename=stem)
        print(f"Generated {stem}: {json_path}")
        print(f"  report: {paths['report']}")
        print(f"  svg: {reports_dir / f'{stem}_sphere.svg'}")
        print(f"  surface: {surface_paths['surface_html']}")
    theory_catalog = build_physics_theory_catalog()
    theory_sources = build_physics_theory_source_registry()
    theory_dir = examples_dir / "theories"
    theory_dir.mkdir(parents=True, exist_ok=True)
    theory_catalog_path = theory_dir / "physics_theory_catalog.json"
    theory_catalog.to_json(theory_catalog_path)
    source_dir = examples_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    theory_sources.to_json(source_dir / "physics_theory_sources.json")
    theory_report = reports_dir / "physics_theory_catalog_report.md"
    write_theory_catalog_report(theory_catalog, theory_report)
    print(f"Generated theory catalog: {theory_catalog_path}")
    print(f"  report: {theory_report}")
    return 0


def cmd_surface(args: argparse.Namespace) -> int:
    pm = ProofMap.from_json(args.input)
    out = Path(args.out)
    basename = args.basename or Path(args.input).stem
    paths = render_surface_bundle(pm, out, basename=basename, coordinate_mode=args.coordinate_mode)
    for key, path in sorted(paths.items()):
        print(f"{key}: {path}")
    return 0


def _expand_file_args(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        matches = [Path(p) for p in glob.glob(pattern)]
        if not matches:
            matches = [Path(pattern)]
        for path in matches:
            normalized = path.resolve()
            if normalized not in seen:
                seen.add(normalized)
                paths.append(path)
    return paths


def cmd_lean_check(args: argparse.Namespace) -> int:
    _trusted_host(args)
    files = _expand_file_args(args.files)
    existing = [path for path in files if path.exists()]
    missing = [path for path in files if not path.exists()]
    for path in missing:
        print(f"missing: {path}", file=sys.stderr)
    if not existing:
        print("No Lean files to check.", file=sys.stderr)
        return 2

    lean = resolve_lean_executable(args.lean)
    if lean is None:
        print("Lean executable not found. Install elan/Lean or set PROOFMAP_LEAN.", file=sys.stderr)
        return 3

    try:
        results = check_lean_files(existing, lean_executable=lean, timeout=args.timeout)
    except OSError as exc:
        print(f"Verifier unavailable: {exc}", file=sys.stderr)
        return 3
    for result in results:
        if result.ok:
            print(f"ok: {result.path}")
        else:
            print(f"failed: {result.path}", file=sys.stderr)
            if result.stdout:
                print(result.stdout, file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
    if missing:
        return 2
    if any(result.returncode < 0 for result in results):
        return 3
    return 0 if all(result.ok for result in results) else 1


def _trusted_host(args: argparse.Namespace) -> None:
    if args.execution_mode != "trusted-host":
        raise ValueError("Legacy verification requires execution-mode trusted-host")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError("Verifier timeout must be finite and positive")
    print(
        "execution-mode: trusted-host (legacy compatibility; local trusted code only; "
        "not isolated paper evidence)",
        file=sys.stderr,
    )


def cmd_attempt_check(args: argparse.Namespace) -> int:
    try:
        _trusted_host(args)
        project_root = Path(args.project_root).resolve()
        candidate_path = Path(args.candidate).expanduser()
        if not candidate_path.is_absolute():
            candidate_path = project_root / candidate_path
        candidate_path = candidate_path.resolve()
        output_path = Path(args.out).resolve()
        protected_inputs = [
            Path(args.map).resolve(),
            Path(args.obligation).resolve(),
            candidate_path,
        ]
        for input_path in protected_inputs:
            same_path = output_path == input_path
            if not same_path and output_path.exists() and input_path.exists():
                same_path = output_path.samefile(input_path)
            if same_path:
                raise ValueError(f"Receipt output must not overwrite an input file: {input_path}")

        proof_map = ProofMap.from_json(args.map)
        obligation = FormalObligation.from_json(args.obligation)
        candidate = Path(args.candidate)
        attempt = ProofAttempt(
            id=args.attempt_id or f"{candidate.stem}.attempt",
            obligation_id=obligation.id,
            artifact_path=str(candidate),
            artifact_sha256=args.artifact_sha256,
            producer=args.producer,
            provider=args.provider,
            model=args.model,
            model_version=args.model_version,
            run_id=args.run_id,
            prompt_sha256=args.prompt_sha256,
            parent_attempt_ids=args.parent,
            strategy=args.strategy,
            input_tokens=args.input_tokens,
            output_tokens=args.output_tokens,
            generation_seconds=args.generation_seconds,
            estimated_cost_usd=args.estimated_cost_usd,
        )
        receipt = check_proof_attempt(
            proof_map,
            obligation,
            attempt,
            map_path=args.map,
            project_root=project_root,
            lean_executable=args.lean,
            timeout=args.timeout,
        )
        receipt.to_json(args.out)
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        print(f"attempt-check input error: {exc}", file=sys.stderr)
        return 2

    print(f"receipt: {Path(args.out)}")
    print(f"attempt: {receipt.attempt.id}")
    print(f"target: {receipt.target_node_id}")
    print(f"outcome: {receipt.verification.outcome.value}")
    print(f"verified: {str(receipt.verified).lower()}")
    if receipt.verification.axioms:
        print(f"axioms: {', '.join(receipt.verification.axioms)}")
    for issue in receipt.verification.policy_issues:
        print(f"policy: {issue}")
    if not receipt.verified:
        if receipt.verification.stdout:
            print(receipt.verification.stdout, file=sys.stderr)
        if receipt.verification.stderr:
            print(receipt.verification.stderr, file=sys.stderr)

    if receipt.verification.outcome == AttemptOutcome.VERIFIED:
        return 0
    if receipt.verification.outcome in {
        AttemptOutcome.VERIFIER_UNAVAILABLE,
        AttemptOutcome.VERIFIER_ERROR,
        AttemptOutcome.TIMEOUT,
    }:
        return 3
    return 1


def cmd_validate_conops(args: argparse.Namespace) -> int:
    result = run_conops_validation(
        args.out,
        lean_executable=args.lean,
        require_lean=args.require_lean,
        timeout=args.timeout,
    )
    print(f"summary: {result.summary_path}")
    print(f"ok: {str(result.ok).lower()}")
    print(f"gap_count: {result.metrics['gap_count']}")
    print(f"seam_count: {result.metrics['seam_count']}")
    print(f"expected_defect: {'boundary.drag_residual' in result.defect_ids}")
    if result.lean_checked:
        print(f"lean_ok: {str(result.lean_ok).lower()}")
    else:
        print("lean_ok: skipped")
    for note in result.notes:
        print(f"note: {note}")
    return 0 if result.ok else 1


def cmd_validate_current_physics(args: argparse.Namespace) -> int:
    result = run_current_physics_backbone_validation(
        args.out,
        lean_executable=args.lean,
        require_lean=args.require_lean,
        timeout=args.timeout,
    )
    print(f"summary: {result.summary_path}")
    print(f"ok: {str(result.ok).lower()}")
    print(f"node_count: {result.metrics['node_count']}")
    print(f"gap_count: {result.metrics['gap_count']}")
    print(f"seam_count: {result.metrics['seam_count']}")
    print(f"source_coverage_errors: {len(result.source_coverage_errors)}")
    print(f"theory_catalog_errors: {len(result.theory_catalog_errors)}")
    print(f"theory_binding_errors: {len(result.theory_binding_errors)}")
    if result.lean_checked:
        print(f"lean_ok: {str(result.lean_ok).lower()}")
    else:
        print("lean_ok: skipped")
    for note in result.notes:
        print(f"note: {note}")
    return 0 if result.ok else 1


def cmd_hypothesis_search(args: argparse.Namespace) -> int:
    pm = ProofMap.from_json(args.input)
    catalog = HypothesisCatalog.from_json(args.hypotheses)
    basename = args.basename or Path(args.hypotheses).stem
    paths = write_hypothesis_search(pm, catalog, args.out, basename=basename)
    evaluations = rank_hypotheses(pm, catalog.hypotheses)
    valid = [evaluation for evaluation in evaluations if evaluation.valid]
    print(f"report: {paths['report']}")
    print(f"json: {paths['json']}")
    print(f"candidates: {len(evaluations)}")
    print(f"valid: {len(valid)}")
    if valid:
        print(f"top: {valid[0].hypothesis_id}")
        print(f"top_score: {valid[0].score}")
    for evaluation in evaluations:
        state = "valid" if evaluation.valid else "invalid"
        print(f"candidate: {evaluation.hypothesis_id} score={evaluation.score} state={state}")
    return 0 if valid else 1


def cmd_theory_list(args: argparse.Namespace) -> int:
    catalog = TheoryCatalog.from_json(args.catalog)
    profiles = catalog.select(
        family=args.family,
        maturity=args.maturity,
        domain=args.domain,
        kind=args.kind,
    )
    if args.json:
        print(json.dumps([profile.to_dict() for profile in profiles], indent=2, sort_keys=True))
    else:
        for profile in profiles:
            print(
                f"{profile.id}\t{profile.maturity.value}\t{profile.evidence_status.value}\t"
                f"{profile.family}\t{profile.name}"
            )
        print(f"profiles: {len(profiles)}")
    return 0


def cmd_theory_validate(args: argparse.Namespace) -> int:
    catalog = TheoryCatalog.from_json(args.catalog)
    source_registry = SourceRegistry.from_json(args.sources) if args.sources else None
    catalog_result = validate_theory_catalog(
        catalog,
        source_registry,
        require_sources=args.require_sources,
    )
    payload: dict[str, object] = {"catalog": catalog_result.to_dict()}
    ok = catalog_result.ok
    if args.map:
        proof_map = ProofMap.from_json(args.map)
        binding_result = validate_theory_bindings(
            proof_map,
            catalog,
            require_any=args.require_bindings,
        )
        payload["bindings"] = binding_result.to_dict()
        ok = ok and binding_result.ok
    if args.report:
        path = write_theory_catalog_report(catalog, args.report, catalog_result)
        payload["report"] = str(path)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if ok else 1


def cmd_theory_scaffold(args: argparse.Namespace) -> int:
    catalog = TheoryCatalog.from_json(args.catalog)
    proof_map = build_theory_scaffold(catalog, args.theory_id)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    proof_map.to_json(out)
    print(f"map: {out}")
    print(f"nodes: {len(proof_map.nodes)}")
    print(f"edges: {len(proof_map.edges)}")
    print(f"gaps: {analyze(proof_map).gap_count}")
    return 0


def cmd_theory_slice(args: argparse.Namespace) -> int:
    proof_map = ProofMap.from_json(args.input)
    sliced = proof_map.theory_slice(
        args.theory_ids,
        include_shared=not args.exclude_shared,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sliced.to_json(out)
    print(f"map: {out}")
    print(f"theories: {', '.join(sorted(args.theory_ids))}")
    print(f"nodes: {len(sliced.nodes)}")
    print(f"edges: {len(sliced.edges)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Proof Map Boundary Analysis toolkit")
    sub = parser.add_subparsers(dest="command", required=True)
    from .kernel_cli import add_commands

    add_commands(sub)
    from .trust_cli import add_commands as add_trust_commands

    add_trust_commands(sub)
    from .paper_cli import add_commands as add_paper_commands

    add_paper_commands(sub)
    from .campaign.cli import add_commands as add_campaign_commands

    add_campaign_commands(sub)

    p = sub.add_parser("examples", help="Write seed example proof maps as JSON")
    p.add_argument("--out", default="examples")
    p.set_defaults(func=cmd_examples)

    p = sub.add_parser("analyze", help="Print metrics for a proof-map JSON file")
    p.add_argument("input")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser(
        "report", help="Generate reports, ledgers, SVG, Lean scaffold, and proof-surface assets"
    )
    p.add_argument("input")
    p.add_argument("--out", default="outputs")
    p.add_argument("--basename", default=None)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser(
        "surface", help="Generate proof-surface atlas, explorer, point CSV, and layout JSON"
    )
    p.add_argument("input")
    p.add_argument("--out", default="outputs")
    p.add_argument("--basename", default=None)
    p.add_argument("--coordinate-mode", choices=["auto", "time", "proof_depth"], default="auto")
    p.set_defaults(func=cmd_surface)

    p = sub.add_parser("lean-check", help="Compile trusted local Lean files (legacy host mode)")
    p.add_argument(
        "--execution-mode",
        choices=["trusted-host"],
        default="trusted-host",
        help="Legacy host execution; default trusted-host. Use paper ci for isolated evidence.",
    )
    p.add_argument("files", nargs="+", help="Lean files or shell-style globs")
    p.add_argument(
        "--lean",
        default=None,
        help="Path to the Lean executable; defaults to PATH, PROOFMAP_LEAN, or ~/.elan/bin/lean",
    )
    p.add_argument("--timeout", type=float, default=60.0, help="Per-file timeout in seconds")
    p.set_defaults(func=cmd_lean_check)

    p = sub.add_parser(
        "attempt-check",
        help="Check a trusted local Lean term and write a legacy host receipt",
    )
    p.add_argument(
        "--execution-mode",
        choices=["trusted-host"],
        default="trusted-host",
        help="Legacy host execution; default trusted-host. Receipts are not isolated paper evidence.",
    )
    p.add_argument("map", help="Proof-map JSON file containing the target node")
    p.add_argument("obligation", help="Formal-obligation JSON file")
    p.add_argument("candidate", help="Lean proof-term file beginning with 'by'")
    p.add_argument("--out", required=True, help="Output verification-receipt JSON file")
    p.add_argument(
        "--producer", required=True, help="Agent, person, or workflow that produced the candidate"
    )
    p.add_argument("--provider", default="", help="Optional model provider or organization")
    p.add_argument("--model", default="", help="Optional model identifier")
    p.add_argument("--model-version", default="", help="Optional immutable model version")
    p.add_argument("--run-id", default="", help="Optional external run identifier")
    p.add_argument(
        "--prompt-sha256", default="", help="Optional SHA-256 hash of the generating prompt"
    )
    p.add_argument(
        "--artifact-sha256", default="", help="Optional expected SHA-256 hash of the candidate"
    )
    p.add_argument(
        "--attempt-id",
        default=None,
        help="Attempt identifier; defaults to <candidate-stem>.attempt",
    )
    p.add_argument(
        "--parent",
        action="append",
        default=[],
        help="Parent attempt id; repeat for repair/branch lineage",
    )
    p.add_argument("--strategy", default="", help="Optional generation or repair strategy label")
    p.add_argument("--input-tokens", type=int, default=0)
    p.add_argument("--output-tokens", type=int, default=0)
    p.add_argument("--generation-seconds", type=float, default=0.0)
    p.add_argument("--estimated-cost-usd", type=float, default=0.0)
    p.add_argument(
        "--project-root",
        default=".",
        help="Lean project root and base for relative candidate paths",
    )
    p.add_argument(
        "--lean",
        default=None,
        help="Path to Lean; defaults to PATH, PROOFMAP_LEAN, or ~/.elan/bin/lean",
    )
    p.add_argument(
        "--timeout", type=float, default=120.0, help="Lean verification timeout in seconds"
    )
    p.set_defaults(func=cmd_attempt_check)

    p = sub.add_parser("validate-conops", help="Run the legacy five-node artifact smoke test")
    p.add_argument("--out", default="outputs/conops_validation")
    p.add_argument(
        "--lean",
        default=None,
        help="Path to the Lean executable; defaults to PATH, PROOFMAP_LEAN, or ~/.elan/bin/lean",
    )
    p.add_argument("--require-lean", action="store_true", help="Fail if Lean is unavailable")
    p.add_argument("--timeout", type=float, default=120.0, help="Lean check timeout in seconds")
    p.set_defaults(func=cmd_validate_conops)

    p = sub.add_parser(
        "validate-current-physics", help="Run the source-backed current-physics backbone validation"
    )
    p.add_argument("--out", default="outputs/current_physics_backbone")
    p.add_argument(
        "--lean",
        default=None,
        help="Path to the Lean executable; defaults to PATH, PROOFMAP_LEAN, or ~/.elan/bin/lean",
    )
    p.add_argument("--require-lean", action="store_true", help="Fail if Lean is unavailable")
    p.add_argument("--timeout", type=float, default=120.0, help="Lean check timeout in seconds")
    p.set_defaults(func=cmd_validate_current_physics)

    p = sub.add_parser(
        "hypothesis-search", help="Rank explicit candidate mechanisms for proof-map gaps"
    )
    p.add_argument("input", help="Proof-map JSON file")
    p.add_argument("hypotheses", help="Hypothesis catalog JSON file")
    p.add_argument("--out", default="outputs/hypothesis_search")
    p.add_argument("--basename", default=None)
    p.set_defaults(func=cmd_hypothesis_search)

    p = sub.add_parser("theory-list", help="List and filter profiles in a theory catalog")
    p.add_argument("catalog", help="Theory-catalog JSON file")
    p.add_argument("--family", default=None)
    p.add_argument("--maturity", choices=[item.value for item in TheoryMaturity], default=None)
    p.add_argument("--domain", default=None)
    p.add_argument("--kind", choices=[item.value for item in TheoryKind], default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_theory_list)

    p = sub.add_parser(
        "theory-validate", help="Validate a theory catalog and optional map bindings"
    )
    p.add_argument("catalog", help="Theory-catalog JSON file")
    p.add_argument("--sources", default=None, help="Optional source-registry JSON file")
    p.add_argument("--map", default=None, help="Optional proof-map JSON file with theory bindings")
    p.add_argument("--require-sources", action="store_true")
    p.add_argument("--require-bindings", action="store_true")
    p.add_argument("--report", default=None, help="Optional Markdown report path")
    p.set_defaults(func=cmd_theory_validate)

    p = sub.add_parser(
        "theory-scaffold", help="Generate a proof-map scaffold from a theory profile"
    )
    p.add_argument("catalog", help="Theory-catalog JSON file")
    p.add_argument("theory_id")
    p.add_argument("--out", required=True, help="Output proof-map JSON file")
    p.set_defaults(func=cmd_theory_scaffold)

    p = sub.add_parser("theory-slice", help="Extract selected theory charts from a bound proof map")
    p.add_argument("input", help="Proof-map JSON file")
    p.add_argument("theory_ids", nargs="+")
    p.add_argument("--out", required=True, help="Output proof-map JSON file")
    p.add_argument("--exclude-shared", action="store_true")
    p.set_defaults(func=cmd_theory_slice)

    p = sub.add_parser("demo", help="Generate the bundled examples and outputs")
    p.add_argument("--out", default=".")
    p.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
