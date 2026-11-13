"""One authenticated boundary into kernel trusted_evidence and paper assessments."""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping

from .attempts import FormalObligation, parse_lean_axioms
from .evidence_records import (
    AcceptanceRecord,
    AssessmentRecord,
    ExecutionEvent,
    FormalizationBinding,
    ReviewDecision,
    VerifierProfile,
    obligation_identity,
)
from .integrity import artifact_digest, digest, strict_loads
from .kernel import (
    DIMENSIONS,
    POLICIES,
    Claim,
    Context,
    EvidenceArtifact,
    Inference,
    KernelMap,
    VerificationEvent,
    closure,
)
from .trust import authenticated_record, verify_record

POLICY = {
    "id": "paper-reviewed-lean-v1",
    "kernel_policy": "deductive-strict-v1",
    "required_reviews": ["source-fidelity", "formal-fidelity"],
    "verification_profile": "lean-std-int-polynomial-v1",
}


def assessment_records(
    acceptance: AcceptanceRecord, binding: FormalizationBinding
) -> list[dict[str, Any]]:
    """Emit independent, provenance-bearing dimensions from policy evaluation.

    These local derived records identify the evaluator; authenticated execution
    and reviewer identities remain in their referenced immutable records. The
    evaluator is not presented as a signed human reviewer. Unmeasured dimensions
    stay NOT_ASSESSED and never inherit the formal encoding's verified status.
    """
    acceptance = AcceptanceRecord.from_dict(acceptance.to_dict())
    binding = FormalizationBinding.from_dict(binding.to_dict())
    if acceptance.binding_digest != binding.digest:
        raise ValueError("ASSESSMENT_BINDING_MISMATCH")
    result = []
    for dimension in DIMENSIONS:
        status = "NOT_ASSESSED"
        evidence: list[str] = []
        reasons = ["This dimension was not measured by the paper acceptance policy."]
        formal = dimension == "deductive"
        if formal:
            status = "PASS" if acceptance.formal_status == "VERIFIED" else "UNAVAILABLE"
            if acceptance.execution_digest is not None:
                evidence = [acceptance.execution_digest]
            reasons = [] if status == "PASS" else list(acceptance.reasons)
        elif dimension in {"source_fidelity", "formal_fidelity"}:
            decision = getattr(acceptance, dimension)
            if decision != "NOT_REVIEWED":
                status = "PASS" if decision == "APPROVE" else "FAIL"
                evidence = list(acceptance.review_digests)
                reasons = (
                    []
                    if status == "PASS"
                    else ["A currently authenticated fidelity decision rejects this binding."]
                )
            else:
                reasons = [
                    "No unique currently authenticated fidelity decision authorizes this binding."
                ]
        record = AssessmentRecord.build(
            subject=("formal:" if formal else "") + binding.assertion_id,
            subject_kind="formal_encoding" if formal else "claim",
            subject_digest=binding.obligation_digest if formal else binding.assertion_digest,
            context_digest=binding.context_digest,
            dimension=dimension,
            status=status,
            policy_digest=acceptance.policy_digest,
            method="paper-policy-dimensions-v1",
            evidence_digests=evidence,
            actor_id="proofmap-policy-evaluator",
            authentication="NOT_CHECKED",
            authentication_digests=[],
            authority_digest=acceptance.trust_digest,
            evaluation_time=acceptance.evaluation_time,
            reasons=reasons,
        )
        result.append(record.to_dict())
    return result


def formal_graph(binding: FormalizationBinding, obligation: FormalObligation) -> KernelMap:
    if binding.obligation_digest != obligation_identity(obligation):
        raise ValueError("FORMAL_OBLIGATION_BINDING_MISMATCH")
    context = Context("formal-context:" + binding.context_digest, binding.definition_digest)
    claim = Claim(
        "formal:" + binding.assertion_id,
        obligation.statement,
        context.id,
        binding.obligation_digest,
        quantifiers=("encoded-in-statement:Int",),
    )
    inference = Inference("formal-inference:" + binding.assertion_id, claim.id, (), context.id)
    graph = KernelMap((claim,), (context,), (inference,))
    graph.validate()
    return graph


def _check_outputs(
    event: ExecutionEvent, profile: VerifierProfile, obligation: FormalObligation
) -> None:
    from . import execution
    from .integrity import canonical_bytes

    candidate = event.outputs["candidate_source"].encode("utf-8")
    wrapper = execution.render_wrapper(obligation, candidate).encode()
    snapshot = {
        "Candidate.lean": wrapper,
        "Recheck.lean": execution.render_wrapper(obligation, b"by grind").encode(),
        "worker.py": execution.WORKER,
        "request.json": canonical_bytes({"profile": profile.to_dict()}),
    }
    if (
        event.candidate_digest != artifact_digest(candidate)
        or event.wrapper_digest != artifact_digest(wrapper)
        or event.snapshot_digest
        != digest(
            "execution-snapshot.v1",
            {key: artifact_digest(value) for key, value in snapshot.items()},
        )
    ):
        raise ValueError("EXECUTION_REQUEST_MATERIAL_MISMATCH")

    if (
        event.controller_digest != artifact_digest(Path(execution.__file__).read_bytes())
        or profile.checker_digest != execution.CHECKER_DIGEST
    ):
        raise ValueError("EXECUTION_CHECKER_VERSION_MISMATCH")
    environment = event.environment
    actual = environment["actual"]
    if (
        not environment["complete"]
        or any(
            actual.get(k) != getattr(profile, k)
            for k in (
                "lean_sha256",
                "library_digest",
                "checker_digest",
                "platform",
                "executable",
                "search_path",
                "image",
            )
        )
        or "version 4.30.0," not in actual.get("version", "")
    ):
        raise ValueError("EXECUTION_ENVIRONMENT_MISMATCH")
    report = strict_loads(event.outputs["worker_stdout"])
    if report.get("outcome") != "CHECKED" or any(
        report["actual"].get(k) != v for k, v in actual.items() if k != "image"
    ):
        raise ValueError("EXECUTION_OUTPUT_ENVIRONMENT_MISMATCH")
    audited: set[str] = set()
    for name in ("Candidate", "Recheck"):
        result = report["results"][name]
        if type(result["returncode"]) is not int or result["returncode"] != 0:
            raise ValueError("EXECUTION_OUTPUT_CHECKER_FAILED")
        axioms = parse_lean_axioms(result["stdout"] + "\n" + result["stderr"], "proofmap_target")
        if axioms is None or set(axioms) - set(profile.axioms):
            raise ValueError("EXECUTION_AXIOM_AUDIT_FAILED")
        audited.update(axioms)
    if sorted(audited) != event.axioms:
        raise ValueError("EXECUTION_AXIOM_BINDING_MISMATCH")


def resolve_execution(
    envelope: Mapping[str, Any] | None,
    trust_store: Mapping[str, Any],
    binding: FormalizationBinding,
    obligation: FormalObligation,
    profile: VerifierProfile,
    *,
    evaluation_time: str,
) -> dict[str, Any]:
    """Return exact matching kernel evidence, or a structured fail-closed reason."""
    try:
        binding = FormalizationBinding.from_dict(binding.to_dict())
        profile = VerifierProfile.from_dict(profile.to_dict())
        if envelope is None:
            raise ValueError("EXECUTION_AUTHENTICATION_MISSING")
        verify_record(
            envelope,
            trust_store,
            role="verification-execution",
            subject=binding.assertion_id,
            profile_digest=profile.digest,
            evaluation_time=evaluation_time,
        )
        event = ExecutionEvent.from_dict(authenticated_record(envelope))
        if (
            event.binding_digest != binding.digest
            or event.revision_id != binding.revision_id
            or event.obligation_digest != obligation_identity(obligation)
            or event.obligation_digest != binding.obligation_digest
            or event.assertion_id != obligation.target_node_id
            or event.candidate_digest != binding.candidate_digest
        ):
            raise ValueError("EXECUTION_SUBJECT_BINDING_MISMATCH")
        if event.outcome != "VERIFIED":
            raise ValueError("EXECUTION_NOT_VERIFIED:" + event.outcome)
        _check_outputs(event, profile, obligation)
        graph = formal_graph(binding, obligation)
        inference = graph.inferences[0]
        artifact = EvidenceArtifact(
            "execution:" + event.digest,
            inference.id,
            graph.inference_digest(inference),
            inference.context,
            binding.definition_digest,
            POLICIES["deductive-strict-v1"].digest,
            "DEDUCTIVE",
            "PASS",
            event.digest,
        )
        graph = replace(
            graph, inferences=(replace(inference, evidence=(artifact.id,)),), evidence=(artifact,)
        )
        verified = VerificationEvent(
            "verification:" + event.digest,
            artifact.digest,
            "PASS",
            digest("approved-environment.v1", event.environment),
            (event.parent_event,) if event.parent_event else (),
        )
        result = closure(graph, trusted_evidence=(artifact.digest,))
        if graph.claims[0].id not in result.closed:
            raise ValueError("KERNEL_EVIDENCE_NOT_CLOSED")
        return {
            "accepted": True,
            "formal_verified": True,
            "reason": "AUTHENTICATED_FORMAL_ENCODING",
            "execution_digest": event.digest,
            "graph": graph.to_dict(),
            "artifact": asdict(artifact),
            "verification_event": asdict(verified),
            "trusted_evidence": [artifact.digest],
            "closure": result.to_dict(),
        }
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return {
            "accepted": False,
            "formal_verified": False,
            "reason": str(exc),
            "trusted_evidence": [],
            "execution_digest": None,
        }


def resolve_reused_execution(
    history: Mapping[str, Any],
    trust_store: Mapping[str, Any],
    binding: FormalizationBinding,
    obligation: FormalObligation,
    profile: VerifierProfile,
    *,
    evaluation_time: str,
) -> dict[str, Any]:
    """Reuse a historical formal fact, never an old source-fidelity decision.

    Exact executable theorem/program/profile bytes are compared independently
    of source IDs. The historical event stays immutable and is authenticated
    against its original subject under current revocation policy. New source
    and formal-fidelity reviews are still required for the current binding.
    """
    try:
        from .execution import render_wrapper

        if set(history) != {
            "parent_run_id",
            "parent_revision",
            "binding",
            "obligation",
            "execution",
        }:
            raise ValueError("HISTORICAL_EXECUTION_FIELDS")
        if (
            not isinstance(history["parent_run_id"], str)
            or not 0 < len(history["parent_run_id"]) <= 512
        ):
            raise ValueError("HISTORICAL_RUN_ID")
        previous = FormalizationBinding.from_dict(history["binding"])
        old_obligation = FormalObligation.from_dict(history["obligation"])
        binding = FormalizationBinding.from_dict(binding.to_dict())
        profile = VerifierProfile.from_dict(profile.to_dict())
        current = FormalObligation.from_dict(obligation.to_dict())
        if history["parent_revision"] != previous.revision_id:
            raise ValueError("HISTORICAL_REVISION_BINDING")
        if (
            binding.obligation_digest != obligation_identity(current)
            or binding.assertion_id != current.target_node_id
        ):
            raise ValueError("HISTORICAL_CURRENT_BINDING")
        execution = history["execution"]
        envelope = execution.get("envelope")
        resolved = resolve_execution(
            envelope,
            trust_store,
            previous,
            old_obligation,
            profile,
            evaluation_time=evaluation_time,
        )
        if not resolved["formal_verified"]:
            raise ValueError("HISTORICAL_AUTHORITY: " + resolved["reason"])
        event = ExecutionEvent.from_dict(authenticated_record(envelope))
        if event.to_dict() != execution["event"]:
            raise ValueError("HISTORICAL_EVENT_SUBSTITUTION")
        candidate = event.outputs["candidate_source"].encode("utf-8")
        material = ("statement", "toolchain", "formal_system", "imports", "allowed_axioms")
        if (
            any(getattr(current, key) != getattr(old_obligation, key) for key in material)
            or binding.candidate_digest != previous.candidate_digest
            or binding.candidate_digest != artifact_digest(candidate)
            or render_wrapper(current, candidate) != render_wrapper(old_obligation, candidate)
            or render_wrapper(current, b"by grind") != render_wrapper(old_obligation, b"by grind")
        ):
            raise ValueError("HISTORICAL_FORMAL_MATERIAL_CHANGED")
        graph = formal_graph(binding, current)
        inference = graph.inferences[0]
        artifact = EvidenceArtifact(
            "historical-execution:" + event.digest,
            inference.id,
            graph.inference_digest(inference),
            inference.context,
            binding.definition_digest,
            POLICIES["deductive-strict-v1"].digest,
            "DEDUCTIVE",
            "PASS",
            event.digest,
        )
        graph = replace(
            graph, inferences=(replace(inference, evidence=(artifact.id,)),), evidence=(artifact,)
        )
        result = closure(graph, trusted_evidence=(artifact.digest,))
        if graph.claims[0].id not in result.closed:
            raise ValueError("HISTORICAL_KERNEL_EVIDENCE_NOT_CLOSED")
        return {
            "accepted": True,
            "formal_verified": True,
            "reason": "AUTHENTICATED_HISTORICAL_FORMAL_ENCODING",
            "execution_digest": event.digest,
            "graph": graph.to_dict(),
            "artifact": asdict(artifact),
            "trusted_evidence": [artifact.digest],
            "closure": result.to_dict(),
            "historical": {
                "parent_run_id": history["parent_run_id"],
                "parent_revision": previous.revision_id,
                "binding_digest": previous.digest,
                "current_binding_digest": binding.digest,
            },
        }
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return {
            "accepted": False,
            "formal_verified": False,
            "reason": str(exc),
            "trusted_evidence": [],
            "execution_digest": None,
        }


def assess_binding(
    binding: FormalizationBinding,
    obligation: FormalObligation,
    profile: VerifierProfile,
    execution_envelope: Mapping[str, Any] | None,
    reviews: list[Mapping[str, Any]],
    trust_store: Mapping[str, Any],
    *,
    evaluation_time: str,
    historical_execution: Mapping[str, Any] | None = None,
) -> AcceptanceRecord:
    """Re-evaluate immutable evidence with current authority/revocation and reviews."""
    if historical_execution is not None and execution_envelope is not None:
        raise ValueError("AMBIGUOUS_CURRENT_AND_HISTORICAL_EXECUTION")
    resolved = (
        resolve_reused_execution(
            historical_execution,
            trust_store,
            binding,
            obligation,
            profile,
            evaluation_time=evaluation_time,
        )
        if historical_execution is not None
        else resolve_execution(
            execution_envelope,
            trust_store,
            binding,
            obligation,
            profile,
            evaluation_time=evaluation_time,
        )
    )
    reasons = [] if resolved["formal_verified"] else [resolved["reason"]]
    decisions: dict[str, list[ReviewDecision]] = {k: [] for k in POLICY["required_reviews"]}
    review_ids: list[str] = []
    invalid_review = False
    for envelope in reviews:
        try:
            # Unauthenticated dimension is used only for selecting the required
            # verifier; it never authorizes a decision.
            review = ReviewDecision.from_dict(authenticated_record(envelope))
            verify_record(
                envelope,
                trust_store,
                role=review.dimension + "-review",
                subject=binding.assertion_id,
                profile_digest=profile.digest,
                evaluation_time=evaluation_time,
            )
            if (
                review.binding_digest != binding.digest
                or review.revision_id != binding.revision_id
                or review.obligation_digest != binding.obligation_digest
            ):
                raise ValueError("REVIEW_BINDING_MISMATCH")
            decisions[review.dimension].append(review)
            review_ids.append(review.digest)
        except (ValueError, TypeError, KeyError) as exc:
            invalid_review = True
            reasons.append(str(exc))
    dimensions = {k: "NOT_REVIEWED" for k in decisions}
    for dimension, values in decisions.items():
        unique = {v.digest: v for v in values}
        superseded = {v.supersedes for v in unique.values() if v.supersedes}
        if any(x not in unique for x in superseded):
            reasons.append("UNKNOWN_REVIEW_SUPERSESSION")
            invalid_review = True
            continue
        current = [v for v in unique.values() if v.digest not in superseded]
        if len(current) == 1:
            dimensions[dimension] = current[0].decision
        elif current or unique:
            invalid_review = True
            reasons.append("CONFLICTING_OR_CYCLIC_REVIEW_DECISIONS")
    status = "UNVERIFIED"
    if "REJECT" in dimensions.values():
        status = "REJECTED"
    elif resolved["formal_verified"]:
        status = "REVIEW_REQUIRED"
        if not invalid_review and all(v == "APPROVE" for v in dimensions.values()):
            status = "ACCEPTED_UNDER_POLICY"
    return AcceptanceRecord.build(
        binding_digest=binding.digest,
        revision_id=binding.revision_id,
        assertion_id=binding.assertion_id,
        obligation_digest=binding.obligation_digest,
        profile_digest=profile.digest,
        policy_digest=digest("acceptance-policy.v1", POLICY),
        trust_digest=digest("external-authority.v1", dict(trust_store)),
        evaluation_time=evaluation_time,
        execution_digest=resolved["execution_digest"],
        review_digests=sorted(set(review_ids)),
        formal_status="VERIFIED" if resolved["formal_verified"] else "UNVERIFIED",
        source_fidelity=dimensions["source-fidelity"],
        formal_fidelity=dimensions["formal-fidelity"],
        assessment=status,
        reasons=reasons,
    )
