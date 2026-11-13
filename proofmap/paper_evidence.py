"""Connect paper subjects to isolated execution; authority always comes from callers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .attempts import FormalObligation
from .evidence_records import FormalizationBinding, VerifierProfile
from .formalize import formalize_document
from .integrity import digest


def preflight(profile: dict[str, Any] | None) -> dict[str, Any]:
    import shutil
    import subprocess

    if profile is None:
        return {
            "execution": "UNAVAILABLE",
            "reason": "An external prepared verifier profile is required",
            "host_fallback": False,
        }
    validated = VerifierProfile.from_dict(profile)
    if shutil.which("docker") is None:
        return {
            "execution": "UNAVAILABLE",
            "reason": "Docker is not installed",
            "profile": validated.digest,
            "host_fallback": False,
        }
    try:
        probe = subprocess.run(
            ["docker", "image", "inspect", validated.image, "--format", "{{.Os}}"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {
            "execution": "UNAVAILABLE",
            "reason": "Docker image inspection failed",
            "host_fallback": False,
        }
    available = probe.returncode == 0 and probe.stdout.strip() == b"linux"
    return {
        "execution": "READY" if available else "UNAVAILABLE",
        "profile": validated.digest,
        "reason": "Image acquired; material validation occurs during every execution"
        if available
        else "Pinned Linux image is not acquired locally",
        "host_fallback": False,
    }


def analyze_formalizations(
    ir: dict[str, Any],
    assertions: list[dict[str, Any]],
    *,
    execution_profile: dict[str, Any] | None,
    controller_key: bytes | None,
    controller_id: str,
    trust_store: dict[str, Any] | None,
    evaluation_time: str | None,
    required: bool,
    candidate_overrides: dict[str, bytes] | None = None,
    prepared_rows: list[dict[str, Any]] | None = None,
    historical_candidates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .execution import execute, render_wrapper

    rows = deepcopy(prepared_rows) if prepared_rows is not None else formalize_document(ir)
    if {row["assertion_id"] for row in rows} != {row["id"] for row in assertions} or len(
        rows
    ) != len(assertions):
        raise ValueError("FORMALIZATION_PREPARED_SUBJECTS")
    if set(candidate_overrides or {}) - {
        r["assertion_id"] for r in rows if r["status"] == "SUPPORTED"
    }:
        raise ValueError("CANDIDATE_OVERRIDE_REQUIRES_EXACT_SUPPORTED_SOURCE_ID")
    by_id = {a["id"]: a for a in assertions}
    events: list[dict[str, Any]] = []
    acceptances: list[dict[str, Any]] = []
    assessments: list[dict[str, Any]] = []
    findings = []
    supported = 0
    verified = 0
    profile = VerifierProfile.from_dict(execution_profile) if execution_profile else None
    outcomes = []
    for row in rows:
        if row["status"] != "SUPPORTED":
            findings.append(
                {
                    "code": "FORMALIZATION_UNSUPPORTED",
                    "source": row["assertion_id"],
                    "detail": row["reason"],
                    "blocking_eligible": False,
                }
            )
            continue
        supported += 1
        obligation = FormalObligation.from_dict(row["obligation"])
        if row["assertion_id"] in (candidate_overrides or {}):
            candidate = (candidate_overrides or {})[row["assertion_id"]]
            render_wrapper(obligation, candidate)
            row["candidate"] = candidate.decode("utf-8")
            row["candidate_method"] = "AUTHOR_SUPPLIED_APPROVED_PROGRAM"
        binding = FormalizationBinding.create(
            revision_id=ir["revision"],
            assertion_id=row["assertion_id"],
            assertion_digest=digest("assertion.v1", by_id[row["assertion_id"]]),
            source_locators=row["source_locators"],
            context_digest=row["context_digest"],
            definition_digest=row["definition_digest"],
            obligation=obligation,
            candidate=row["candidate"].encode("utf-8"),
            method=row["method"],
        )
        row["binding"] = binding.to_dict()
        if not row["exact_check"]["equal"]:
            findings.append(
                {
                    "code": "CANDIDATE_EXACT_CONTRADICTION",
                    "source": row["assertion_id"],
                    "detail": "Parsed integer polynomial coefficients disagree; source fidelity is unreviewed.",
                    "blocking_eligible": False,
                }
            )
        if profile is None:
            continue
        history = (historical_candidates or {}).get(row["assertion_id"])
        if history is not None and trust_store is not None and evaluation_time is not None:
            from .evidence_adapter import assess_binding, resolve_reused_execution

            resolution = resolve_reused_execution(
                history,
                trust_store,
                binding,
                obligation,
                profile,
                evaluation_time=evaluation_time,
            )
            row["historical_execution"] = deepcopy(history)
            row["resolution"] = resolution
            verified += int(resolution["formal_verified"])
            outcomes.append("VERIFIED" if resolution["formal_verified"] else "UNTRUSTED")
            acceptances.append(
                assess_binding(
                    binding,
                    obligation,
                    profile,
                    None,
                    [],
                    trust_store,
                    evaluation_time=evaluation_time,
                    historical_execution=history,
                ).to_dict()
            )
            if not resolution["formal_verified"]:
                findings.append(
                    {
                        "code": "HISTORICAL_EXECUTION_NOT_CURRENTLY_TRUSTED",
                        "source": row["assertion_id"],
                        "detail": resolution["reason"],
                        "blocking_eligible": False,
                    }
                )
            continue
        result = execute(
            binding,
            obligation,
            row["candidate"].encode("utf-8"),
            profile,
            controller_id=controller_id,
            private_key=controller_key,
        )
        events.append(result)
        outcomes.append(result["event"]["outcome"])
        row["execution_event"] = result["event"]["id"]
        if (
            result.get("envelope") is not None
            and trust_store is not None
            and evaluation_time is not None
        ):
            from .evidence_adapter import assess_binding, resolve_execution

            resolution = resolve_execution(
                result["envelope"],
                trust_store,
                binding,
                obligation,
                profile,
                evaluation_time=evaluation_time,
            )
            row["resolution"] = resolution
            verified += int(resolution.get("accepted", False))
            if result["event"]["outcome"] == "VERIFIED" and not resolution.get("accepted", False):
                outcomes[-1] = "UNTRUSTED"
            acceptances.append(
                assess_binding(
                    binding,
                    obligation,
                    profile,
                    result["envelope"],
                    [],
                    trust_store,
                    evaluation_time=evaluation_time,
                ).to_dict()
            )
    if profile is None:
        status = "UNAVAILABLE" if required else "NOT_RUN"
    elif not supported:
        status = "NOT_APPLICABLE"
    elif any(
        outcome in {"UNAVAILABLE", "TIMEOUT", "ERROR", "VERIFIER_ERROR"} for outcome in outcomes
    ):
        status = next(
            outcome
            for outcome in outcomes
            if outcome in {"UNAVAILABLE", "TIMEOUT", "ERROR", "VERIFIER_ERROR"}
        )
        status = "ERROR" if status == "VERIFIER_ERROR" else status
    elif all(outcome == "VERIFIED" for outcome in outcomes):
        status = "PASS" if supported == len(rows) else "PARTIAL"
    else:
        status = "FAIL"
    if status == "UNAVAILABLE":
        findings.append(
            {
                "code": "FORMAL_INFRASTRUCTURE_UNAVAILABLE",
                "detail": "Select an externally prepared pinned Lean/Std profile and a working Linux Docker runtime; no host fallback is permitted.",
                "blocking_eligible": False,
            }
        )
    from .evidence_adapter import assessment_records
    from .evidence_records import AcceptanceRecord

    bound_rows = {row["binding"]["id"]: row for row in rows if "binding" in row}
    for acceptance in acceptances:
        assessments.extend(
            assessment_records(
                AcceptanceRecord.from_dict(acceptance),
                FormalizationBinding.from_dict(bound_rows[acceptance["binding_digest"]]["binding"]),
            )
        )
    return {
        "formalizations": rows,
        "execution_events": events,
        "acceptance_records": acceptances,
        "assessment_records": assessments,
        "findings": findings,
        "status": status,
        "supported": supported,
        "verified": verified,
    }


def fidelity_draft(
    bundle: dict[str, Any], assertion: str, profile: dict[str, Any], dimension: str, reviewer: str
) -> dict[str, Any]:
    selected = next(
        (
            row
            for row in bundle["formalizations"]
            if row["assertion_id"] == assertion and row["status"] == "SUPPORTED"
        ),
        None,
    )
    if selected is None:
        raise ValueError("REVIEW_REQUIRES_EXACT_SUPPORTED_FORMALIZATION")
    VerifierProfile.from_dict(profile)
    return {
        "binding": selected["binding"],
        "profile": profile,
        "dimension": dimension,
        "decision": None,
        "reviewer_id": reviewer,
        "method": "human-review-v1",
        "supersedes": None,
    }


def sign_fidelity_draft(draft: dict[str, Any], key: bytes) -> dict[str, Any]:
    from .evidence_records import ReviewDecision
    from .trust import sign_record

    if set(draft) != {
        "binding",
        "profile",
        "dimension",
        "decision",
        "reviewer_id",
        "method",
        "supersedes",
    }:
        raise ValueError("REVIEW_DRAFT_FIELDS")
    if draft["decision"] not in {"APPROVE", "REJECT"}:
        raise ValueError("REVIEW_REQUIRES_EXPLICIT_APPROVE_OR_REJECT")
    review = ReviewDecision.create(
        binding=FormalizationBinding.from_dict(draft["binding"]),
        profile=VerifierProfile.from_dict(draft["profile"]),
        dimension=draft["dimension"],
        decision=draft["decision"],
        reviewer_id=draft["reviewer_id"],
        method=draft["method"],
        supersedes=draft["supersedes"],
    )
    return sign_record(review.to_dict(), key, draft["reviewer_id"])


def reassess(
    bundle: dict[str, Any],
    store: Any,
    profile: dict[str, Any],
    trust_store: dict[str, Any],
    evaluation_time: str,
) -> dict[str, Any]:
    from .evidence_adapter import POLICY, assess_binding, assessment_records
    from .integrity import canonical_bytes

    run_id = bundle["run_manifest"]["run_id"]
    if canonical_bytes(store.inspect(run_id)["bundle"]) != canonical_bytes(bundle):
        raise ValueError("Assessment bundle differs from immutable indexed run")
    verified_profile = VerifierProfile.from_dict(profile)
    events = {row["event"]["id"]: row for row in bundle["execution_events"]}
    reviews = store.list_audit(run_id, "ReviewDecision")
    records = []
    dimensions = []
    audits = []
    for row in bundle["formalizations"]:
        if row["status"] != "SUPPORTED":
            continue
        binding = FormalizationBinding.from_dict(row["binding"])
        envelope = events.get(row.get("execution_event", ""), {}).get("envelope")
        relevant = [
            r["envelope"]
            for r in reviews
            if r["record"]["binding_digest"] == binding.digest and r["envelope"] is not None
        ]
        acceptance = assess_binding(
            binding,
            FormalObligation.from_dict(row["obligation"]),
            verified_profile,
            envelope,
            relevant,
            trust_store,
            evaluation_time=evaluation_time,
            historical_execution=row.get("historical_execution"),
        )
        record = acceptance.to_dict()
        audits.append({"record": record, "envelope": None})
        for dimension in assessment_records(acceptance, binding):
            audits.append({"record": dimension, "envelope": None})
            dimensions.append(dimension)
        records.append(record)
    store.add_audits(run_id, audits)
    return {
        "policy": POLICY,
        "run_id": run_id,
        "revision": bundle["input_manifest"]["revision"],
        "evaluation_time": evaluation_time,
        "records": records,
        "assessment_records": dimensions,
        "counts": {
            "ingested": len(bundle["assertions"]),
            "formalized": len(records),
            "verified": sum(r["formal_status"] == "VERIFIED" for r in records),
            "reviewed": sum(bool(r["review_digests"]) for r in records),
            "accepted": sum(r["assessment"] == "ACCEPTED_UNDER_POLICY" for r in records),
        },
    }


def apply_fidelity(
    bundle: dict[str, Any],
    envelope: dict[str, Any],
    store: Any,
    profile: dict[str, Any],
    trust_store: dict[str, Any],
    evaluation_time: str,
) -> dict[str, Any]:
    from .evidence_records import ReviewDecision
    from .trust import authenticated_record, verify_record

    review = ReviewDecision.from_dict(authenticated_record(envelope))
    verified_profile = VerifierProfile.from_dict(profile)
    verify_record(
        envelope,
        trust_store,
        role=review.dimension + "-review",
        subject=review.assertion_id,
        profile_digest=verified_profile.digest,
        evaluation_time=evaluation_time,
    )
    if not any(
        row.get("binding", {}).get("id") == review.binding_digest
        for row in bundle["formalizations"]
    ):
        raise ValueError("STALE_REVIEW_BINDING")
    store.add_audit(
        bundle["run_manifest"]["run_id"], {"record": review.to_dict(), "envelope": envelope}
    )
    return reassess(bundle, store, profile, trust_store, evaluation_time)


def report_assessment(
    bundle: dict[str, Any], current: dict[str, Any], store: Any, out: Any
) -> None:
    """Render a derived current view while leaving the original run immutable."""
    from copy import deepcopy

    from .integrity import write_json
    from .paper import render

    view = deepcopy(bundle)
    records = {r["assertion_id"]: r for r in current["records"]}
    review_ids = {digest for record in records.values() for digest in record["review_digests"]}
    reviews = [
        row["record"]
        for row in store.list_audit(bundle["run_manifest"]["run_id"], "ReviewDecision")
        if row["record"]["id"] in review_ids
    ]
    for row in view["formalizations"]:
        row["current_assessment"] = records.get(row["assertion_id"])
        row["review_decisions"] = [
            review for review in reviews if review["assertion_id"] == row["assertion_id"]
        ]
    outcomes = view["assessment"]["outcomes"]
    outcomes["coverage"]["reviewed_claims"] = current["counts"]["reviewed"]
    outcomes["coverage"]["accepted_claims"] = current["counts"]["accepted"]
    outcomes["coverage"]["kernel_verified"] = current["counts"]["verified"]
    selected = outcomes["coverage"]["theorem_like_claims"]
    outcomes["coverage"]["kernel_verified_fraction"] = (
        current["counts"]["verified"] / selected if selected else None
    )
    outcomes["kernel_verification"] = (
        "PASS"
        if current["counts"]["verified"]
        else "NOT_VERIFIED"
        if bundle["execution_events"]
        else "NOT_RUN"
    )
    outcomes["formal_statement_fidelity"] = {
        r["assertion_id"]: r["formal_fidelity"] for r in current["records"]
    }
    outcomes["current_policy_assessment"] = {
        r["assertion_id"]: r["assessment"] for r in current["records"]
    }
    outcomes["authority_evaluation_time"] = current["evaluation_time"]
    stored = store.inspect(bundle["run_manifest"]["run_id"])
    artifacts = {name: store.get(sha) for name, sha in stored["artifacts"].items()}
    out.mkdir(parents=True, exist_ok=True)
    write_json(
        out / "current-assessment.json",
        {**current, "outcomes": outcomes, "review_decisions": reviews},
    )
    render(view, out, artifacts)
