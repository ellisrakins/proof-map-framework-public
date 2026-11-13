"""Attributed interpretation edits are immutable analysis, never proof authority."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .integrity import canonical_bytes, digest, strict_loads, write_json
from .kernel import Inference, closure
from .schema import validate

ROLES = frozenset(
    {
        "THEOREM",
        "LEMMA",
        "PROPOSITION",
        "COROLLARY",
        "CONJECTURE",
        "DEFINITION",
        "ASSUMPTION",
        "UNRESOLVED",
    }
)


def _targets(ir: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "kind": row["kind"],
            "scope": row["scope"],
            "source_digest": digest("interpretation-target.v1", row),
        }
        for row in ir["elements"]
        if row["kind"] in {"ASSERTION", "PROOF"}
    ]


def override_export(bundle: dict[str, Any], author: str) -> dict[str, Any]:
    if not isinstance(author, str) or not author.strip() or len(author) > 512:
        raise ValueError("OVERRIDE_ATTRIBUTION_REQUIRED")
    return {
        "schema_version": "1.0",
        "record_type": "InterpretationOverride",
        "revision": bundle["input_manifest"]["revision"],
        "run_id": bundle["run_manifest"]["run_id"],
        "analysis_digest": bundle["run_manifest"]["analysis_digest"],
        "policy_digest": bundle["run_manifest"]["policy_digest"],
        "raw_ir_digest": digest("interpretation-raw-ir.v1", bundle["document_ir"]),
        "extraction_digest": digest("interpretation-extraction.v1", bundle["extraction_events"]),
        "prior_overrides_digest": digest(
            "interpretation-history.v1", bundle.get("interpretation_overrides", [])
        ),
        "author": author,
        "attribution_authenticated": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "targets": _targets(bundle.get("interpreted_ir", bundle["document_ir"])),
        "changes": [],
    }


def _validate_record(record: dict[str, Any]) -> None:
    if validate("interpretation-override", record):
        raise ValueError("OVERRIDE_RECORD_SCHEMA")
    fields = {
        "schema_version",
        "record_type",
        "revision",
        "run_id",
        "analysis_digest",
        "policy_digest",
        "raw_ir_digest",
        "extraction_digest",
        "prior_overrides_digest",
        "author",
        "attribution_authenticated",
        "created_at",
        "targets",
        "changes",
    }
    if not isinstance(record, dict) or set(record) != fields | {"id"}:
        raise ValueError("OVERRIDE_RECORD_FIELDS")
    if (
        record["schema_version"] != "1.0"
        or record["record_type"] != "InterpretationOverride"
        or record["attribution_authenticated"] is not False
    ):
        raise ValueError("OVERRIDE_RECORD_VERSION_OR_AUTHORITY")
    if record["id"] != digest(
        "interpretation-override.v1", {k: v for k, v in record.items() if k != "id"}
    ):
        raise ValueError("OVERRIDE_RECORD_DIGEST")
    if (
        not isinstance(record["author"], str)
        or not record["author"].strip()
        or len(record["author"]) > 512
    ):
        raise ValueError("OVERRIDE_ATTRIBUTION_REQUIRED")
    try:
        stamp = datetime.fromisoformat(record["created_at"])
        if stamp.tzinfo is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
            raise ValueError("UTC required")
    except (TypeError, ValueError) as exc:
        raise ValueError("OVERRIDE_TIMESTAMP") from exc
    if not isinstance(record["changes"], list) or not 1 <= len(record["changes"]) <= 256:
        raise ValueError("OVERRIDE_CHANGE_COUNT")


def _apply_changes(ir: dict[str, Any], record: dict[str, Any]) -> None:
    _validate_record(record)
    targets = {row["id"]: row for row in _targets(ir)}
    if record["targets"] != list(targets.values()):
        raise ValueError("STALE_OVERRIDE_TARGETS")
    elements = {row["id"]: row for row in ir["elements"]}
    seen = set()
    for change in record["changes"]:
        if not isinstance(change, dict) or set(change) != {
            "kind",
            "target",
            "scope",
            "source_digest",
            "value",
            "note",
        }:
            raise ValueError("OVERRIDE_CHANGE_FIELDS")
        target = targets.get(change["target"])
        if target is None or any(change[key] != target[key] for key in ("scope", "source_digest")):
            raise ValueError("STALE_OVERRIDE_SOURCE_OR_SCOPE")
        pair = (change["target"], change["kind"])
        if pair in seen:
            raise ValueError("DUPLICATE_OVERRIDE_TARGET")
        seen.add(pair)
        if (
            not isinstance(change["note"], str)
            or not change["note"].strip()
            or len(change["note"]) > 4096
        ):
            raise ValueError("OVERRIDE_REASON_REQUIRED")
        element = elements[change["target"]]
        value = change["value"]
        if change["kind"] == "role":
            if element["kind"] != "ASSERTION" or not isinstance(value, str) or value not in ROLES:
                raise ValueError("OVERRIDE_ROLE")
            element["role"] = value
        elif change["kind"] == "proof_for":
            if element["kind"] != "PROOF" or (
                value is not None
                and (
                    not isinstance(value, str)
                    or value not in targets
                    or targets[value]["kind"] != "ASSERTION"
                    or targets[value]["scope"] != element["scope"]
                )
            ):
                raise ValueError("OVERRIDE_PROOF_SCOPE")
            element["proof_for"] = value
        elif change["kind"] == "dependencies":
            if (
                element["kind"] != "ASSERTION"
                or not isinstance(value, list)
                or any(not isinstance(p, str) for p in value)
                or len(value) != len(set(value))
                or len(value) > 256
            ):
                raise ValueError("OVERRIDE_DEPENDENCIES")
            if any(
                p == element["id"]
                or p not in targets
                or targets[p]["kind"] != "ASSERTION"
                or targets[p]["scope"] != element["scope"]
                for p in value
            ):
                raise ValueError("OVERRIDE_DEPENDENCY_SCOPE")
        else:
            raise ValueError("OVERRIDE_CHANGE_KIND")


def interpreted_document(bundle: dict[str, Any]) -> dict[str, Any]:
    ir: dict[str, Any] = deepcopy(bundle["document_ir"])
    previous: list[dict[str, Any]] = []
    prior_analysis = None
    for record in bundle.get("interpretation_overrides", []):
        _validate_record(record)
        if (
            record["revision"] != ir["revision"]
            or record["raw_ir_digest"] != digest("interpretation-raw-ir.v1", bundle["document_ir"])
            or record["extraction_digest"]
            != digest("interpretation-extraction.v1", bundle["extraction_events"])
            or record["prior_overrides_digest"] != digest("interpretation-history.v1", previous)
        ):
            raise ValueError("OVERRIDE_RAW_SOURCE_OR_HISTORY_MISMATCH")
        if record["policy_digest"] != bundle["run_manifest"]["policy_digest"] or (
            prior_analysis is not None and record["analysis_digest"] != prior_analysis
        ):
            raise ValueError("OVERRIDE_ANALYSIS_OR_POLICY_MISMATCH")
        _apply_changes(ir, record)
        previous.append(record)
        prior_analysis = digest(
            "paper-interpretation-analysis.v1",
            {"base": record["analysis_digest"], "override": record["id"]},
        )
    return ir


def _derive(bundle: dict[str, Any]) -> tuple[list[dict[str, Any]], Any, dict[str, Any]]:
    from .extractor import semantic_overlay
    from .paper import assertion_layer

    ir = interpreted_document(bundle)
    assertions, graph = assertion_layer(ir)
    history_digest = digest("interpretation-history.v1", bundle["interpretation_overrides"])
    for assertion in assertions:
        assertion["interpretation_digest"] = history_digest
    overlay = semantic_overlay(bundle["document_ir"], bundle["extraction_events"])
    dependencies = [
        {**row, "authority": "MODEL_SUGGESTION"}
        for row in overlay.get("candidate_dependencies", [])
    ]
    for record in bundle["interpretation_overrides"]:
        for change in record["changes"]:
            if change["kind"] == "dependencies":
                dependencies = [
                    row for row in dependencies if row["conclusion"] != change["target"]
                ]
                dependencies.append(
                    {
                        "conclusion": change["target"],
                        "premises": change["value"],
                        "authority": "ATTRIBUTED_NOT_AUTHENTICATED",
                    }
                )
    ids = {a["id"] for a in assertions}
    candidates = [
        Inference(
            "interpretation:"
            + digest(
                "interpretation-inference.v1",
                {"group": row, "index": index, "history": history_digest},
            ),
            row["conclusion"],
            tuple(row["premises"]),
            ir["revision"],
            mode="PAPER_ASSERTION",
            status="REVIEW_REQUIRED",
        )
        for index, row in enumerate(dependencies)
        if row["conclusion"] in ids and all(p in ids for p in row["premises"])
    ]
    graph = replace(graph, inferences=graph.inferences + tuple(candidates))
    graph.validate()
    overlay["interpretation_dependencies"] = dependencies
    return assertions, graph, overlay


def validate_override_bundle(bundle: dict[str, Any]) -> None:
    history = bundle.get("interpretation_overrides")
    if not isinstance(history, list) or not history or len(history) > 256:
        raise ValueError("OVERRIDE_HISTORY_REQUIRED")
    if interpreted_document(bundle) != bundle.get("interpreted_ir"):
        raise ValueError("OVERRIDE_INTERPRETED_IR_MISMATCH")
    assertions, graph, overlay = _derive(bundle)
    if canonical_bytes([assertions, graph.to_dict(), overlay]) != canonical_bytes(
        [bundle["assertions"], bundle["argument_map"], bundle["semantic_overlay"]]
    ):
        raise ValueError("OVERRIDE_DERIVATION_MISMATCH")
    expected = digest(
        "paper-interpretation-analysis.v1",
        {"base": history[-1]["analysis_digest"], "override": history[-1]["id"]},
    )
    if (
        bundle["run_manifest"]["analysis_digest"] != expected
        or bundle["run_manifest"].get("parent_run_id") != history[-1]["run_id"]
    ):
        raise ValueError("OVERRIDE_DERIVED_RUN_BINDING")
    if bundle.get("execution_events") or bundle.get("acceptance_records"):
        raise ValueError("OVERRIDE_CANNOT_CARRY_AUTHORITY")
    from .paper_evidence import analyze_formalizations

    fresh = analyze_formalizations(
        bundle["interpreted_ir"],
        assertions,
        execution_profile=None,
        controller_key=None,
        controller_id="interpretation-only",
        trust_store=None,
        evaluation_time=None,
        required=False,
    )
    if bundle["formalizations"] != fresh["formalizations"]:
        raise ValueError("OVERRIDE_FORMAL_DERIVATION_MISMATCH")
    outcomes = bundle["assessment"]["outcomes"]
    if (
        any(
            outcomes["coverage"].get(name) != 0
            for name in ("kernel_verified", "reviewed_claims", "accepted_claims")
        )
        or outcomes.get("kernel_verification") != "NOT_RUN"
        or outcomes.get("formal_statement_fidelity") != "NOT_REVIEWED"
    ):
        raise ValueError("OVERRIDE_CANNOT_CARRY_ASSESSMENT_AUTHORITY")


def apply_override(
    bundle: dict[str, Any],
    draft: dict[str, Any],
    store: Any,
    out: Path | None = None,
) -> dict[str, Any]:
    """Create a new run and recompute analysis; raw source/model records stay identical."""
    indexed = store.inspect(bundle["run_manifest"]["run_id"])
    if canonical_bytes(indexed["bundle"]) != canonical_bytes(bundle):
        raise ValueError("OVERRIDE_REQUIRES_IMMUTABLE_INDEXED_PARENT")
    if not isinstance(draft, dict):
        raise ValueError("OVERRIDE_DRAFT_TYPE")
    expected = override_export(bundle, draft.get("author", ""))
    if set(draft) != set(expected) or any(
        draft[key] != expected[key] for key in expected if key not in {"created_at", "changes"}
    ):
        raise ValueError("STALE_OR_FORGED_OVERRIDE")
    if out is not None and out.exists() and any(out.iterdir()):
        raise ValueError("OVERRIDE_OUTPUT_MUST_BE_NEW")
    record = deepcopy(draft)
    record["id"] = digest("interpretation-override.v1", record)
    _validate_record(record)
    result: dict[str, Any] = deepcopy(bundle)
    result.pop("revision_plan", None)
    result["interpretation_overrides"] = [*result.get("interpretation_overrides", []), record]
    result["interpreted_ir"] = interpreted_document(result)
    assertions, graph, overlay = _derive(result)
    from .paper_evidence import analyze_formalizations

    formal = analyze_formalizations(
        result["interpreted_ir"],
        assertions,
        execution_profile=None,
        controller_key=None,
        controller_id="interpretation-only",
        trust_store=None,
        evaluation_time=None,
        required=False,
    )
    result.update(
        assertions=assertions,
        argument_map=graph.to_dict(),
        semantic_overlay=overlay,
        formalizations=formal["formalizations"],
        execution_events=[],
        acceptance_records=[],
        assessment_records=formal.get("assessment_records", []),
        stage_manifests=[],
    )
    from .semantic_candidates import check_candidate_fidelity

    if "candidate_fidelity" in result:
        result["candidate_fidelity"] = check_candidate_fidelity(
            result["interpreted_ir"], overlay.get("candidates", []), None
        )
    result["findings"] = [
        *bundle["document_ir"]["findings"],
        *formal["findings"],
        {
            "code": "INTERPRETATION_OVERRIDE_APPLIED",
            "detail": "Attributed interpretation recomputed; current evidence and fidelity decisions require fresh evaluation.",
            "classification": "REVIEW_REQUIRED",
            "blocking_eligible": False,
        },
    ]
    from .paper_checkers import make_result

    source_ids = [row["id"] for row in result["document_ir"]["elements"]]
    result["assessment"]["checkers"] = [
        make_result(
            "source-integrity",
            "PASS",
            revision=result["input_manifest"]["revision"],
            source_ids=source_ids,
        ),
        make_result(
            "interpretation-recomputation",
            "PASS",
            revision=result["input_manifest"]["revision"],
            source_ids=source_ids,
            configuration={"override": record["id"]},
        ),
        make_result(
            "formal",
            "NOT_RUN",
            revision=result["input_manifest"]["revision"],
            source_ids=[row["id"] for row in assertions],
        ),
    ]
    result["assessment"]["closure"] = closure(graph, policy="paper-assertion-v1").to_dict()
    result["assessment"]["missing_required_stages"] = ["current-execution-and-fidelity"]
    outcomes = result["assessment"]["outcomes"]
    outcomes.update(
        pipeline_execution="PARTIAL",
        computational="NOT_RUN",
        formal_compilation="NOT_RUN",
        kernel_verification="NOT_RUN",
        formal_statement_fidelity="NOT_REVIEWED",
        scholarly_acceptance="NOT_ASSESSED",
    )
    for name in ("current_policy_assessment", "authority_evaluation_time"):
        outcomes.pop(name, None)
    outcomes["coverage"].update(
        authored_assertions=len(assertions),
        theorem_like_claims=len(formal["formalizations"]),
        supported_formal_obligations=formal["supported"],
        kernel_verified=0,
        kernel_verified_fraction=0.0 if formal["formalizations"] else None,
        reviewed_claims=0,
        accepted_claims=0,
    )
    run = result["run_manifest"]
    run.pop("analysis_context", None)
    run.update(
        run_id=str(uuid4()),
        parent_run_id=bundle["run_manifest"]["run_id"],
        analysis_digest=digest(
            "paper-interpretation-analysis.v1",
            {"base": record["analysis_digest"], "override": record["id"]},
        ),
        duration_seconds=0.0,
        exit_code=0,
        cache_provenance={
            "reused_stages": [],
            "resume_requested": False,
            "namespace": "interpretation-recomputation",
        },
    )
    from .paper_actions import plan_paper_actions

    result["action_plan"] = plan_paper_actions(result)
    run["bundle_digests"] = {
        name: digest("paper-bundle-component.v1", value)
        for name, value in result.items()
        if name != "run_manifest"
    }
    result = strict_loads(canonical_bytes(result))
    validate_override_bundle(result)
    papers = [
        row["paper"] for row in store.list() if row["run"] == bundle["run_manifest"]["run_id"]
    ]
    artifacts = {name: store.get(sha) for name, sha in indexed["artifacts"].items()}
    store.ingest(papers[0], result, artifacts)
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        for name, value in result.items():
            write_json(out / (name + ".json"), value)
        from .paper_reports import write_reports

        write_reports(result, out, artifacts)
    return result
