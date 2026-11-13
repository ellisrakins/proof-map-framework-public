"""Read-only campaign views; presentation never supplies mathematical authority."""

from __future__ import annotations

import html
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..integrity import atomic_write, digest, markdown_text, write_json
from ..paper_reports import report_model, write_reports
from ..paper_sources import source_validation_operation
from .inventory import unresolved_region_count


def qualified_anchor(ref: dict[str, Any]) -> str:
    return "claim-" + digest("campaign-qualified-anchor.v1", ref)


def _paper_anchor(selection: dict[str, Any]) -> str:
    return digest("campaign-paper-anchor.v1", selection)


def _current(
    store: Any,
    bundle: dict[str, Any],
    profile: dict[str, Any],
    authority: dict[str, Any],
    evaluation_time: str,
) -> dict[str, Any]:
    """Use the existing trust adapter without publishing a new audit or verdict."""
    from .operations import _view

    bundle = _view(store, bundle)
    from ..attempts import FormalObligation
    from ..evidence_adapter import POLICY, assess_binding
    from ..evidence_records import FormalizationBinding, VerifierProfile

    verified_profile = VerifierProfile.from_dict(profile)
    events = {row["event"]["id"]: row for row in bundle.get("execution_events", [])}
    reviews = store.list_audit(bundle["run_manifest"]["run_id"], "ReviewDecision")
    records = []
    for row in bundle.get("formalizations", []):
        if row["status"] != "SUPPORTED":
            continue
        binding = FormalizationBinding.from_dict(row["binding"])
        relevant = [
            review["envelope"]
            for review in reviews
            if review["record"]["binding_digest"] == binding.digest
            and review["envelope"] is not None
        ]
        current_envelope = events.get(row.get("execution_event", ""), {}).get("envelope")
        records.append(
            assess_binding(
                binding,
                FormalObligation.from_dict(row["obligation"]),
                verified_profile,
                current_envelope,
                relevant,
                authority,
                evaluation_time=evaluation_time,
                historical_execution=(
                    row.get("historical_execution") if current_envelope is None else None
                ),
            ).to_dict()
        )
    return {"policy": POLICY, "evaluation_time": evaluation_time, "records": records}


def _ref(bundle: dict[str, Any], selection: dict[str, Any], assertion: str) -> dict[str, Any]:
    from ..evidence_adapter import POLICY

    source = next(row for row in bundle["assertions"] if row["id"] == assertion)
    formal: dict[str, Any] = next(
        (row for row in bundle.get("formalizations", []) if row["assertion_id"] == assertion),
        {},
    )
    return {
        "paper_id": selection["paper_id"],
        "run_id": selection["run_id"],
        "revision": selection["revision"],
        "assertion_id": assertion,
        "assertion_digest": digest("assertion.v1", source),
        "binding_digest": formal.get("binding", {}).get("id"),
        "interpretation_digest": digest(
            "campaign-interpretation.v1",
            next(
                row
                for row in bundle.get("interpreted_ir", bundle["document_ir"])["elements"]
                if row["id"] == assertion
            ),
        ),
        "assessment_policy": digest("acceptance-policy.v1", POLICY),
    }


def validate_qualified_ref(store: Any, ref: dict[str, Any]) -> dict[str, Any]:
    """Validate endpoint content and its paper namespace; never guess by a label."""
    from .models import validate_ref_material

    validate_ref_material(store, ref)
    required = {"paper_id", "run_id", "revision", "assertion_id", "assertion_digest"}
    if not isinstance(ref, dict) or not required <= ref.keys():
        raise ValueError("RELATION_REQUIRES_QUALIFIED_ENDPOINT")
    indexed = store.db.execute(
        "SELECT r.paper_id,u.revision FROM runs u JOIN revisions r ON r.id=u.revision WHERE u.id=?",
        (ref["run_id"],),
    ).fetchone()
    if indexed != (ref["paper_id"], ref["revision"]):
        raise ValueError("RELATION_ENDPOINT_NAMESPACE")
    bundle = store.inspect(ref["run_id"])["bundle"]
    matches = [row for row in bundle["assertions"] if row["id"] == ref["assertion_id"]]
    if len(matches) != 1 or digest("assertion.v1", matches[0]) != ref["assertion_digest"]:
        raise ValueError("RELATION_ENDPOINT_ASSERTION")
    formal: dict[str, Any] = next(
        (r for r in bundle.get("formalizations", []) if r["assertion_id"] == ref["assertion_id"]),
        {},
    )
    if ref.get("binding_digest") != formal.get("binding", {}).get("id"):
        raise ValueError("RELATION_ENDPOINT_BINDING")
    if not isinstance(ref.get("assessment_policy"), str) or not ref["assessment_policy"]:
        raise ValueError("RELATION_ENDPOINT_ASSESSMENT_POLICY")
    return next(
        row["locator"]
        for row in bundle["document_ir"]["elements"]
        if row["id"] == ref["assertion_id"]
    )


@source_validation_operation
def candidate_relation(
    store: Any,
    campaign_id: str,
    left_ref: dict[str, Any],
    right_ref: dict[str, Any],
    *,
    relation: str,
    reason: str,
    method: str = "OPERATOR",
    actor: str = "operator",
    ambiguity: list[str] | None = None,
) -> dict[str, Any]:
    from .models import record, utc_now

    if relation not in {
        "CITES",
        "CANDIDATE_DEPENDENCY",
        "POSSIBLE_DUPLICATE",
        "POSSIBLE_CONTRADICTION",
    }:
        raise ValueError("UNSUPPORTED_CAMPAIGN_RELATION")
    if not reason.strip() or not method.strip() or not actor.strip():
        raise ValueError("RELATION_PROVENANCE_REQUIRED")
    snapshot = store.current_snapshot(campaign_id)
    members = {(s["paper_id"], s["run_id"], s["revision"]) for s in snapshot["selections"]}
    for ref in (left_ref, right_ref):
        if (ref["paper_id"], ref["run_id"], ref["revision"]) not in members:
            raise ValueError("RELATION_ENDPOINT_NOT_SELECTED")
    anchors = [validate_qualified_ref(store, ref) for ref in (left_ref, right_ref)]
    value = record(
        "CampaignRelationCandidate",
        campaign_id=campaign_id,
        snapshot_id=snapshot["id"],
        left=deepcopy(left_ref),
        right=deepcopy(right_ref),
        source_anchors=anchors,
        relation=relation,
        reason=reason,
        method=method,
        actor=actor,
        created_at=utc_now(),
        ambiguity=ambiguity or [],
        proof_closure=False,
        review_state="BRIDGE_REVIEW_REQUIRED",
    )
    store.add_record(value, campaign_id)
    return value


def _task_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = {row["id"]: deepcopy(row) for row in records if row["kind"] == "Task"}
    attempts: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        task_id = str(row.get("task_id", ""))
        if row["kind"] == "TaskAttempt":
            attempts.setdefault(task_id, []).append(row)
        if row["kind"] == "TaskEvent" and task_id in tasks:
            tasks[task_id]["operation_state"] = row.get("state", row.get("to_state"))
            tasks[task_id]["resources_and_lease"] = row.get("projection", {})
            tasks[task_id].setdefault("events", []).append(row)
    for ident, task in tasks.items():
        task["attempts"] = attempts.get(ident, [])
        task.setdefault("operation_state", task.get("state", "REQUESTED"))
        task["next_operator_action"] = (
            "Create an explicit fidelity decision and sign it with externally configured authority."
            if task["operation_state"] == "AWAITING_REVIEW"
            else "Inspect the exact target and prerequisite work before authorizing dispatch."
        )
        task["results"] = [
            row for row in records if row["kind"] == "TaskResult" and row.get("task_id") == ident
        ]
    return [_display(row) for row in tasks.values()]


def _display(value: Any) -> Any:
    """Local paths and live fencing tokens are audit data, not public UI values."""
    hidden = {
        "source_path",
        "source_roots",
        "private_key_path",
        "controller_config",
        "lease_token",
        "private_key",
        "controller_key",
        "api_key",
        "access_token",
        "refresh_token",
        "password",
    }
    if isinstance(value, dict):
        return {
            key: "[LOCAL_CONFIGURATION_REDACTED]" if key in hidden else _display(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_display(child) for child in value]
    return value


def _paper_view(
    store: Any, bundle: dict[str, Any], current: dict[str, Any] | None
) -> dict[str, Any]:
    """Align existing paper outcomes/review links with the same campaign evaluation."""
    from .operations import _view

    view = _view(store, bundle)
    assessments = {r["assertion_id"]: r for r in (current or {}).get("records", [])}
    authenticated_reviews = {ident for r in assessments.values() for ident in r["review_digests"]}
    reviews = store.list_audit(bundle["run_manifest"]["run_id"], "ReviewDecision")
    for formal in view.get("formalizations", []):
        formal.pop("current_assessment", None)
        if formal["assertion_id"] in assessments:
            formal["current_assessment"] = assessments[formal["assertion_id"]]
        binding = formal.get("binding", {}).get("id")
        formal["review_decisions"] = [
            {
                **review["record"],
                "attribution_authenticated": review["record"]["id"] in authenticated_reviews,
                "assessment_scope": "CURRENT_AUTHORITY_EVALUATION"
                if current
                else "HISTORICAL_UNAUTHENTICATED",
            }
            for review in reviews
            if review["record"]["binding_digest"] == binding
        ]
    if current is not None:
        records = list(assessments.values())
        outcomes = view["assessment"]["outcomes"]
        coverage = outcomes["coverage"]
        coverage["reviewed_claims"] = sum(
            r["source_fidelity"] == "APPROVE" and r["formal_fidelity"] == "APPROVE" for r in records
        )
        coverage["accepted_claims"] = sum(
            r["assessment"] == "ACCEPTED_UNDER_POLICY" for r in records
        )
        coverage["kernel_verified"] = sum(r["formal_status"] == "VERIFIED" for r in records)
        denominator = coverage["theorem_like_claims"]
        coverage["kernel_verified_fraction"] = (
            coverage["kernel_verified"] / denominator if denominator else None
        )
        outcomes["kernel_verification"] = (
            "PASS"
            if coverage["kernel_verified"]
            else "NOT_VERIFIED"
            if view["execution_events"]
            else "NOT_RUN"
        )
        outcomes["formal_statement_fidelity"] = {
            r["assertion_id"]: r["formal_fidelity"] for r in records
        }
        outcomes["current_policy_assessment"] = {
            r["assertion_id"]: r["assessment"] for r in records
        }
        outcomes["authority_evaluation_time"] = current["evaluation_time"]
    return view


@source_validation_operation
def campaign_report_model(
    store: Any,
    campaign_id: str,
    *,
    execution_profile: dict[str, Any] | None = None,
    trust_store: dict[str, Any] | None = None,
    evaluation_time: str | None = None,
) -> dict[str, Any]:
    """One projection feeds JSON, text, HTML and the namespaced graph ledger."""
    if any((execution_profile, trust_store, evaluation_time)) and not all(
        (execution_profile, trust_store, evaluation_time)
    ):
        raise ValueError("CURRENT_VIEW_REQUIRES_PROFILE_AUTHORITY_AND_TIME")
    snapshot = store.current_snapshot(campaign_id)
    records = store.records(campaign_id)
    activated_snapshots = {snapshot["id"]}
    parent = snapshot.get("parent_snapshot")
    while parent is not None:
        historical = store.get_record(parent)
        if (
            historical["kind"] != "CampaignSnapshot"
            or historical["campaign_id"] != campaign_id
            or parent in activated_snapshots
            or len(activated_snapshots) > 10_000
        ):
            raise ValueError("REPORT_SNAPSHOT_LINEAGE")
        activated_snapshots.add(parent)
        parent = historical.get("parent_snapshot")
    papers, nodes, edges = [], [], []
    coverage = dict.fromkeys(
        [
            "discovered",
            "unresolved_regions",
            "supported",
            "attempted",
            "verified",
            "reviewed",
            "accepted",
        ],
        0,
    )
    for selection in snapshot["selections"]:
        indexed = store.inspect(selection["run_id"])
        original = indexed["bundle"]
        if original["input_manifest"]["revision"] != selection["revision"]:
            raise ValueError("CAMPAIGN_SELECTION_REVISION_MISMATCH")
        artifacts = {name: store.get(sha) for name, sha in indexed["artifacts"].items()}
        current = (
            _current(store, original, execution_profile, trust_store, evaluation_time)
            if execution_profile and trust_store and evaluation_time
            else None
        )
        view = _paper_view(store, original, current)
        assessments = {r["assertion_id"]: r for r in (current or {}).get("records", [])}
        reviews = store.list_reviews(
            selection["revision"], original["run_manifest"]["analysis_digest"]
        )
        paper = report_model(view, artifacts, reviews)
        paper["selection"] = deepcopy(selection)
        paper["report_path"] = "papers/" + _paper_anchor(selection) + "/paper-report.html"
        paper["current_authority"] = current
        paper["historical_assessment"] = deepcopy(original["assessment"])
        formalizations = {r["assertion_id"]: r for r in original.get("formalizations", [])}
        coverage["discovered"] += len(paper["claims"])
        coverage["unresolved_regions"] += unresolved_region_count(
            original.get("interpreted_ir", original["document_ir"])
        )
        for claim in paper["claims"]:
            qualified = _ref(original, selection, claim["id"])
            claim["qualified_ref"] = qualified
            claim["anchor"] = qualified_anchor(qualified)
            formal = formalizations.get(claim["id"], {})
            assessment = assessments.get(claim["id"], {})
            events = claim["evidence"]
            claim["operational_formal_state"] = (
                "UNSUPPORTED"
                if formal.get("status") != "SUPPORTED"
                else events[-1]["event"]["outcome"]
                if events
                else "HISTORICAL_EXECUTION_REQUIRES_REAUTHENTICATION"
                if formal.get("historical_execution")
                else "NOT_RUN"
            )
            claim["current_policy_state"] = assessment.get("assessment", "NOT_EVALUATED")
            claim["review_state"] = (
                "APPROVED"
                if assessment.get("formal_fidelity") == "APPROVE"
                else "REJECTED"
                if assessment.get("formal_fidelity") == "REJECT"
                else "PENDING_OR_NOT_CURRENTLY_AUTHENTICATED"
            )
            coverage["supported"] += int(formal.get("status") == "SUPPORTED")
            coverage["attempted"] += int(bool(events))
            coverage["verified"] += int(assessment.get("formal_status") == "VERIFIED")
            coverage["reviewed"] += int(
                assessment.get("source_fidelity") == "APPROVE"
                and assessment.get("formal_fidelity") == "APPROVE"
            )
            coverage["accepted"] += int(claim["current_policy_state"] == "ACCEPTED_UNDER_POLICY")
            nodes.append(
                {
                    "id": claim["anchor"],
                    "qualified_ref": qualified,
                    "title": claim["title"],
                    "source_anchor": claim["source"]["locator"],
                    "href": "#" + claim["anchor"],
                    "formal_state": claim["operational_formal_state"],
                    "assessment": claim["current_policy_state"],
                    "assessment_provenance": {
                        "policy": (current or {}).get("policy"),
                        "evaluation_time": evaluation_time,
                        "record": assessment or None,
                    },
                    "representation": "PRESENTATION_ONLY",
                    "closure_authority": False,
                }
            )
        by_id = {
            r["qualified_ref"]["assertion_id"]: r["id"]
            for r in nodes
            if r["qualified_ref"]["run_id"] == selection["run_id"]
        }
        ir = original.get("interpreted_ir", original["document_ir"])
        source_inferences = {
            "author-inference:" + row["id"]: row for row in ir.get("source_inferences", [])
        }
        model_inferences = {
            "candidate:" + row["id"]: row
            for row in original.get("semantic_overlay", {}).get("candidate_dependencies", [])
        }
        claims_by_id = {claim["id"]: claim for claim in paper["claims"]}
        for inference in original["argument_map"].get("inferences", []):
            authored = source_inferences.get(inference["id"])
            candidate = model_inferences.get(inference["id"])
            origin = "MODEL_SUGGESTION" if candidate is not None else "AUTHOR_SOURCE_REFERENCE"
            source_record = candidate if candidate is not None else authored
            for premise in inference.get("premises", []):
                if premise in by_id and inference.get("conclusion") in by_id:
                    endpoints = [premise, inference["conclusion"]]
                    edges.append(
                        {
                            "from": by_id[premise],
                            "to": by_id[inference["conclusion"]],
                            "kind": "MODEL_CANDIDATE_DEPENDENCY"
                            if candidate is not None
                            else "AUTHOR_DEPENDENCY",
                            "inference_id": inference["id"],
                            "qualified_inference": {
                                **selection,
                                "inference_id": inference["id"],
                                "inference_digest": digest("campaign-inference.v1", inference),
                            },
                            "inference": deepcopy(inference),
                            "source_anchors": {
                                "endpoints": {
                                    ident: deepcopy(claims_by_id[ident]["source"])
                                    for ident in endpoints
                                },
                                "dependency_locators": deepcopy(
                                    (source_record or {}).get("source_locators", [])
                                ),
                            },
                            "source_provenance": {
                                "origin": origin,
                                "record": deepcopy(source_record),
                                "interpretation_digest": digest("campaign-document-ir.v1", ir),
                            },
                            "support_state": "MODEL_SUGGESTION_REVIEW_REQUIRED"
                            if candidate is not None
                            else "AUTHOR_ASSERTED_UNVERIFIED",
                            "accepted_inferential_support": False,
                            "assessment_provenance": {
                                "scope": "INFERENTIAL_SUPPORT_NOT_AUTHENTICATED",
                                "policy": (current or {}).get("policy"),
                                "evaluation_time": evaluation_time,
                                "endpoint_assessments": {
                                    ident: deepcopy(assessments.get(ident)) for ident in endpoints
                                },
                                "retained_evidence_ids": list(inference.get("evidence", [])),
                                "reason": "Endpoint assessments do not authenticate this dependency as an inferential bridge.",
                            },
                            "closure_authority": False,
                        }
                    )
        papers.append(paper)
    historical_papers = []
    selected_runs = {selection["run_id"] for selection in snapshot["selections"]}
    historical_members = {
        member["run_id"]: member
        for historical in records
        if historical["kind"] == "CampaignSnapshot" and historical["id"] in activated_snapshots
        for member in historical["selections"]
        if member["run_id"] not in selected_runs
    }
    for member in historical_members.values():
        indexed = store.inspect(member["run_id"])
        original = indexed["bundle"]
        paper = report_model(
            _paper_view(store, original, None),
            {name: store.get(sha) for name, sha in indexed["artifacts"].items()},
        )
        paper.update(
            selection=member,
            report_path="papers/" + _paper_anchor(member) + "/paper-report.html",
            current_authority=None,
            historical_assessment=original["assessment"],
            membership_scope="HISTORICAL_SOURCE_VIEW",
        )
        for claim in paper["claims"]:
            ref = _ref(original, member, claim["id"])
            claim.update(
                qualified_ref=ref,
                anchor=qualified_anchor(ref),
                operational_formal_state="HISTORICAL_RECORD",
                current_policy_state="NOT_EVALUATED",
                review_state="HISTORICAL_UNAUTHENTICATED",
            )
        historical_papers.append(paper)
    for relation in (r for r in records if r["kind"] == "CampaignRelationCandidate"):
        edges.append(
            {
                "from": qualified_anchor(relation["left"]),
                "to": qualified_anchor(relation["right"]),
                "kind": relation["relation"],
                "record_id": relation["id"],
                "closure_authority": False,
                "source_anchors": relation["source_anchors"],
                "reason": relation["reason"],
                "review_state": relation["review_state"],
                "applicability": "CURRENT_ENDPOINTS_SELECTED"
                if relation["left"]["run_id"] in selected_runs
                and relation["right"]["run_id"] in selected_runs
                else "HISTORICAL_OR_UNRESOLVED_ENDPOINT",
            }
        )
    tasks = _task_rows(records)
    goals = []
    for goal in snapshot.get("goals", []):
        target = goal.get("target", goal.get("qualified_ref"))
        match = next(
            (
                claim
                for paper in papers
                for claim in paper["claims"]
                if isinstance(target, dict)
                and all(
                    claim["qualified_ref"].get(k) == target.get(k)
                    for k in ("paper_id", "run_id", "revision", "assertion_id", "binding_digest")
                )
            ),
            None,
        )
        goals.append(
            {
                "goal": goal,
                "state": match["current_policy_state"]
                if match
                else "UNRESOLVED_TARGET"
                if isinstance(target, dict)
                else "RESEARCHER_QUESTION",
                "href": "#" + match["anchor"]
                if match
                else "#" + qualified_anchor(target)
                if isinstance(target, dict) and target.get("run_id") in historical_members
                else None,
                "blockers": []
                if match and match["current_policy_state"] == "ACCEPTED_UNDER_POLICY"
                else [
                    "Fresh policy assessment and applicable evidence/reviews required"
                    if match
                    else "No selected exact claim binding"
                ],
            }
        )
    return {
        "schema_version": "1.0",
        "kind": "CampaignReport",
        "campaign_id": campaign_id,
        "objective": snapshot["objective"],
        "snapshot_id": snapshot["id"],
        "snapshot": snapshot,
        "assessment_scope": "CURRENT_AUTHORITY_EVALUATION"
        if execution_profile
        else "HISTORICAL_ONLY_NO_CURRENT_AUTHORITY",
        "evaluation_time": evaluation_time,
        "coverage": coverage,
        "goals": goals,
        "papers": papers,
        "historical_papers": historical_papers,
        "tasks": tasks,
        "relations": [r for r in records if r["kind"] == "CampaignRelationCandidate"],
        "handoffs": [r for r in records if r["kind"] == "ReviewHandoff"],
        "planning": [_display(r) for r in records if r["kind"] in {"CampaignPlan", "ActionPlan"}],
        "historical_snapshots": [
            r for r in records if r["kind"] in {"CampaignSnapshot", "CampaignAssessmentSnapshot"}
        ],
        "snapshot_publication": {
            r["id"]: "CURRENT"
            if r["id"] == snapshot["id"]
            else "ACTIVATED_ANCESTOR"
            if r["id"] in activated_snapshots
            else "UNPROMOTED_RECORD"
            for r in records
            if r["kind"] == "CampaignSnapshot"
        },
        "graph": {
            "representation": "PRESENTATION_ONLY",
            "closure_authority": False,
            "timeline": "EPISTEMIC_RESEARCH_HISTORY",
            "nodes": nodes,
            "edges": edges,
        },
        "warning": "Source assertions, formal execution, fidelity, current policy acceptance and scholarly novelty are separate. Task success supplies no acceptance authority.",
        "scholarly_novelty": "NOT_ASSESSED",
    }


@source_validation_operation
def write_campaign_report(store: Any, campaign_id: str, out: Path, **inputs: Any) -> dict[str, Any]:
    model = campaign_report_model(store, campaign_id, **inputs)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "campaign-report.json", model)
    write_json(out / "graph-ledger.json", model["graph"])
    body = [
        "<h1>Research campaign dossier</h1>",
        "<p>" + html.escape(model["warning"]) + "</p>",
        '<nav aria-label="Campaign navigation"><a href="#goals">Goals</a> · <a href="#papers">Papers</a> · <a href="#planning">Planning</a> · <a href="#tasks">Tasks</a> · <a href="#boundary">Boundary ledger</a> · <a href="#history">History</a></nav>',
    ]
    md = ["# Research campaign dossier", "", markdown_text(model["warning"]), ""]

    def values(value: Any) -> str:
        from ..paper_reports import _pairs

        return (
            "<dl>"
            + "".join(
                "<dt>" + html.escape(k) + "</dt><dd>" + html.escape(v) + "</dd>"
                for k, v in _pairs(value)
            )
            + "</dl>"
        )

    for key in ("objective", "snapshot_id", "assessment_scope", "evaluation_time", "coverage"):
        body.append(values({key: model[key]}))
        md += ["**" + key + "**: " + markdown_text(model[key]), ""]
    for packet in model["handoffs"]:
        destination = out / "review-packets"
        destination.mkdir(exist_ok=True)
        write_json(destination / (packet["id"] + ".json"), packet)
        packet_document = (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\"><title>Review handoff</title></head><body><h1>Pending explicit human decision</h1><p>Review the exact source and formal binding before creating a decision.</p>"
            + values(packet)
            + "</body></html>"
        )
        atomic_write(destination / (packet["id"] + ".html"), packet_document)
    body.append('<h2 id="goals">Goals</h2>')
    for goal in model["goals"]:
        body.append(values(goal))
        if goal["href"]:
            body.append(
                '<a href="' + html.escape(goal["href"], quote=True) + '">Exact goal target</a>'
            )
    body.append(
        '<h2 id="planning">Retained plans, ranking, blockers and assumptions</h2>'
        "<p>Plans describe conditional work. Their recorded evaluation time and snapshot remain historical; they confer no execution or acceptance authority.</p>"
        + values(model["planning"])
    )
    body.append('<h2 id="papers">Papers and source-bound claims</h2>')
    all_papers = model["papers"] + model["historical_papers"]
    for paper in all_papers:
        selection = paper["selection"]
        indexed = store.inspect(selection["run_id"])
        view = _paper_view(store, indexed["bundle"], paper["current_authority"])
        destination = out / "papers" / _paper_anchor(selection)
        write_reports(
            view, destination, {name: store.get(sha) for name, sha in indexed["artifacts"].items()}
        )
        # Existing paper writer calls its outputs review.*, expose stable dossier names.
        paper_html = next(iter(destination.glob("*.html")), None)
        if paper_html and paper_html.name != "paper-report.html":
            atomic_write(destination / "paper-report.html", paper_html.read_bytes())
        body.append(
            "<h3>"
            + html.escape(
                selection["paper_id"]
                + " / "
                + paper.get("membership_scope", "CURRENT_SELECTED_MEMBER")
            )
            + "</h3>"
            + '<a href="'
            + paper["report_path"]
            + '">Open source / interpretation / formal evidence / review</a>'
        )
        for claim in paper["claims"]:
            body.append(
                '<article id="' + claim["anchor"] + '"><h4>' + html.escape(claim["title"]) + "</h4>"
            )
            body.append(
                values(
                    {
                        "qualified_ref": claim["qualified_ref"],
                        "formal": claim["operational_formal_state"],
                        "review": claim["review_state"],
                        "current_policy": claim["current_policy_state"],
                    }
                )
            )
            body.append(
                "<h5>Original source</h5><pre>" + html.escape(claim["source"]["text"]) + "</pre>"
            )
            body.append(
                values({"source_locator": claim["source"]["locator"], "context": claim["context"]})
            )
            from ..paper_reports import _anchor

            body.append(
                '<a href="'
                + paper["report_path"]
                + "#"
                + _anchor("claim", claim["id"])
                + '">Formal statement, exact evidence, review and next actions</a></article>'
            )
            for packet in model["handoffs"]:
                if packet.get("target") == claim["qualified_ref"]:
                    body.append(
                        '<a href="review-packets/'
                        + packet["id"]
                        + '.html">Exact reviewer packet</a>'
                    )
            md += [
                "## " + markdown_text(selection["paper_id"] + " / " + claim["title"]),
                "",
                "Formal: "
                + claim["operational_formal_state"]
                + "; current policy: "
                + claim["current_policy_state"],
                "",
            ]
            md += [
                "[Source, formal statement, evidence and reviews](" + paper["report_path"] + ")",
                "",
            ]
            from ..paper_reports import _pairs

            md += [
                "- " + markdown_text(key) + ": " + markdown_text(value)
                for key, value in _pairs(
                    {
                        "qualified_ref": claim["qualified_ref"],
                        "original_source": claim["source"],
                        "context": claim["context"],
                        "formalization": claim["formal"],
                        "execution": claim["evidence"],
                        "review_decisions": claim["reviews"],
                    }
                )
            ]
            md.append("")
    body.append('<h2 id="tasks">Operational tasks and attempts</h2>')
    from ..paper_reports import _anchor

    for task in model["tasks"]:
        body.append(
            '<article id="task-'
            + task["id"]
            + '"><h3>Task '
            + html.escape(task["id"][:12])
            + "</h3>"
            + values(task)
        )
        subject = task.get("subject", task.get("target", {}))
        assertion = (
            subject.get("assertion_id", subject.get("id")) if isinstance(subject, dict) else None
        )
        for paper in all_papers:
            for claim in paper["claims"]:
                if (
                    assertion == claim["id"]
                    and subject.get("run_id", task.get("run_id")) == paper["selection"]["run_id"]
                ):
                    body.append(
                        '<a href="#'
                        + claim["anchor"]
                        + '">Exact source target</a> · <a href="'
                        + paper["report_path"]
                        + "#"
                        + _anchor("claim", claim["id"])
                        + '">Binding, execution and reviews</a>'
                    )
        body.append("<pre>proofmap campaign tasks " + html.escape(campaign_id) + "</pre></article>")
    body.append('<h2 id="boundary">Qualified boundary ledger</h2>')
    for node in model["graph"]["nodes"]:
        body.append(
            '<p><a href="'
            + node["href"]
            + '">'
            + html.escape(node["title"])
            + "</a>: "
            + html.escape(node["formal_state"])
            + " / "
            + html.escape(node["assessment"])
            + "</p>"
        )
    for edge in model["graph"]["edges"]:
        body.append(values(edge))
        for endpoint in (edge["from"], edge["to"]):
            if endpoint in {n["id"] for n in model["graph"]["nodes"]}:
                body.append('<a href="#' + endpoint + '">Relation endpoint</a> ')
    body.append(
        '<h2 id="history">Immutable historical snapshots</h2>'
        + values(model["historical_snapshots"])
    )
    body.append(
        "<h2>Explicit review command</h2><p>Choose the decision, dimension and reviewer identity after inspecting the packet. The immutable claim remains unchanged.</p><pre>proofmap campaign review-decision "
        + html.escape(campaign_id)
        + " --run RUN_ID --assertion CLAIM_ID --execution-profile profile.json --dimension source-fidelity --decision DECISION --reviewer-id REVIEWER --reason REASON --out decision.json</pre>"
    )
    document = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src \'none\'; base-uri \'none\'; form-action \'none\'"><meta name="viewport" content="width=device-width"><title>ProofMap campaign dossier</title><style>body{font:16px system-ui;max-width:1000px;margin:2rem auto;padding:1rem}pre,dd{white-space:pre-wrap;overflow-wrap:anywhere}dt{font-weight:bold}article{border-top:1px solid #bbb;padding:1rem 0}a{color:#164ca1}nav a{margin-right:1rem}</style></head><body>'
        + "\n".join(body)
        + "</body></html>"
    )
    atomic_write(out / "campaign-report.html", document)
    from ..paper_reports import _pairs

    for title, key in (
        ("Goals", "goals"),
        ("Retained plans, ranking, blockers and assumptions", "planning"),
        ("Operational task lifecycle and resources", "tasks"),
        ("Candidate cross-paper relations", "relations"),
        ("Review handoffs", "handoffs"),
        ("Historical snapshots", "historical_snapshots"),
        ("Snapshot publication", "snapshot_publication"),
    ):
        md += ["## " + title, ""]
        md += [
            "- " + markdown_text(label) + ": " + markdown_text(value)
            for label, value in _pairs(model[key])
        ]
        md.append("")
    atomic_write(out / "campaign-report.md", "\n".join(md))
    return model
