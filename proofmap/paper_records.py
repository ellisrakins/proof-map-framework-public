"""Versioned paper table contracts and exact projections of source records.

Historical v1 bundles may omit fields the producer did not measure. New runs
declare record_contract_version=1.0 and must include the complete source tables;
legacy compatibility never permits forged records or inferred acceptance.
"""

from __future__ import annotations

from typing import Any

from .integrity import ValidationIssue, canonical_bytes, digest, strict_loads
from .schema import schema, validate


def _validate_initial_acceptances(
    bundle: dict[str, Any], *, allow_missing_dimensions: bool = False
) -> None:
    """Check cached projections, without authenticating their claimed authority."""
    from .evidence_adapter import POLICY, assessment_records
    from .evidence_records import AcceptanceRecord, FormalizationBinding

    rows = {
        row["binding"]["id"]: row for row in bundle.get("formalizations", []) if "binding" in row
    }
    events = {
        result["event"]["id"]: result["event"] for result in bundle.get("execution_events", [])
    }
    if len(events) != len(bundle.get("execution_events", [])):
        raise ValueError("DUPLICATE_EXECUTION_EVENT")
    expected_dimensions = []
    for value in bundle.get("acceptance_records", []):
        acceptance = AcceptanceRecord.from_dict(value)
        row = rows.get(acceptance.binding_digest)
        if row is None:
            raise ValueError("ACCEPTANCE_BINDING_MISMATCH")
        binding = FormalizationBinding.from_dict(row["binding"])
        if any(
            value[key] != getattr(binding, key)
            for key in ("revision_id", "assertion_id", "obligation_digest")
        ):
            raise ValueError("ACCEPTANCE_SUBJECT_BINDING")
        if acceptance.policy_digest != digest("acceptance-policy.v1", POLICY):
            raise ValueError("ACCEPTANCE_POLICY_BINDING")
        if (
            acceptance.review_digests
            or acceptance.source_fidelity != "NOT_REVIEWED"
            or acceptance.formal_fidelity != "NOT_REVIEWED"
        ):
            raise ValueError("SOURCE_RUN_CANNOT_INVENT_FIDELITY")
        if acceptance.execution_digest is not None:
            if "historical_execution" in row:
                event = row["historical_execution"]["execution"]["event"]
            else:
                event = events.get(row.get("execution_event"))
            if (
                event is None
                or event["id"] != acceptance.execution_digest
                or event["outcome"] != "VERIFIED"
                or event["profile_digest"] != acceptance.profile_digest
            ):
                raise ValueError("ACCEPTANCE_EXECUTION_BINDING")
        expected_dimensions.extend(assessment_records(acceptance, binding))
    if (not allow_missing_dimensions or "assessment_records" in bundle) and canonical_bytes(
        bundle.get("assessment_records", [])
    ) != canonical_bytes(expected_dimensions):
        raise ValueError("ASSESSMENT_DIMENSION_PROJECTION")


def _validate_summary(bundle: dict[str, Any], *, legacy: bool = False) -> None:
    from copy import deepcopy

    from jsonschema import Draft202012Validator

    from .kernel import KernelMap, closure
    from .paper_checkers import required_failures, validate_result

    summary = strict_loads(canonical_bytes(bundle["assessment"]))
    if not isinstance(summary, dict):
        raise ValueError("PIPELINE_ASSESSMENT_SCHEMA")
    if legacy:
        # Older records may omit measurements, never invent them. Check every
        # field they do supply against the same typed contract and projections.
        summary_schema = deepcopy(schema("pipeline-assessment"))
        summary_schema.pop("required")
        summary_schema["properties"]["outcomes"].pop("required")
        summary_schema["properties"]["outcomes"]["properties"]["coverage"].pop("required")
        summary_schema["properties"]["checkers"] = {"type": "array"}
        if list(Draft202012Validator(summary_schema).iter_errors(summary)):
            raise ValueError("PIPELINE_ASSESSMENT_SCHEMA")
    elif validate("pipeline-assessment", summary):
        raise ValueError("PIPELINE_ASSESSMENT_SCHEMA")
    if (
        "policy" in summary
        and digest("paper-policy.v1", summary["policy"]) != bundle["run_manifest"]["policy_digest"]
    ):
        raise ValueError("PIPELINE_ASSESSMENT_POLICY")
    graph = KernelMap.from_dict(bundle["argument_map"])
    expected_closure = closure(graph, policy="paper-assertion-v1").to_dict()
    if "closure" in summary and canonical_bytes(summary["closure"]) != canonical_bytes(
        expected_closure
    ):
        raise ValueError("PIPELINE_ASSESSMENT_CLOSURE")
    outcomes = summary.get("outcomes", {})
    rows = bundle.get("formalizations", [])
    acceptances = bundle.get("acceptance_records", [])
    _validate_initial_acceptances(bundle, allow_missing_dimensions=legacy)
    if len({row["binding_digest"] for row in acceptances}) != len(acceptances):
        raise ValueError("DUPLICATE_INITIAL_ACCEPTANCE")
    if any(
        row["review_digests"] or row["assessment"] == "ACCEPTED_UNDER_POLICY" for row in acceptances
    ):
        raise ValueError("SOURCE_RUN_CANNOT_INVENT_FIDELITY")
    verified = sum(row["formal_status"] == "VERIFIED" for row in acceptances)
    expected_counts = {
        "authored_assertions": len(bundle["assertions"]),
        "theorem_like_claims": len(rows),
        "supported_formal_obligations": sum(row["status"] == "SUPPORTED" for row in rows),
        "kernel_verified": verified,
        "kernel_verified_fraction": verified / len(rows) if rows else None,
        "reviewed_claims": 0,
        "accepted_claims": 0,
    }
    if (
        any(value != expected_counts[key] for key, value in outcomes.get("coverage", {}).items())
        or verified > expected_counts["supported_formal_obligations"]
    ):
        raise ValueError("PIPELINE_ASSESSMENT_COUNTS")
    checkers = {row["checker"]: row for row in summary.get("checkers", [])}
    if len(checkers) != len(summary.get("checkers", [])):
        raise ValueError("DUPLICATE_ASSESSMENT_CHECKER")
    for checker in checkers.values():
        if legacy and "schema_version" not in checker:
            if (
                set(checker) != {"checker", "execution_status", "findings"}
                or not isinstance(checker["checker"], str)
                or checker["execution_status"]
                not in {
                    "PASS",
                    "PARTIAL",
                    "FAIL",
                    "ERROR",
                    "TIMEOUT",
                    "UNAVAILABLE",
                    "NOT_RUN",
                    "NOT_APPLICABLE",
                }
                or not isinstance(checker["findings"], list)
            ):
                raise ValueError("LEGACY_CHECKER_SCHEMA")
        else:
            validate_result(checker)
    for checker, outcome in (("formal", "formal_compilation"), ("exact", "computational")):
        if (
            checker in checkers
            and outcome in outcomes
            and outcomes[outcome] != checkers[checker]["execution_status"]
        ):
            raise ValueError("PIPELINE_ASSESSMENT_CHECKER_OUTCOME")
    expected_kernel = (
        "PASS" if verified else "NOT_RUN" if not bundle.get("execution_events") else "NOT_VERIFIED"
    )
    if "kernel_verification" in outcomes and outcomes["kernel_verification"] != expected_kernel:
        raise ValueError("PIPELINE_ASSESSMENT_KERNEL_STATUS")
    if (
        "extraction_quality" in outcomes
        and outcomes["extraction_quality"] != bundle["document_ir"]["status"]
    ):
        raise ValueError("PIPELINE_ASSESSMENT_EXTRACTION")
    context = bundle["run_manifest"].get("analysis_context")
    if context is not None:
        required = list(
            context["config"].get("required_stages", ["source-integrity", "source-structure"])
        )
        if context["require_formal"] and "formal" not in required:
            required.append("formal")
        missing = required_failures(
            summary.get("checkers", []),
            required,
            allow_partial={"source-structure", "dependency-context", "citation-local"}
            & set(required),
        )
        if "missing_required_stages" in summary and summary["missing_required_stages"] != missing:
            raise ValueError("PIPELINE_ASSESSMENT_REQUIRED_STAGES")
        infrastructure = bundle["document_ir"]["parser"].get("execution") in {
            "TIMEOUT",
            "ERROR",
            "UNAVAILABLE",
        }
        infrastructure = (
            infrastructure
            or checkers.get("model-extraction", {}).get("execution_status") == "ERROR"
        )
        infrastructure = infrastructure or (
            checkers.get("formal", {}).get("execution_status")
            in {"UNAVAILABLE", "ERROR", "TIMEOUT"}
            and (
                context["require_formal"]
                or context["execution_profile"] is not None
                or "formal" in required
            )
        )
        expected_pipeline = "ERROR" if infrastructure else "FAIL" if missing else "PASS"
        if "pipeline_execution" in outcomes and outcomes["pipeline_execution"] != expected_pipeline:
            raise ValueError("PIPELINE_ASSESSMENT_STATUS")
    exit_codes = {"PASS": 0, "FAIL": 1, "ERROR": 3, "PARTIAL": 0}
    if (
        "exit_code" in bundle["run_manifest"]
        and "pipeline_execution" in outcomes
        and bundle["run_manifest"]["exit_code"] != exit_codes[outcomes["pipeline_execution"]]
    ):
        raise ValueError("PIPELINE_ASSESSMENT_EXIT")


def validate_paper_records(bundle: dict[str, Any]) -> None:
    projected = {
        name: bundle[name] for name in ("run_manifest", "assertions", "symbols", "findings")
    }
    projected["schema_version"] = "1.0"
    issues = validate("paper-records", projected)
    if issues:
        raise ValueError("PAPER_RECORD_SCHEMA: " + issues[0].path + ": " + issues[0].message)
    context = bundle["run_manifest"].get("analysis_context")
    if context is not None:
        from .evidence_records import VerifierProfile
        from .extractor import validate_config

        if digest("paper-policy.v1", context["policy"]) != bundle["run_manifest"]["policy_digest"]:
            raise ValueError("RUN_POLICY_BINDING")
        if context["execution_profile"] is not None:
            VerifierProfile.from_dict(context["execution_profile"])
        configured = context["config"].get("extractor")
        if configured is not None:
            try:
                validate_config(configured)
            except ValueError:
                # Failed attempts retain raw input for diagnosis. This exception
                # never admits an extracted event or a successful checker result.
                diagnostic_only = (
                    context["extractor_mode"] in {"configured", "replay"}
                    and not bundle.get("extraction_events")
                    and any(
                        row.get("checker") == "model-extraction"
                        and row.get("execution_status") == "ERROR"
                        for row in bundle["assessment"].get("checkers", [])
                    )
                    and any(row.get("code") == "EXTRACTOR_ERROR" for row in bundle["findings"])
                )
                if not diagnostic_only:
                    raise
        fidelity_config = context.get("candidate_fidelity_config")
        if fidelity_config is not None:
            validate_config(fidelity_config)
    raw = bundle["document_ir"]
    ir = bundle.get("interpreted_ir", raw)
    elements = {row["id"]: row for row in ir["elements"]}
    seen = set()
    for assertion in bundle["assertions"]:
        source = elements.get(assertion["id"])
        if source is None or source["kind"] != "ASSERTION" or assertion["id"] in seen:
            raise ValueError("ASSERTION_RECORD_SUBJECT")
        seen.add(assertion["id"])
        if any(
            assertion[key] != source.get(key, "UNRESOLVED")
            for key in ("scope", "role")
            if key in assertion
        ):
            raise ValueError("ASSERTION_RECORD_CONTEXT")
        if "assessment" in assertion and assertion["assessment"]["subject"] != assertion["id"]:
            raise ValueError("ASSERTION_ASSESSMENT_SUBJECT")
        if "proof_ids" in assertion:
            expected = [
                row["id"]
                for row in ir["elements"]
                if row["kind"] == "PROOF" and row.get("proof_for") == assertion["id"]
            ]
            if sorted(assertion["proof_ids"]) != sorted(expected):
                raise ValueError("ASSERTION_PROOF_ASSOCIATION")
        if "source_context" in assertion and assertion["source_context"] != [
            row for row in ir.get("mathematical_context", []) if row["owner"] == assertion["id"]
        ]:
            raise ValueError("ASSERTION_SOURCE_CONTEXT")
    symbols = {row["id"]: row for row in bundle["symbols"]}
    expected_symbols = {
        row["id"]: row
        for row in raw["elements"]
        if row["kind"] in {"SYMBOL_OCCURRENCE", "MACRO_DEFINITION", "MATH_EXPRESSION"}
    }
    if len(symbols) != len(bundle["symbols"]) or any(
        ident not in expected_symbols
        or canonical_bytes(row) != canonical_bytes(expected_symbols[ident])
        for ident, row in symbols.items()
    ):
        raise ValueError("SYMBOL_SOURCE_PROJECTION")
    if bundle["run_manifest"].get("record_contract_version") == "1.0":
        if (
            not {"duration_seconds", "exit_code", "cache_provenance"}
            <= bundle["run_manifest"].keys()
        ):
            raise ValueError("RUN_RECORD_INCOMPLETE")
        if context is None:
            if not bundle.get("interpretation_overrides"):
                raise ValueError("RUN_CONTEXT_MISSING")
            if bundle["assessment"]["outcomes"]["pipeline_execution"] != "PARTIAL" or bundle[
                "assessment"
            ]["missing_required_stages"] != ["current-execution-and-fidelity"]:
                raise ValueError("INTERPRETATION_REQUIRES_CURRENT_EVIDENCE")
        if context is not None and "extractor_contract" not in context:
            raise ValueError("RUN_EXTRACTOR_CONTRACT_MISSING")
        if set(symbols) != set(expected_symbols) or seen != {
            row["id"] for row in ir["elements"] if row["kind"] == "ASSERTION"
        }:
            raise ValueError("PAPER_RECORD_TABLE_INCOMPLETE")
        required = {
            "status",
            "role",
            "hypotheses",
            "quantifiers",
            "conclusion",
            "proof_ids",
            "fidelity",
            "formal_obligation_digest",
            "assessment",
            "source_context",
        }
        if any(not required <= row.keys() for row in bundle["assertions"]):
            raise ValueError("ASSERTION_RECORD_INCOMPLETE")
    # A producer/version marker is untrusted input. Removing it must never
    # disable the authority projections of any fields still present.
    _validate_summary(
        bundle,
        legacy=bundle["run_manifest"].get("record_contract_version") != "1.0"
        and "schema_version" not in bundle["assessment"],
    )
    for finding in bundle["findings"]:
        if "certificate_digest" in finding:
            content = {key: value for key, value in finding.items() if key != "certificate_digest"}
            if finding["certificate_digest"] != digest("exact-check.v1", content):
                raise ValueError("FINDING_CERTIFICATE_BINDING")


def paper_record_issues(bundle: dict[str, Any]) -> list[ValidationIssue]:
    try:
        validate_paper_records(bundle)
    except (ValueError, KeyError, TypeError) as exc:
        return [ValidationIssue(str(exc).split(":", 1)[0], "/paper-records", str(exc))]
    return []
