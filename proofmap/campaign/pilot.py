"""Measured, rights-backed source intake; research-quality labels stay independent."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..integrity import artifact_digest, load_json, rooted_path, write_json
from ..paper_sources import source_validation_operation


def validate_corpus(corpus: Path) -> dict[str, Any]:
    corpus = corpus.resolve(strict=True)
    manifest = load_json(corpus / "provenance.json")
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "1.0"
        or len(manifest.get("samples", [])) < 3
        or len(manifest["samples"]) > 20
    ):
        raise ValueError("PILOT_CORPUS_INVENTORY")
    ids: set[str] = set()
    authors: set[str] = set()
    formats: set[str] = set()
    for sample in manifest["samples"]:
        if sample["id"] in ids or not sample["rights"] or not sample["transformation"]:
            raise ValueError("PILOT_CORPUS_PROVENANCE")
        ids.add(sample["id"])
        authors.add(sample["author"])
        formats.add(sample["format"])
        path = rooted_path(corpus, sample["path"])
        declared = sample["retained_artifacts"]
        actual = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
        if {p.relative_to(corpus).as_posix() for p in actual} != {r["path"] for r in declared}:
            raise ValueError("PILOT_SOURCE_ARTIFACT_SET")
        for row in declared:
            source = rooted_path(corpus, row["path"])
            raw = source.read_bytes()
            if len(raw) != row["bytes"] or artifact_digest(raw) != row["sha256"]:
                raise ValueError("PILOT_SOURCE_ARTIFACT_CHANGED")
    if len(authors) < 3 or not {"born-digital-pdf", "multi-file-tex"} <= formats:
        raise ValueError("PILOT_CORPUS_COMPOSITION")
    return manifest


@source_validation_operation
def evaluate_realism(
    corpus: Path,
    out: Path,
    *,
    live_config: dict[str, Any] | None = None,
    disclosure_authorized: bool = False,
) -> dict[str, Any]:
    """Use normal intake, validated anchors and actual pure-stage reuse, offline by default.

    Live quality remains NOT_MEASURED without independently labelled quality,
    even when a configured endpoint actually supplies model responses.
    """
    from ..extractor import validate_config
    from ..paper import ci
    from ..paper_sources import locator_validation_session, validate_locator
    from ..paper_store import PaperStore

    manifest = validate_corpus(corpus)
    if live_config is not None:
        if not disclosure_authorized:
            raise ValueError("PILOT_MODEL_DISCLOSURE_NOT_AUTHORIZED")
        validate_config(live_config)
        if not {
            "max_requests",
            "max_input_bytes",
            "max_total_output_tokens",
            "max_total_seconds",
        } <= set(live_config):
            raise ValueError("PILOT_MODEL_EXPLICIT_BUDGET_REQUIRED")
    out.mkdir(parents=True, exist_ok=True)
    store_root = out / "store"
    budget_keys = (
        "max_requests",
        "max_input_bytes",
        "max_total_output_tokens",
        "max_total_seconds",
    )
    remaining = {key: live_config[key] for key in budget_keys} if live_config else {}
    reservations: list[dict[str, Any]] = []
    rows = []
    for sample in manifest["samples"]:
        started = time.monotonic()
        source = rooted_path(corpus, sample["path"])
        # Reserve each document's configured maximum before any disclosure.
        # Unknown usage and interrupted replies never release this reservation.
        # These are whole-pilot limits, rather than per-document counters reset
        # on every call. A larger optional pilot can explicitly partition its
        # budgets in separate operator-initiated runs.
        dispatch = live_config is not None and all(
            remaining[key] >= live_config[key] for key in budget_keys
        )
        if dispatch:
            assert live_config is not None
            for key in budget_keys:
                remaining[key] -= live_config[key]
            reservations.append(
                {
                    "document": sample["id"],
                    "reserved": {key: live_config[key] for key in budget_keys},
                }
            )
        bundle, code = ci(
            source,
            out / sample["id"] / "initial",
            store_root,
            entrypoint=sample["entrypoint"],
            paper_id="realism:" + sample["id"],
            extractor="configured" if dispatch else "none",
            config={"extractor": live_config} if dispatch else None,
        )
        stored = PaperStore(store_root)
        try:
            retained = stored.inspect(bundle["run_manifest"]["run_id"])
            artifacts = {name: stored.get(sha) for name, sha in retained["artifacts"].items()}
        finally:
            stored.close()
        session = locator_validation_session()
        valid = 0
        failures = []
        for element in bundle["document_ir"]["elements"]:
            try:
                validate_locator(element["locator"], artifacts, element["text"], session=session)
                valid += 1
            except ValueError as exc:
                failures.append(str(exc))
        # Reuse is observed by a second normal pipeline call; it is not inferred
        # from a cache label or from merely hashing equal source bytes.
        resumed, resumed_code = ci(
            source,
            out / sample["id"] / "resumed",
            store_root,
            entrypoint=sample["entrypoint"],
            paper_id="realism:" + sample["id"],
            resume=True,
        )
        formals = bundle["formalizations"]
        executions = bundle["execution_events"]
        rows.append(
            {
                "id": sample["id"],
                "author": sample["author"],
                "format": sample["format"],
                "rights_url": sample["rights_url"],
                "source_revision": bundle["input_manifest"]["revision"],
                "run_id": bundle["run_manifest"]["run_id"],
                "runtime_seconds": round(time.monotonic() - started, 6),
                "exit_code": code,
                "resume_exit_code": resumed_code,
                "source_bytes": sum(len(raw) for raw in artifacts.values()),
                "source_artifacts": len(artifacts),
                "anchors_valid": valid,
                "anchors_total": len(bundle["document_ir"]["elements"]),
                "anchor_failures": failures,
                "discovered_claims": len(bundle["assertions"]),
                "supported_claims": sum(r["status"] == "SUPPORTED" for r in formals),
                "unsupported_claims": sum(r["status"] != "SUPPORTED" for r in formals),
                "verified_claims": sum(r["event"]["outcome"] == "VERIFIED" for r in executions),
                "review_burden_targets": sum(r["status"] == "SUPPORTED" for r in formals),
                "reused_pure_stages": len(
                    resumed["run_manifest"]["cache_provenance"]["reused_stages"]
                ),
                "parser_failures": int(
                    bundle["document_ir"]["parser"].get("execution")
                    in {"TIMEOUT", "ERROR", "UNAVAILABLE"}
                ),
                "false_hard_blocks": None,
                "false_hard_blocks_denominator": 0,
                "fidelity": None,
                "novelty": None,
                "unknown_reason": "NO_INDEPENDENT_RESEARCH_QUALITY_LABELS",
                "live_model_events": len(bundle["extraction_events"]) if dispatch else 0,
                "model_dispatch": "EXPLICITLY_CONFIGURED_ATTEMPT"
                if dispatch
                else "NOT_RUN_BUDGET_EXHAUSTED"
                if live_config
                else "NOT_REQUESTED",
            }
        )
    labelled = [r["anchors_valid"] / r["anchors_total"] for r in rows if r["anchors_total"]]
    metrics = (
        "discovered_claims",
        "supported_claims",
        "unsupported_claims",
        "verified_claims",
        "review_burden_targets",
        "reused_pure_stages",
        "runtime_seconds",
        "parser_failures",
    )
    result = {
        "schema_version": "1.0",
        "corpus_id": manifest["corpus_id"],
        "composition": manifest["composition"],
        "documents": rows,
        "documents_total": len(rows),
        "macro": {name: sum(r[name] for r in rows) / len(rows) for name in metrics},
        "source_anchor_validity": {
            "macro": sum(labelled) / len(labelled) if labelled else None,
            "macro_documents_denominator": len(labelled),
            "valid": sum(r["anchors_valid"] for r in rows),
            "total": sum(r["anchors_total"] for r in rows),
        },
        "live_model_execution": "OBSERVED"
        if live_config and any(r["live_model_events"] for r in rows)
        else "NOT_MEASURED",
        "live_model_quality": "NOT_MEASURED",
        "live_model_budget": {
            "scope": "ENTIRE_PILOT",
            "accounting": "CONSERVATIVE_DOCUMENT_MAXIMA_RESERVED_BEFORE_DISPATCH",
            "configured": {key: live_config[key] for key in budget_keys} if live_config else None,
            "reservations": reservations,
            "remaining": remaining,
            "absent_usage_is_not_zero": True,
        },
        "external_user_pilot": "NOT_PERFORMED",
        "production_authority": "NOT_CONFIGURED",
        "publication": "NOT_REQUESTED",
        "boundary": "Intake of historical excerpts only; wrapper structure is adapted. No scientific accuracy, productivity or novelty claim.",
    }
    write_json(out / "realism-outcomes.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live-config", type=Path)
    parser.add_argument("--authorize-disclosure", action="store_true")
    args = parser.parse_args(argv)
    value = evaluate_realism(
        args.corpus,
        args.out,
        live_config=load_json(args.live_config) if args.live_config else None,
        disclosure_authorized=args.authorize_disclosure,
    )
    print("Realism intake", value["documents_total"], "documents", value["source_anchor_validity"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
