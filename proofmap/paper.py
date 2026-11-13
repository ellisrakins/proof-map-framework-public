"""Offline-first paper CI: authored assertions, not automated truth certification."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, replace
from importlib.metadata import version
from importlib.resources import files as package_files
from pathlib import Path
from typing import Any

from .extractor import extract
from .integrity import artifact_digest, digest, load_json, write_json
from .kernel import Assessment, Claim, Context, Inference, KernelMap, TypedRelation, closure
from .paper_checkers import make_result, register, required_failures, run_checker
from .paper_sources import acquire, parse, source_validation_operation
from .paper_store import PaperStore

POLICY = {
    "id": "paper-ci-alpha-v1",
    "version": 1,
    "source_required": True,
    "author_assertions_are_proof": False,
    "model_suggestions_are_evidence": False,
    "allow_partial_extraction": True,
    "formal_execution": "isolated-only",
}


def assertion_layer(ir: dict[str, Any]) -> tuple[list[dict[str, Any]], KernelMap]:
    revision = ir["revision"]
    assertions = []
    claims = []
    for el in ir["elements"]:
        if el["kind"] != "ASSERTION":
            continue
        proofs = [
            p["id"] for p in ir["elements"] if p["kind"] == "PROOF" and p["proof_for"] == el["id"]
        ]
        assertion = {
            "id": el["id"],
            "revision": revision,
            "source_ids": [el["id"]],
            "statement": el["text"],
            "scope": el["scope"],
            "status": "AUTHOR_ASSERTED",
            "role": el.get("role", "UNRESOLVED"),
            "hypotheses": "UNRESOLVED_IN_SOURCE_TEXT",
            "quantifiers": "UNRESOLVED_IN_SOURCE_TEXT",
            "conclusion": "UNRESOLVED_IN_SOURCE_TEXT",
            "proof_ids": proofs,
            "fidelity": "NOT_REVIEWED",
            "formal_obligation_digest": None,
            "assessment": asdict(Assessment(el["id"])),
            "source_context": [
                row for row in ir.get("mathematical_context", []) if row["owner"] == el["id"]
            ],
        }
        assertions.append(assertion)
        claims.append(
            Claim(
                el["id"],
                el["text"],
                revision,
                revision,
                scope=el["scope"],
                label=", ".join(el["labels"]),
            )
        )
    claim_ids = {c.id for c in claims}
    proof_owners = {e["id"]: e["proof_for"] for e in ir["elements"] if e["kind"] == "PROOF"}
    deps: dict[str, set[str]] = {}
    for ref in ir["references"]:
        conclusion = proof_owners.get(ref["owner"], ref["owner"])
        if conclusion not in claim_ids or len(ref["targets"]) != 1:
            continue
        for target in ref["targets"]:
            if target in claim_ids:
                deps.setdefault(conclusion, set()).add(target)
    inferences = tuple(
        Inference(
            "author-inference:" + c,
            c,
            tuple(sorted(ps)),
            revision,
            mode="PAPER_ASSERTION",
            status="REVIEW_REQUIRED",
        )
        for c, ps in sorted(deps.items())
    )
    if "source_inferences" in ir:
        inferences = tuple(
            Inference(
                "author-inference:" + row["id"],
                row["conclusion"],
                tuple(row["premises"]),
                revision,
                mode="PAPER_ASSERTION",
                status="REVIEW_REQUIRED",
            )
            for row in ir["source_inferences"]
            if row["conclusion"] in claim_ids
            and all(target in claim_ids for target in row["premises"])
        )
    graph = KernelMap(
        tuple(claims),
        (
            Context(
                revision, revision, "Revision-local author definitions, not trusted foundations"
            ),
        ),
        inferences,
        warnings=("Source references are author dependencies, not verified derivations.",),
    )
    graph.validate()
    return assertions, graph


def checker(name: str, status: str, findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return make_result(name, status, findings)


def _extraction_replay(record: Any, revision: str, config: dict[str, Any]) -> dict[str, Any]:
    """Accept exported event lists and older records without weakening replay binding."""
    from .extractor import BUDGET_DEFAULTS

    config_digest = digest("extractor-config.v1", config)
    if isinstance(record, list):
        events = record
    elif isinstance(record, dict) and "events" in record:
        if record.get("revision") != revision or record.get("config_digest") != config_digest:
            raise ValueError("STALE_EXTRACTION_REPLAY")
        events = record["events"]
    elif isinstance(record, dict) and "request_sha256" in record:
        events = [record]
    else:
        raise ValueError("EXTRACTION_REPLAY_FORMAT")
    if not isinstance(events, list) or len(events) > BUDGET_DEFAULTS["max_requests"]:
        raise ValueError("EXTRACTION_REPLAY_FORMAT")
    required = ("request_sha256", "config_digest", "raw_response", "response_sha256")
    for event in events:
        if not isinstance(event, dict) or any(not isinstance(event.get(k), str) for k in required):
            raise ValueError("EXTRACTION_REPLAY_FORMAT")
        if event.get("revision", revision) != revision or event["config_digest"] != config_digest:
            raise ValueError("STALE_EXTRACTION_REPLAY")
        if len(event["raw_response"].encode("utf-8")) > 1_000_000:
            raise ValueError("EXTRACTOR_OUTPUT_BUDGET")
    # extract_document/ extract recompute every chunk request and raw-response hash.
    # Stored classifications are never accepted in place of validating the response.
    return {"revision": revision, "config_digest": config_digest, "events": events}


@source_validation_operation
def ci(
    input_path: Path,
    out: Path,
    store_root: Path,
    *,
    extractor: str = "none",
    config: dict[str, Any] | None = None,
    parser: str = "auto",
    entrypoint: str | None = None,
    paper_id: str | None = None,
    replay: dict[str, Any] | list[dict[str, Any]] | None = None,
    execution_profile: dict[str, Any] | None = None,
    controller_key: bytes | None = None,
    controller_id: str = "local-unsigned",
    trust_store: dict[str, Any] | None = None,
    evaluation_time: str | None = None,
    require_formal: bool = False,
    resume: bool = False,
    candidate_overrides: dict[str, bytes] | None = None,
    candidate_fidelity_config: dict[str, Any] | None = None,
    candidate_fidelity_replay: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    start = time.monotonic()
    config = config or {}
    if set(config) - {"extractor", "exact_checks", "required_stages"}:
        raise ValueError("UNKNOWN_PAPER_CONFIG_FIELDS")
    if extractor not in {"none", "configured", "replay"}:
        raise ValueError("Unknown extractor mode")
    # Prevent accidental replacement of manuscript files or acquisition of our outputs.
    root = input_path.resolve()
    if out.resolve() == root or (root.is_dir() and out.resolve().is_relative_to(root)):
        raise ValueError("Output must be outside the manuscript input tree")
    if root.is_dir() and store_root.resolve().is_relative_to(root):
        raise ValueError("Store must be outside the manuscript input tree")
    manifest, files = acquire(input_path, entrypoint)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "input_manifest.json", manifest.to_dict())
    from .extractor import PROMPT, RESPONSE_SCHEMA
    from .semantic_candidates import DECOMPOSITION_PROMPT, FIDELITY_PROMPT

    analysis_inputs: dict[str, Any] = {
        "revision": manifest.revision,
        "config": config,
        "candidate_fidelity_config": candidate_fidelity_config,
        "extractor_contract": {
            "classification_prompt": artifact_digest(PROMPT.encode()),
            "decomposition_prompt": artifact_digest(DECOMPOSITION_PROMPT.encode()),
            "fidelity_prompt": artifact_digest(FIDELITY_PROMPT.encode()),
            "classification_schema": digest("extraction-schema.v1", RESPONSE_SCHEMA),
        },
        "parser_requested": parser,
        "extractor_mode": extractor,
        "policy": POLICY,
        "execution_profile": execution_profile,
        "require_formal": require_formal,
        "candidate_overrides": {
            k: artifact_digest(v) for k, v in (candidate_overrides or {}).items()
        },
        "parser_packages": {name: version(name) for name in ("pylatexenc", "pypdf")},
        "pipeline_revision": digest(
            "pipeline-code.v1",
            {
                name: package_files("proofmap").joinpath(name + ".py").read_text(encoding="utf-8")
                for name in (
                    "paper",
                    "paper_sources",
                    "extractor",
                    "kernel",
                    "integrity",
                    "exact_check",
                    "paper_store",
                    "formalize",
                    "evidence_records",
                    "execution",
                    "evidence_adapter",
                    "paper_checkers",
                    "paper_evidence",
                    "paper_stages",
                    "paper_reports",
                    "lean_worker",
                    "paper_parse_worker",
                    "paper_revision",
                    "source_semantics",
                    "semantic_candidates",
                    "paper_records",
                    "paper_actions",
                    "paper_overrides",
                )
            },
        ),
    }
    analysis_digest = digest("paper-analysis.v1", analysis_inputs)
    stage_manifests = []
    reused_stages = []
    stage_analysis = analysis_digest
    cache = PaperStore(store_root)
    try:
        stage_args: dict[str, Any] = dict(
            revision=manifest.revision,
            analysis=analysis_digest,
            stage="parsing",
            inputs={"revision": manifest.revision},
            implementation=analysis_digest,
        )
        cached = cache.load_stage(**stage_args)
        if cached is not None:
            ir = cached["output"]
            stage_manifests.append(cached["manifest"])
            reused_stages.append(cached["manifest"]["id"])
        else:
            ir = parse(manifest, files, parser)
            stage_manifests.append(
                cache.commit_stage(
                    **stage_args,
                    output=ir,
                    outcome=ir["parser"]["execution"]
                    if ir["parser"].get("execution") in {"TIMEOUT", "ERROR", "UNAVAILABLE"}
                    else "PASS"
                    if ir["status"] == "PASS"
                    else "PARTIAL",
                )
            )
    finally:
        cache.close()
    # Bind actual parser build, not merely the requested alias.
    analysis_digest = digest("paper-analysis.v1", {"base": analysis_digest, "parser": ir["parser"]})
    analysis_context = {
        name: value for name, value in analysis_inputs.items() if name != "revision"
    }
    analysis_context["parser_actual"] = ir["parser"]
    analysis_context["trust"] = digest("paper-current-trust.v1", trust_store)
    from .paper_revision import (
        historical_candidates,
        prepare_formalizations,
        record_formal_execution,
        revision_plan,
    )

    cache = PaperStore(store_root)
    try:
        previous = cache.latest(paper_id or manifest.entrypoint)
        revision = revision_plan(previous, ir, analysis_context)
        prepared, formal_stages, formal_reused = prepare_formalizations(
            ir,
            revision,
            cache,
            analysis_digest,
            analysis_inputs["pipeline_revision"],
            previous,
        )
        stage_manifests.extend(formal_stages)
        reused_stages.extend(formal_reused)
    finally:
        cache.close()
    assertions, graph = assertion_layer(ir)
    findings = list(ir["findings"])
    events = []
    stages = [
        checker("source-integrity", "PASS"),
        checker("source-structure", ir["status"]),
        checker("dependency-context", "PARTIAL" if assertions else "NOT_APPLICABLE"),
        checker(
            "citation-local",
            "PARTIAL" if any(f["code"] == "UNRESOLVED_CITATION" for f in findings) else "PASS",
        ),
    ]
    infrastructure_failure = ir["parser"].get("execution") in {"TIMEOUT", "ERROR", "UNAVAILABLE"}
    if extractor != "none":
        try:
            if "extractor" not in config or (extractor == "replay" and replay is None):
                raise ValueError("Explicit extractor config and replay event are required")
            from .extractor import extract_document

            recorded = (
                _extraction_replay(replay, ir["revision"], config["extractor"])
                if extractor == "replay"
                else None
            )

            def cached_extract(
                chunk: dict[str, Any], model_config: dict[str, Any], **kwargs: Any
            ) -> dict[str, Any]:
                cache = PaperStore(store_root)
                try:
                    key: dict[str, Any] = dict(
                        revision=manifest.revision,
                        analysis=stage_analysis,
                        stage="extraction",
                        inputs={
                            "chunk": digest("extraction-chunk-input.v1", chunk),
                            "config": digest("extractor-config.v1", model_config),
                            "replay": digest("recorded-extraction.v1", kwargs.get("replay")),
                        },
                        implementation=stage_analysis,
                        parents={"parsing": stage_manifests[0]["id"]},
                    )
                    cached_chunk = cache.load_stage(**key)
                    if cached_chunk is not None:
                        event: dict[str, Any] = cached_chunk["output"]["event"]
                        checked = extract(chunk, model_config, replay=event)
                        if checked["result"] != event["result"]:
                            raise ValueError("EXTRACTION_CACHE_RESULT_MISMATCH")
                        stage_manifests.append(cached_chunk["manifest"])
                        reused_stages.append(cached_chunk["manifest"]["id"])
                        return event
                    event = extract(chunk, model_config, **kwargs)
                    stage_manifests.append(
                        cache.commit_stage(
                            **key, output={"event": event, "chunk": chunk, "config": model_config}
                        )
                    )
                    return event
                finally:
                    cache.close()

            extracted = extract_document(
                ir,
                config["extractor"],
                replay=recorded,
                extract_chunk=cached_extract,
            )
            events.extend(extracted["events"])
            findings.extend(extracted["findings"])
            stages.append(checker("model-extraction", extracted["status"]))
        except (OSError, ValueError) as exc:
            infrastructure_failure = True
            stages.append(checker("model-extraction", "ERROR"))
            findings.append(
                {
                    "code": "EXTRACTOR_ERROR",
                    "detail": type(exc).__name__,
                    "classification": "INFRASTRUCTURE",
                    "blocking_eligible": False,
                }
            )
    else:
        stages.append(checker("model-extraction", "NOT_RUN"))
    from .extractor import semantic_overlay

    overlay = semantic_overlay(ir, events)
    from .semantic_candidates import check_candidate_fidelity

    fidelity = check_candidate_fidelity(
        ir,
        overlay.get("candidates", []),
        candidate_fidelity_config,
        replay=candidate_fidelity_replay,
    )
    # Candidate AND groups remain separate from author references and certified proofs.
    claim_ids = {c.id for c in graph.claims}
    candidate_inferences = []
    relations: list[TypedRelation] = []
    for row in overlay.get("candidate_dependencies", []):
        if row["conclusion"] in claim_ids and all(p in claim_ids for p in row["premises"]):
            candidate_inferences.append(
                Inference(
                    "candidate:" + row["id"],
                    row["conclusion"],
                    tuple(row["premises"]),
                    manifest.revision,
                    mode="PAPER_ASSERTION",
                    status="REVIEW_REQUIRED",
                )
            )
            relations.extend(
                TypedRelation(p, row["conclusion"], "MODEL_INFERRED_DEPENDENCY")
                for p in row["premises"]
                if p != row["conclusion"]
            )
    graph = replace(
        graph, inferences=graph.inferences + tuple(candidate_inferences), relations=tuple(relations)
    )
    from .paper_evidence import analyze_formalizations

    register("formal", analyze_formalizations)
    formal = run_checker(
        "formal",
        ir,
        assertions,
        execution_profile=execution_profile,
        controller_key=controller_key,
        controller_id=controller_id,
        trust_store=trust_store,
        evaluation_time=evaluation_time,
        required=require_formal or "formal" in config.get("required_stages", []),
        candidate_overrides=candidate_overrides,
        prepared_rows=prepared,
        historical_candidates=historical_candidates(previous, revision),
    )
    record_formal_execution(revision, formal["formalizations"])
    findings.extend(formal["findings"])
    if formal["status"] in {"UNAVAILABLE", "ERROR", "TIMEOUT"} and (
        require_formal
        or execution_profile is not None
        or "formal" in config.get("required_stages", [])
    ):
        infrastructure_failure = True
    exact = []
    for check in config.get("exact_checks", []):
        if set(check) != {"label", "left", "right"}:
            raise ValueError("EXACT_CHECK_FIELDS")
        sources = [e for e in ir["elements"] if check["label"] in e["labels"]]
        if len(sources) != 1:
            raise ValueError("EXACT_CHECK_SOURCE_MISSING_OR_AMBIGUOUS")
        # The author manifest selects an encoded equality. It is not proof of
        # its correspondence to prose; a false encoding cannot block the paper.
        passed = run_checker("exact-polynomial", check["left"], check["right"])["check"] == "PASS"
        result = {
            "code": "EXACT_EQUALITY_PASS" if passed else "CANDIDATE_EXACT_CONTRADICTION",
            "source": sources[0]["id"],
            "expression": check,
            "domain": "Q[x]",
            "classification": "ENCODED_COMPUTATION",
            "fidelity": "NOT_REVIEWED",
            "blocking_eligible": False,
        }
        result["certificate_digest"] = digest("exact-check.v1", result)
        exact.append(result)
    findings.extend(exact)
    stages.extend(
        [
            checker(
                "exact",
                "PASS"
                if exact and all(f["code"] == "EXACT_EQUALITY_PASS" for f in exact)
                else "FAIL"
                if exact
                else "NOT_APPLICABLE",
                exact,
            ),
            checker("formal", formal["status"]),
            checker("extraction-fidelity", fidelity["execution_status"]),
        ]
    )
    required = config.get("required_stages", ["source-integrity", "source-structure"])
    if require_formal and isinstance(required, list):
        required = list(dict.fromkeys(required + ["formal"]))
    source_ids = [row["id"] for row in ir["elements"]]
    measured = {
        "formal": {
            "attempted": formal["supported"] if execution_profile else 0,
            "eligible": len(formal["formalizations"]),
            "supported": formal["supported"] if execution_profile else 0,
            "denominator": "Source assertion formalizations",
            "reason": "Historical formal facts are authenticated separately from new execution.",
        },
        "extraction-fidelity": {
            "attempted": fidelity["attempted"],
            "eligible": fidelity["eligible"],
            "supported": len(fidelity["decisions"]),
            "denominator": "Source-anchored candidate interpretations",
            "reason": "Advisory provider decisions are not authenticated source/formal fidelity reviews.",
        },
        "exact": {
            "attempted": len(exact),
            "eligible": len(exact),
            "supported": len(exact),
            "denominator": "Explicit encoded exact checks",
            "reason": "Source formalization exact checks are retained in each formalization row.",
        },
    }
    stages = [
        make_result(
            stage["checker"],
            stage["execution_status"],
            stage["findings"],
            revision=manifest.revision,
            source_ids=source_ids,
            configuration={"analysis": analysis_digest, "policy": POLICY},
            coverage=measured.get(stage["checker"]),
        )
        for stage in stages
    ]
    missing = required_failures(
        stages,
        required,
        allow_partial={"source-structure", "dependency-context", "citation-local"} & set(required),
    )
    code = 3 if infrastructure_failure else 1 if missing else 0
    outcome = {
        "pipeline_execution": "ERROR" if infrastructure_failure else "FAIL" if missing else "PASS",
        "source_integrity": "PASS",
        "extraction_quality": ir["status"],
        "coverage": {
            "authored_assertions": len(assertions),
            "theorem_like_claims": len(formal["formalizations"]),
            "supported_formal_obligations": formal["supported"],
            "kernel_verified": formal["verified"],
            "kernel_verified_fraction": formal["verified"] / len(formal["formalizations"])
            if formal["formalizations"]
            else None,
            "reviewed_claims": 0,
            "accepted_claims": 0,
        },
        "structural_consistency": "PARTIAL",
        "computational": stages[-3]["execution_status"],
        "formal_compilation": formal["status"],
        "kernel_verification": "PASS"
        if formal["verified"]
        else "NOT_RUN"
        if not formal["execution_events"]
        else "NOT_VERIFIED",
        "formal_statement_fidelity": "NOT_REVIEWED",
        "scholarly_acceptance": "NOT_ASSESSED",
    }
    bundle: dict[str, Any] = {
        "input_manifest": manifest.to_dict(),
        "document_ir": ir,
        "assertions": assertions,
        "symbols": [
            e
            for e in ir["elements"]
            if e["kind"] in {"SYMBOL_OCCURRENCE", "MACRO_DEFINITION", "MATH_EXPRESSION"}
        ],
        "argument_map": graph.to_dict(),
        "extraction_events": events,
        "semantic_overlay": overlay,
        "candidate_fidelity": fidelity,
        "formalizations": formal["formalizations"],
        "execution_events": formal["execution_events"],
        "acceptance_records": formal["acceptance_records"],
        "assessment_records": formal["assessment_records"],
        "stage_manifests": stage_manifests,
        "revision_plan": revision,
        "findings": findings,
        "assessment": {
            "schema_version": "1.0",
            "policy": POLICY,
            "outcomes": outcome,
            "checkers": stages,
            "missing_required_stages": missing,
            "closure": closure(graph, policy="paper-assertion-v1").to_dict(),
            "warning": "Pipeline conformance is not proof, peer review, or novelty.",
        },
        "run_manifest": {
            "record_contract_version": "1.0",
            "schema_version": "1.0",
            "run_id": str(uuid.uuid4()),
            "revision": manifest.revision,
            "analysis_digest": analysis_digest,
            "analysis_context": analysis_context,
            "policy_digest": digest("paper-policy.v1", POLICY),
            "duration_seconds": round(time.monotonic() - start, 6),
            "exit_code": code,
            "cache_provenance": {
                "reused_stages": reused_stages,
                "resume_requested": resume,
                "namespace": "local-controller",
            },
        },
    }
    from .paper_actions import plan_paper_actions

    authority: dict[str, Any] = (
        {
            "profile": execution_profile,
            "trust_store": trust_store,
            "evaluation_time": evaluation_time,
        }
        if execution_profile is not None and trust_store is not None and evaluation_time is not None
        else {}
    )
    bundle["action_plan"] = plan_paper_actions(bundle, **authority)
    bundle["run_manifest"]["bundle_digests"] = {
        name: digest("paper-bundle-component.v1", value)
        for name, value in bundle.items()
        if name != "run_manifest"
    }
    for name, value in bundle.items():
        write_json(out / (name + ".json"), value)
    render(bundle, out, files)
    store = PaperStore(store_root)
    try:
        store.ingest(paper_id or manifest.entrypoint, bundle, files)
    finally:
        store.close()
    return bundle, code


def render(bundle: dict[str, Any], out: Path, artifacts: dict[str, bytes] | None = None) -> None:
    from .paper_reports import write_reports

    write_reports(bundle, out, artifacts)


def review_export(bundle: dict[str, Any], author: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "revision": bundle["input_manifest"]["revision"],
        "analysis_digest": bundle["run_manifest"]["analysis_digest"],
        "author": author,
        "attribution_authenticated": False,
        "decisions": [
            {
                "assertion": a["id"],
                "assertion_digest": digest("assertion.v1", a),
                "formal_obligation_digest": a["formal_obligation_digest"],
                "source_fidelity": "NOT_REVIEWED",
                "formal_fidelity": "NOT_REVIEWED",
                "note": "",
            }
            for a in bundle["assertions"]
        ],
    }


def review_apply(bundle: dict[str, Any], review: dict[str, Any], store: PaperStore) -> str:
    from .integrity import canonical_bytes

    indexed = store.inspect(bundle["run_manifest"]["run_id"])["bundle"]
    if canonical_bytes(bundle) != canonical_bytes(indexed):
        raise ValueError("Review bundle differs from the immutable indexed run")
    expected = review_export(bundle, review.get("author", ""))
    if set(review) != set(expected) or any(
        review[k] != expected[k]
        for k in ("schema_version", "revision", "analysis_digest", "attribution_authenticated")
    ):
        raise ValueError("STALE_OR_INVALID_REVIEW")
    if not isinstance(review["author"], str) or not review["author"].strip():
        raise ValueError("Review attribution required (not authentication)")
    by_id = {a["assertion"]: a for a in expected["decisions"]}
    seen = set()
    for decision in review["decisions"]:
        target = by_id.get(decision.get("assertion"))
        if target is None or set(decision) != set(target) or decision["assertion"] in seen:
            raise ValueError("INVALID_REVIEW_TARGET")
        seen.add(decision["assertion"])
        for key in ("assertion_digest", "formal_obligation_digest"):
            if decision[key] != target[key]:
                raise ValueError("STALE_REVIEW_BINDING")
        if (
            decision["source_fidelity"] not in {"NOT_REVIEWED", "ACCEPTED", "REJECTED"}
            or decision["formal_fidelity"] != "NOT_REVIEWED"
        ):
            raise ValueError(
                "Review cannot forge formal evidence or review a missing formalization"
            )
        if not isinstance(decision["note"], str):
            raise ValueError("Review note type")
    return store.add_review(review)


def diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    from .paper_revision import revision_plan

    plan = revision_plan(old, new["document_ir"], new["run_manifest"].get("analysis_context", {}))
    matched = {row["previous_assertion_id"] for row in plan["rows"]}
    invalidated = {
        row["previous_assertion_id"]
        for row in plan["rows"]
        if not row["reuse_eligible"] and row["previous_assertion_id"] is not None
    }
    invalidated.update(row["id"] for row in old["assertions"] if row["id"] not in matched)
    reasons = sorted({reason for row in plan["rows"] for reason in row["reasons"]})
    observed = new.get("revision_plan", {})
    return {
        "old_revision": old["input_manifest"]["revision"],
        "new_revision": new["input_manifest"]["revision"],
        "changes": [
            {
                "label": row["label"],
                "kind": ",".join(row["changes"]) or "UNCHANGED",
                "reasons": row["reasons"],
            }
            for row in plan["rows"]
            if row["logical_id"] is not None
        ],
        "invalidated_assertions": sorted(invalidated),
        "invalidation_reasons": reasons,
        "stale_source_bindings": [row["id"] for row in old["assertions"]]
        if old["input_manifest"]["revision"] != new["input_manifest"]["revision"]
        else [],
        "reviews": "STALE"
        if old["run_manifest"]["analysis_digest"] != new["run_manifest"]["analysis_digest"]
        else "UNCHANGED",
        "reuse": {
            "eligible_assertions": [
                row["assertion_id"] for row in plan["rows"] if row["reuse_eligible"]
            ],
            "observed": observed.get("rows", [])
            if observed.get("parent_run") == old["run_manifest"]["run_id"]
            else [],
            "authority": "PURE_ARTIFACT_OR_AUTHENTICATED_HISTORICAL_FACT; CURRENT_FIDELITY_REQUIRED",
        },
    }


def load_bundle(directory: Path) -> dict[str, Any]:
    run = load_json(directory / "run_manifest.json")
    bundle = {
        name: load_json(directory / (name + ".json"))
        for name in run["bundle_digests"]
        if name
        in {
            "input_manifest",
            "document_ir",
            "assertions",
            "symbols",
            "argument_map",
            "extraction_events",
            "findings",
            "assessment",
            "semantic_overlay",
            "candidate_fidelity",
            "formalizations",
            "execution_events",
            "acceptance_records",
            "assessment_records",
            "action_plan",
            "stage_manifests",
            "revision_plan",
            "interpreted_ir",
            "interpretation_overrides",
        }
    }
    bundle["run_manifest"] = run
    expected = bundle["run_manifest"].get("bundle_digests")
    actual = {
        name: digest("paper-bundle-component.v1", value)
        for name, value in bundle.items()
        if name != "run_manifest"
    }
    if expected != actual:
        raise ValueError("STALE_OR_MIXED_PAPER_BUNDLE")
    from .paper_store import validate_bundle

    validate_bundle(bundle)
    return bundle
