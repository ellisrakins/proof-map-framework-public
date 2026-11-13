"""Evidence-action planning, never an execution or acceptance boundary.

Counterfactual witnesses assume successful future actions. They are deliberately
not kernel evidence, signed receipts, assessments, or empirical predictions.
Cached paper acceptance records are not an authority input to this module.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from importlib.resources import files
from math import isfinite
from typing import Any, cast

from .integrity import canonical_bytes, digest, strict_loads
from .kernel import POLICIES, KernelMap, closure

VERSION = "1.0"
HEURISTIC = {"name": "conditional-closure-planning", "version": "1"}
LIMIT = 10_000


def _record(kind: str, **fields: Any) -> dict[str, Any]:
    value = {"schema_version": VERSION, "kind": kind, "authority": "PLANNING_ONLY", **fields}
    value["id"] = digest("action-planning.v1", value)
    return cast(dict[str, Any], strict_loads(canonical_bytes(value)))


def validate_action_record(value: dict[str, Any]) -> None:
    """Validate packaged shape, identity and internal references, not authority."""
    from jsonschema import Draft202012Validator

    schema = strict_loads(
        files("proofmap.resources").joinpath("action-planning.schema.json").read_bytes()
    )
    canonical_bytes(value)
    if not isinstance(value, dict) or list(Draft202012Validator(schema).iter_errors(value)):
        raise ValueError("ACTION_RECORD_SCHEMA")
    if value["id"] != digest("action-planning.v1", {k: v for k, v in value.items() if k != "id"}):
        raise ValueError("ACTION_RECORD_IDENTITY")
    if value["kind"] == "EVIDENCE_ACTION_REQUEST":
        _request_time(value["requested_at"])
        if not value["actor"].strip():
            raise ValueError("ACTION_REQUEST_ACTOR")
        return
    if value["kind"] == "ACTION_COUNTERFACTUAL":
        selected = set(value["selected_actions"])
        hypothetical = set(value["hypothetical"]["closed"])
        witnesses = value["hypothetical"]["witnesses"]
        actual = value["actual"]
        actual_ids = set(actual.get("closed", actual.get("accepted", [])))
        if (
            set(witnesses) != hypothetical
            or set(value["delta"]) != hypothetical - actual_ids
            or set(value["assumptions"]) != selected
            or set(value["blocked_actions"]) - selected
            or any(
                set(w["actions"]) - selected or set(w["actions"]) & value["blocked_actions"].keys()
                for w in witnesses.values()
            )
        ):
            raise ValueError("ACTION_COUNTERFACTUAL_BINDING")
        return
    actual = value["actual"]
    if value["domain"] == "kernel":
        if (
            actual.get("graph_digest") != value["subject_digest"]
            or actual.get("policy_digest") != value["policy"]
        ):
            raise ValueError("ACTION_CLOSURE_BINDING")
    else:
        if "authority_evaluated" not in actual or set(actual["accepted"]) - set(actual["verified"]):
            raise ValueError("ACTION_ASSESSMENT_BINDING")
        if not actual["authority_evaluated"] and (
            actual["verified"] or actual["accepted"] or actual["assessments"]
        ):
            raise ValueError("ACTION_AUTHORITY_NOT_EVALUATED")
    actions = {a["id"]: a for a in value["actions"]}
    if len(actions) != len(value["actions"]):
        raise ValueError("ACTION_DUPLICATE_ID")
    for action in actions.values():
        if action["id"] != digest(
            "evidence-action.v1", {k: v for k, v in action.items() if k != "id"}
        ):
            raise ValueError("ACTION_IDENTITY")
        if set(action["prerequisites"]) - actions.keys():
            raise ValueError("ACTION_DANGLING_PREREQUISITE")
        if action["policy"] != value["policy"] or action["condition"] not in action["assumptions"]:
            raise ValueError("ACTION_POLICY_OR_ASSUMPTIONS")
    pending = {aid: len(a["prerequisites"]) for aid, a in actions.items()}
    reverse: dict[str, list[str]] = {aid: [] for aid in actions}
    for aid, action in actions.items():
        for prerequisite in action["prerequisites"]:
            reverse[prerequisite].append(aid)
    queue = deque(aid for aid, count in pending.items() if count == 0)
    visited = 0
    while queue:
        visited += 1
        for aid in reverse[queue.popleft()]:
            pending[aid] -= 1
            if pending[aid] == 0:
                queue.append(aid)
    if visited != len(actions):
        raise ValueError("ACTION_PREREQUISITE_CYCLE")


def _action(
    kind: str,
    subject: dict[str, str],
    context: str,
    policy: str,
    *,
    artifact: str,
    mode: str,
    condition: str,
    reasons: Iterable[str],
    effect: str,
    target: str,
    prerequisites: Iterable[str] = (),
) -> dict[str, Any]:
    value = {
        "kind": kind,
        "subject": subject,
        "context": context,
        "policy": policy,
        "required_artifact": artifact,
        "mode": mode,
        "prerequisites": sorted(set(prerequisites)),
        "assumptions": [condition],
        "condition": condition,
        "reason_codes": sorted(set(reasons)),
        "effect": effect,
        "target": target,
        "estimated_cost": None,
        "expected_gain": None,
        "heuristic": dict(HEURISTIC),
    }
    value["id"] = digest("evidence-action.v1", value)
    return value


def _plan(
    domain: str, subject: str, policy: str, actual: dict[str, Any], actions: list[dict[str, Any]]
) -> dict[str, Any]:
    if len(actions) > LIMIT:
        raise ValueError("ACTION_RESOURCE_LIMIT")
    value = _record(
        "EVIDENCE_ACTION_PLAN",
        domain=domain,
        subject_digest=subject,
        policy=policy,
        heuristic=dict(HEURISTIC),
        actual=actual,
        actions=sorted(actions, key=lambda a: (a["subject"]["id"], a["kind"], a["id"])),
    )
    validate_action_record(value)
    return value


def plan_evidence_actions(
    graph: KernelMap,
    *,
    policy: str = "deductive-strict-v1",
    foundations: Iterable[tuple[str, str]] = (),
    assumptions: Iterable[tuple[str, str]] = (),
    trusted_evidence: Iterable[str] = (),
) -> dict[str, Any]:
    """Derive exact proposed repairs from the current kernel closure failures.

    As with kernel.closure, trusted_evidence is provided by the caller's real
    authentication boundary, never from authored graph labels or this planner.
    """
    actual = closure(
        graph,
        policy=policy,
        foundations=foundations,
        assumptions=assumptions,
        trusted_evidence=trusted_evidence,
    )
    if len(graph.claims) + len(graph.inferences) > LIMIT:
        raise ValueError("ACTION_RESOURCE_LIMIT")
    claims = {c.id: c for c in graph.claims}
    contexts = {c.id: asdict(c) for c in graph.contexts}
    actions = []
    missing_premises = {p for values in actual.unresolved_premises.values() for p in values}
    needed = set(missing_premises)
    conclusions = {i.conclusion for i in graph.inferences}
    needed.update(c for c in actual.open if c not in conclusions)
    for cid in sorted(needed):
        claim = claims[cid]
        safe = claim.scope == "global" and claim.status not in {"GAP", "BLOCKED", "REJECTED"}
        actions.append(
            _action(
                "PROVE_PREMISE",
                {
                    "kind": "claim",
                    "id": cid,
                    "digest": digest(
                        "action-claim.v1",
                        {
                            "claim": asdict(claim),
                            "context": contexts[claim.context],
                        },
                    ),
                },
                claim.context,
                actual.policy_digest,
                artifact="independently authenticated claim evidence",
                mode="verifier accepted by " + policy,
                condition=f"A new independent proof establishes exact claim {cid} in its unchanged context under {policy}; no foundation is declared.",
                reasons=["MISSING_PREMISE" if cid in missing_premises else "MISSING_DERIVATION"],
                effect="ASSUME_CLAIM" if safe and POLICIES[policy].modes else "NONE",
                target=cid,
            )
        )
    generic = "MISSING_STALE_OR_UNTRUSTED_EVIDENCE"
    evidence_codes = {
        "MISSING_EVIDENCE",
        "STALE_EVIDENCE_BINDING",
        "INVALID_EVIDENCE_OUTCOME",
        "UNTRUSTED_EVIDENCE",
        generic,
    }
    for inference in sorted(graph.inferences, key=lambda i: i.id):
        if inference.conclusion in actual.closed:
            continue
        reasons = set(actual.evidence_issues.get(inference.id, ()))
        subject = {
            "kind": "inference",
            "id": inference.id,
            "digest": graph.inference_digest(inference),
        }
        evidence_reasons = reasons & evidence_codes
        if evidence_reasons:
            if len(evidence_reasons) > 1:
                evidence_reasons.discard(generic)
            kind = (
                "COMPUTATIONAL_REPRODUCTION"
                if inference.mode in {"COMPUTATIONAL", "EMPIRICAL"}
                else "VERIFY_INFERENCE"
            )
            if evidence_reasons == {"UNTRUSTED_EVIDENCE"}:
                kind = "AUTHENTICATE_EVIDENCE"
            elif "STALE_EVIDENCE_BINDING" in evidence_reasons:
                kind = "REFRESH_EVIDENCE"
            actions.append(
                _action(
                    kind,
                    subject,
                    inference.context,
                    actual.policy_digest,
                    artifact="current exact-subject authenticated "
                    + inference.mode.lower()
                    + " evidence",
                    mode=inference.mode,
                    condition=f"Current independently authenticated PASS evidence matches inference {inference.id}, its context and policy.",
                    reasons=evidence_reasons,
                    effect="CERTIFY_INFERENCE",
                    target=inference.id,
                )
            )
        for reason in sorted(reasons - evidence_codes):
            context_issue = reason in {"UNVERIFIED_SCOPE_DISCHARGE", "UNACCEPTED_EXTRA_ASSUMPTION"}
            permissible = reason == "CONCLUSION_BLOCKED" or (
                reason == "INFERENCE_NOT_ACCEPTABLE_UNDER_POLICY"
                and inference.mode in POLICIES[policy].modes
            )
            actions.append(
                _action(
                    "RESOLVE_CONTEXT" if context_issue else "RESOLVE_INFERENCE",
                    subject,
                    inference.context,
                    actual.policy_digest,
                    artifact="checked scoped obligation"
                    if context_issue
                    else "independent inference eligibility review",
                    mode="supported-context-check" if context_issue else "independent-review",
                    condition=f"Independent checking resolves {reason} for exact inference {inference.id}; unsupported context transformations require a new graph and plan.",
                    reasons=[reason],
                    effect="CLEAR_ISSUE" if permissible else "NONE",
                    target=inference.id,
                )
            )
    return _plan("kernel", actual.graph_digest, actual.policy_digest, actual.to_dict(), actions)


def _selected(
    plan: dict[str, Any], action_ids: Iterable[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    ids = list(action_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("ACTION_DUPLICATE_SELECTION")
    actions = {a["id"]: a for a in plan["actions"]}
    if set(ids) - actions.keys():
        raise ValueError("ACTION_UNKNOWN_OR_STALE_SELECTION")
    chosen = {aid: actions[aid] for aid in ids}
    blocked = {
        aid: sorted(set(a["prerequisites"]) - chosen.keys())
        for aid, a in chosen.items()
        if set(a["prerequisites"]) - chosen.keys()
    }
    # A selected but blocked prerequisite cannot make a dependent runnable.
    reverse: dict[str, list[str]] = {aid: [] for aid in chosen}
    for aid, action in chosen.items():
        for prerequisite in set(action["prerequisites"]) & chosen.keys():
            reverse[prerequisite].append(aid)
    queue = deque(sorted(blocked))
    while queue:
        prerequisite = queue.popleft()
        for aid in reverse[prerequisite]:
            if aid not in blocked:
                blocked[aid] = [prerequisite]
                queue.append(aid)
    return {aid: a for aid, a in chosen.items() if aid not in blocked}, blocked


def _scenario(
    plan: dict[str, Any],
    ids: list[str],
    hypothetical: list[str],
    witnesses: dict[str, Any],
    blocked: dict[str, list[str]],
    *,
    actual_ids: list[str],
) -> dict[str, Any]:
    selected = {a["id"]: a for a in plan["actions"] if a["id"] in ids}
    value = _record(
        "ACTION_COUNTERFACTUAL",
        plan_id=plan["id"],
        subject_digest=plan["subject_digest"],
        selected_actions=sorted(ids),
        actual=deepcopy(plan["actual"]),
        hypothetical={"closed": sorted(hypothetical), "witnesses": witnesses},
        delta=sorted(set(hypothetical) - set(actual_ids)),
        blocked_actions=blocked,
        assumptions={aid: a["assumptions"] for aid, a in sorted(selected.items())},
        execution="NOT_RUN",
        expected_gain=None,
        estimated_cost=None,
    )
    validate_action_record(value)
    return value


def simulate_evidence_actions(
    graph: KernelMap, action_ids: Iterable[str], **authority: Any
) -> dict[str, Any]:
    """Evaluate a distinct counterfactual fixed point; never call a verifier."""
    ids = list(action_ids)
    plan = plan_evidence_actions(graph, **authority)
    if plan["actual"]["truncated"]:
        raise ValueError("ACTION_CLOSURE_INCOMPLETE")
    chosen, blocked = _selected(plan, ids)
    witnesses: dict[str, dict[str, list[str]]] = {
        cid: {"actions": [], "inferences": []} for cid in plan["actual"]["closed"]
    }
    for aid, action in chosen.items():
        if action["effect"] == "ASSUME_CLAIM":
            witnesses[action["target"]] = {"actions": [aid], "inferences": []}
    repaired: dict[str, set[str]] = {}
    certifications: dict[str, str] = {}
    for aid, action in chosen.items():
        if action["effect"] == "CERTIFY_INFERENCE":
            certifications[action["target"]] = aid
        elif action["effect"] == "CLEAR_ISSUE":
            repaired.setdefault(action["target"], set()).update(action["reason_codes"])
    used_by_target: dict[str, set[str]] = {}
    for aid, action in chosen.items():
        if action["effect"] == "CLEAR_ISSUE":
            used_by_target.setdefault(action["target"], set()).add(aid)
    pending = deque(sorted(graph.inferences, key=lambda i: i.id))
    queued = {i.id for i in pending}
    reverse_inferences: dict[str, list[Any]] = {}
    for inference in graph.inferences:
        for premise in set(inference.premises):
            reverse_inferences.setdefault(premise, []).append(inference)
    witness_size = 0
    while pending:
        inference = pending.popleft()
        queued.discard(inference.id)
        if inference.conclusion in witnesses or any(p not in witnesses for p in inference.premises):
            continue
        reasons = set(plan["actual"]["evidence_issues"].get(inference.id, ()))
        used = set(used_by_target.get(inference.id, ()))
        reasons -= repaired.get(inference.id, set())
        if inference.id in certifications:
            reasons -= {
                "MISSING_EVIDENCE",
                "STALE_EVIDENCE_BINDING",
                "INVALID_EVIDENCE_OUTCOME",
                "UNTRUSTED_EVIDENCE",
                "MISSING_STALE_OR_UNTRUSTED_EVIDENCE",
            }
            used.add(certifications[inference.id])
        # Research assumptions never become unconditional accepted premises.
        if reasons or inference.assumptions:
            continue
        inherited = [witnesses[p] for p in inference.premises]
        witnesses[inference.conclusion] = {
            "actions": sorted(used | {a for w in inherited for a in w["actions"]}),
            "inferences": sorted({inference.id} | {i for w in inherited for i in w["inferences"]}),
        }
        witness_size += sum(len(v) for v in witnesses[inference.conclusion].values())
        if witness_size > 200_000:
            raise ValueError("ACTION_WITNESS_RESOURCE_LIMIT")
        for dependent in reverse_inferences.get(inference.conclusion, []):
            if dependent.id not in queued:
                pending.append(dependent)
                queued.add(dependent.id)
    return _scenario(
        plan, ids, list(witnesses), witnesses, blocked, actual_ids=plan["actual"]["closed"]
    )


def plan_paper_actions(
    bundle: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
    trust_store: dict[str, Any] | None = None,
    evaluation_time: str | None = None,
    reviews: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Plan source/formal evidence work; recheck authority only when supplied.

    Offline plans mark current authority unknown. Stored acceptance labels and
    worker event outcomes never substitute for current authenticated assessment.
    """
    from .attempts import FormalObligation
    from .evidence_adapter import POLICY, assess_binding
    from .evidence_records import FormalizationBinding, VerifierProfile

    canonical_bytes(bundle)
    supplied = (profile is not None, trust_store is not None, evaluation_time is not None)
    if any(supplied) and not all(supplied):
        raise ValueError("ACTION_AUTHORITY_INPUTS_INCOMPLETE")
    revision = bundle["input_manifest"]["revision"]
    assertions = {a["id"]: a for a in bundle["assertions"]}
    if len(assertions) != len(bundle["assertions"]) or len(assertions) > LIMIT:
        raise ValueError("ACTION_ASSERTION_IDS")
    events = {row["event"]["id"]: row for row in bundle.get("execution_events", [])}
    if len(events) != len(bundle.get("execution_events", [])):
        raise ValueError("ACTION_EVENT_IDS")
    selected_profile = VerifierProfile.from_dict(profile) if profile is not None else None
    reviews = list(reviews)
    policy_digest = digest("acceptance-policy.v1", POLICY)
    actual: dict[str, Any] = {
        "authority_evaluated": all(supplied),
        "verified": [],
        "accepted": [],
        "unknown": [],
        "assessments": [],
    }
    actions = []
    subjects = []
    seen: set[str] = set()
    for row in bundle.get("formalizations", []):
        cid = row["assertion_id"]
        if cid not in assertions or cid in seen or assertions[cid]["revision"] != revision:
            raise ValueError("ACTION_SOURCE_BINDING")
        seen.add(cid)
        if row["status"] != "SUPPORTED":
            actions.append(
                _action(
                    "RESOLVE_CONTEXT",
                    {
                        "kind": "assertion",
                        "id": cid,
                        "digest": digest("assertion.v1", assertions[cid]),
                    },
                    assertions[cid]["scope"],
                    policy_digest,
                    artifact="supported anchored source interpretation and formal obligation",
                    mode="source-interpretation-review",
                    condition="A supported exact source interpretation is established; rerun formalization and create a new plan before predicting acceptance.",
                    reasons=["FORMALIZATION_UNSUPPORTED"],
                    effect="NONE",
                    target=cid,
                )
            )
            actual["unknown"].append(cid)
            subjects.append({"assertion": assertions[cid], "formalization": row})
            continue
        binding = FormalizationBinding.from_dict(row["binding"])
        obligation = FormalObligation.from_dict(row["obligation"])
        if (
            binding.assertion_id != cid
            or binding.revision_id != revision
            or binding.assertion_digest != digest("assertion.v1", assertions[cid])
        ):
            raise ValueError("ACTION_SOURCE_BINDING")
        from .evidence_records import obligation_identity

        if binding.obligation_digest != obligation_identity(obligation):
            raise ValueError("ACTION_OBLIGATION_BINDING")
        subject = {"kind": "formalization", "id": cid, "digest": binding.digest}
        event = events.get(row.get("execution_event", ""), {})
        history = row.get("historical_execution")
        record = None
        if selected_profile is not None and trust_store is not None and evaluation_time is not None:
            from .trust import authenticated_record

            relevant_reviews: list[Mapping[str, Any]] = []
            for review in reviews:
                try:
                    subject_id = authenticated_record(review).get("assertion_id")
                except ValueError:
                    subject_id = cid  # retain malformed input as a visible rejection
                if subject_id == cid:
                    relevant_reviews.append(review)
            record = assess_binding(
                binding,
                obligation,
                selected_profile,
                event.get("envelope"),
                relevant_reviews,
                trust_store,
                evaluation_time=evaluation_time,
                historical_execution=history,
            ).to_dict()
            actual["assessments"].append(
                {
                    k: record[k]
                    for k in (
                        "assertion_id",
                        "binding_digest",
                        "formal_status",
                        "source_fidelity",
                        "formal_fidelity",
                        "assessment",
                        "reasons",
                    )
                }
            )
            if record["formal_status"] == "VERIFIED":
                actual["verified"].append(cid)
            if record["assessment"] == "ACCEPTED_UNDER_POLICY":
                actual["accepted"].append(cid)
        else:
            actual["unknown"].append(cid)
        subjects.append(
            {
                "binding": binding.to_dict(),
                "event": event,
                "historical_execution": history,
                "assessment": record,
            }
        )
        prerequisite = []
        if record is None or record["formal_status"] != "VERIFIED":
            action = _action(
                "AUTHENTICATE_EVIDENCE"
                if event.get("envelope") or history is not None
                else "VERIFY_FORMAL_SUBJECT",
                subject,
                binding.context_digest,
                policy_digest,
                artifact="current authenticated isolated execution with exact binding and pinned profile",
                mode=str(POLICY["verification_profile"]),
                condition=f"Current authority validates a successful isolated execution of exact formal subject {binding.obligation_digest}.",
                reasons=record["reasons"]
                if record
                else [
                    "CURRENT_AUTHORITY_NOT_EVALUATED"
                    if event or history is not None
                    else "MISSING_EXECUTION"
                ],
                effect="VERIFY_FORMAL",
                target=cid,
            )
            actions.append(action)
            prerequisite = [action["id"]]
        for dimension in ("source_fidelity", "formal_fidelity"):
            if record is not None and record[dimension] == "APPROVE" and not record["reasons"]:
                continue
            action = _action(
                dimension.upper() + "_REVIEW",
                subject,
                binding.context_digest,
                policy_digest,
                artifact="authenticated "
                + dimension.replace("_", "-")
                + " review of exact source/formal binding",
                mode=dimension.replace("_", "-") + "-review",
                condition=f"An authorized independent reviewer approves {dimension} for binding {binding.digest}; conflicting, stale and rejected decisions are explicitly reconciled.",
                reasons=["MISSING_" + dimension.upper() + "_REVIEW"]
                if record is None
                else [dimension.upper() + ":" + record[dimension], *record["reasons"]],
                effect=dimension.upper(),
                target=cid,
                prerequisites=prerequisite,
            )
            actions.append(action)
    for key in ("verified", "accepted", "unknown"):
        actual[key].sort()
    actual["assessments"].sort(key=lambda r: r["assertion_id"])
    subject_digest = digest(
        "paper-action-subject.v1",
        {
            "revision": revision,
            "subjects": sorted(subjects, key=lambda s: canonical_bytes(s)),
            "profile": profile,
            "evaluation_time": evaluation_time,
            "trust_store": trust_store,
            "reviews": sorted(reviews, key=lambda r: canonical_bytes(r)),
        },
    )
    return _plan("paper", subject_digest, policy_digest, actual, actions)


def simulate_paper_actions(
    bundle: dict[str, Any], action_ids: Iterable[str], **authority: Any
) -> dict[str, Any]:
    ids = list(action_ids)
    plan = plan_paper_actions(bundle, **authority)
    chosen, blocked = _selected(plan, ids)
    accepted = set(plan["actual"]["accepted"])
    witnesses: dict[str, dict[str, list[str]]] = {
        cid: {"actions": [], "inferences": []} for cid in accepted
    }
    rows = {r["assertion_id"]: r for r in plan["actual"]["assessments"]}
    targets = {a["target"] for a in chosen.values() if a["effect"] != "NONE"}
    for cid in sorted(targets - accepted):
        effects = {a["effect"] for a in chosen.values() if a["target"] == cid}
        row = rows.get(cid)
        verified = cid in plan["actual"]["verified"] or "VERIFY_FORMAL" in effects
        source = (
            row is not None and row["source_fidelity"] == "APPROVE" and not row["reasons"]
        ) or "SOURCE_FIDELITY" in effects
        formal = (
            row is not None and row["formal_fidelity"] == "APPROVE" and not row["reasons"]
        ) or "FORMAL_FIDELITY" in effects
        if verified and source and formal:
            accepted.add(cid)
            witnesses[cid] = {
                "actions": sorted(aid for aid, a in chosen.items() if a["target"] == cid),
                "inferences": [],
            }
    return _scenario(
        plan, ids, sorted(accepted), witnesses, blocked, actual_ids=plan["actual"]["accepted"]
    )


def _request_time(requested_at: str) -> None:
    try:
        when = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("ACTION_REQUEST_TIME") from exc
    if when.tzinfo is None:
        raise ValueError("ACTION_REQUEST_TIME")


def request_action(
    plan: dict[str, Any], action_id: str, *, actor: str, requested_at: str
) -> dict[str, Any]:
    """Make an auditable request only; no execution, signing, or store mutation."""
    validate_action_record(plan)
    if plan["kind"] != "EVIDENCE_ACTION_PLAN" or action_id not in {
        a["id"] for a in plan["actions"]
    }:
        raise ValueError("ACTION_UNKNOWN_OR_STALE_SELECTION")
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 512:
        raise ValueError("ACTION_REQUEST_ACTOR")
    _request_time(requested_at)
    value = _record(
        "EVIDENCE_ACTION_REQUEST",
        plan_id=plan["id"],
        subject_digest=plan["subject_digest"],
        action_id=action_id,
        actor=actor,
        attribution_authenticated=False,
        requested_at=requested_at,
        status="REQUESTED",
        execution="NOT_RUN",
        event_ids=[],
    )
    validate_action_record(value)
    return value


def rank_evidence_actions(
    plan: dict[str, Any], *, costs: Mapping[str, float] | None = None
) -> list[dict[str, Any]]:
    """Rank declared blocker counts; supplied effort is not a probability/value.

    Unknown costs and expected empirical gains remain null. Known effort uses
    caller-defined comparable units, recorded as supplied estimates, not facts.
    """
    validate_action_record(plan)
    if plan["kind"] != "EVIDENCE_ACTION_PLAN":
        raise ValueError("ACTION_PLAN_REQUIRED")
    costs = dict(costs or {})
    if set(costs) - {a["id"] for a in plan["actions"]}:
        raise ValueError("ACTION_UNKNOWN_COST_SUBJECT")
    for cost in costs.values():
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not isfinite(cost)
            or cost < 0
        ):
            raise ValueError("ACTION_INVALID_COST")
    rows = []
    for action in plan["actions"]:
        rows.append(
            {
                "action": deepcopy(action),
                "heuristic": dict(HEURISTIC),
                "blocking_conditions": len(action["reason_codes"]),
                "prerequisite_count": len(action["prerequisites"]),
                "expected_gain": None,
                "estimated_cost": costs.get(action["id"]),
                "cost_basis": "caller-estimated effort units"
                if action["id"] in costs
                else "UNKNOWN",
                "score": None,
            }
        )
    return sorted(
        rows,
        key=lambda r: (
            r["prerequisite_count"],
            -r["blocking_conditions"],
            r["estimated_cost"] is None,
            r["estimated_cost"] or 0,
            r["action"]["id"],
        ),
    )
