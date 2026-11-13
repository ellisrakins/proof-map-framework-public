"""Campaign orchestration of existing paper planners, execution and trust APIs.

Operator authorization allows bounded work, never fidelity approval. Historical
paper runs remain immutable; new evidence is appended to the existing audit CAS.
"""

from __future__ import annotations

import html
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Any, cast

from ..attempts import FormalObligation
from ..evidence_adapter import POLICY, assess_binding, assessment_records
from ..evidence_records import FormalizationBinding, VerifierProfile
from ..integrity import canonical_bytes, digest, load_json, relative_path, write_json
from ..paper_actions import plan_paper_actions, request_action, validate_action_record
from ..paper_sources import source_validation_operation
from . import queue
from .inventory import unresolved_region_count
from .models import qualified_ref, record, validate_record

AUTOMATIC = {
    "VERIFY_FORMAL_SUBJECT",
    "AUTHENTICATE_EVIDENCE",
    "REFRESH_EVIDENCE",
    "REASSESS_POLICY",
    "EXACT_COMPUTATION",
    "ANALYZE_SOURCE",
    "FORMALIZE_SUPPORTED",
    "REFRESH_REPORT",
    "INGEST_SOURCE",
    "REPARSE_SOURCE",
    "EXTRACT_RECORDED",
    "EXTRACT_CONFIGURED",
}
HUMAN = {"SOURCE_FIDELITY_REVIEW", "FORMAL_FIDELITY_REVIEW", "RESOLVE_CONTEXT", "REVIEW_BRIDGE"}
SOURCE_STAGES = {"INGEST_SOURCE", "REPARSE_SOURCE", "EXTRACT_RECORDED", "EXTRACT_CONFIGURED"}


def _bundle(store: Any, run_id: str) -> dict[str, Any]:
    return cast(dict[str, Any], store.inspect(run_id)["bundle"])


def _events(store: Any, bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Retain fresh audited execution in addition to original immutable evidence."""
    events = list(bundle.get("execution_events", []))
    events.extend(
        {"event": row["record"], "envelope": row.get("envelope")}
        for row in store.list_audit(bundle["run_manifest"]["run_id"], "ExecutionEvent")
    )
    return list({e["event"]["id"]: e for e in events}.values())


def _view(store: Any, bundle: dict[str, Any]) -> dict[str, Any]:
    view = deepcopy(bundle)
    view["execution_events"] = _events(store, bundle)
    by_binding = {e["event"]["binding_digest"]: e for e in view["execution_events"]}
    for row in view.get("formalizations", []):
        event = by_binding.get(row.get("binding", {}).get("id"))
        if event is not None:
            row["execution_event"] = event["event"]["id"]
            if event.get("envelope") is not None:
                # A derived current view selects one evidence path. The original
                # immutable row retains its historical execution for audit.
                row.pop("historical_execution", None)
    return view


def _goal_ref(goal: dict[str, Any]) -> dict[str, Any] | None:
    return goal.get("target") or goal.get("claim") or goal.get("qualified_claim")


@source_validation_operation
def plan_campaign(
    store: Any,
    campaign_id: str,
    formal_scope: str = "supported",
    profile: dict[str, Any] | None = None,
    trust_store: dict[str, Any] | None = None,
    evaluation_time: str | None = None,
) -> dict[str, Any]:
    """Aggregate the established PLANNING_ONLY planner; no execution or approval."""
    if formal_scope not in {"supported", "selected", "all"}:
        raise ValueError("CAMPAIGN_FORMAL_SCOPE")
    if (trust_store is not None or evaluation_time is not None) and not (
        profile is not None and trust_store is not None and evaluation_time is not None
    ):
        raise ValueError("CAMPAIGN_AUTHORITY_INPUTS_INCOMPLETE")
    snapshot = store.current_snapshot(campaign_id)
    goals = [store.get_record(g) if isinstance(g, str) else g for g in snapshot["goals"]]
    refs = [(g, _goal_ref(g)) for g in goals]
    targets = {(r["run_id"], r["assertion_id"]) for _, r in refs if r}
    actions, papers, blockers = [], [], []
    goal_by_target: dict[tuple[str, str], list[str]] = {}
    for g, ref in refs:
        if ref:
            if canonical_bytes(ref) != canonical_bytes(
                qualified_ref(store, ref["run_id"], ref["assertion_id"])
            ):
                raise ValueError("CAMPAIGN_GOAL_BINDING_STALE")
            goal_by_target.setdefault((ref["run_id"], ref["assertion_id"]), []).append(g["id"])
            if not any(s["run_id"] == ref["run_id"] for s in snapshot["selections"]):
                blockers.append(
                    {
                        "goal_id": g["id"],
                        "target": ref,
                        "code": "UNRESOLVED_TARGET",
                        "reason": "The exact goal refers to a historical run outside selected membership; explicit rebinding is required.",
                    }
                )
        else:
            blockers.append(
                {
                    "goal_id": g["id"],
                    "code": "UNANCHORED_RESEARCH_QUESTION",
                    "statement_origin": "RESEARCHER_QUESTION",
                }
            )
    for selection in snapshot["selections"]:
        run_id = selection["run_id"]
        bundle = _bundle(store, run_id)
        reviews = [
            r["envelope"] for r in store.list_audit(run_id, "ReviewDecision") if r.get("envelope")
        ]
        pp = plan_paper_actions(
            _view(store, bundle),
            profile=profile if trust_store is not None else None,
            trust_store=trust_store,
            evaluation_time=evaluation_time,
            reviews=reviews,
        )
        by_id = {r["assertion_id"]: r for r in bundle.get("formalizations", [])}
        supported = {c for c, r in by_id.items() if r["status"] == "SUPPORTED"}
        selected = {c for run, c in targets if run == run_id}
        eligible = (
            supported
            if formal_scope == "supported"
            else selected
            if formal_scope == "selected"
            else set(by_id)
        )
        if targets and formal_scope == "supported":
            eligible &= selected
        for cid in sorted(set(by_id) - supported):
            blockers.append(
                {
                    "run_id": run_id,
                    "assertion_id": cid,
                    "code": "FORMALIZATION_UNSUPPORTED",
                    "reason": by_id[cid].get("reason", "unsupported"),
                    "selected_blocker": formal_scope == "all" or cid in selected,
                }
            )
        for action in pp["actions"]:
            if action["target"] not in eligible:
                continue
            ref = qualified_ref(store, run_id, action["target"])
            wrapper = {
                "paper_action": action,
                "paper_plan": pp["id"],
                "target": ref,
                "goal_ids": sorted(goal_by_target.get((run_id, action["target"]), [])),
                "adapter": "HUMAN_REVIEW" if action["kind"] in HUMAN else action["kind"],
                "estimated_cost": None,
                "cost_basis": "UNKNOWN",
                "required_evidence": action["required_artifact"],
            }
            wrapper["id"] = digest("campaign-action.v1", wrapper)
            actions.append(wrapper)
        unresolved = unresolved_region_count(bundle.get("interpreted_ir", bundle["document_ir"]))
        papers.append(
            {
                "paper_id": selection["paper_id"],
                "run_id": run_id,
                "revision": selection["revision"],
                "paper_plan": pp,
                "counts": {
                    "discovered": len(bundle["assertions"]),
                    "unresolved_regions": unresolved,
                    "supported": len(supported),
                    "eligible": len(eligible & supported),
                    "attempted": len(_events(store, bundle)),
                    "verified": len(pp["actual"]["verified"]),
                    "reviewed_bindings": sum(
                        a["source_fidelity"] == "APPROVE" and a["formal_fidelity"] == "APPROVE"
                        for a in pp["actual"]["assessments"]
                    ),
                    "accepted": len(pp["actual"]["accepted"]),
                },
            }
        )
    # Retain prerequisite identities across campaign wrappers, without inventing closure.
    mapping = {(a["target"]["run_id"], a["paper_action"]["id"]): a["id"] for a in actions}
    for action in actions:
        action["prerequisites"] = [
            mapping[(action["target"]["run_id"], p)]
            for p in action["paper_action"]["prerequisites"]
            if (action["target"]["run_id"], p) in mapping
        ]
    plan = record(
        "CampaignPlan",
        campaign_id=campaign_id,
        snapshot_id=snapshot["id"],
        authority="PLANNING_ONLY",
        formal_scope=formal_scope,
        actions=sorted(
            actions,
            key=lambda a: (
                len(a["prerequisites"]),
                a["target"]["run_id"],
                a["paper_action"]["kind"],
                a["id"],
            ),
        ),
        papers=papers,
        blockers=blockers,
        ranking_policy="runnable-prerequisites-goal-relevance-v1",
        created_at=queue.utc_now(),
        profile_digest=VerifierProfile.from_dict(profile).digest if profile else None,
        assessment_policy=digest("acceptance-policy.v1", POLICY),
        evaluation_time=evaluation_time,
    )
    store.add_record(plan, campaign_id)
    return plan


def _validate_policy(policy: dict[str, Any]) -> None:
    validate_record(policy)
    if policy["kind"] != "OperationPolicy" or set(policy["allowed_kinds"]) - (AUTOMATIC | HUMAN):
        raise ValueError("CAMPAIGN_POLICY_ADAPTERS")
    if policy.get("concurrency", 1) != 1:
        raise ValueError("CAMPAIGN_CONCURRENCY_PROFILE")
    for name, low, high in (
        ("max_tasks", 0, 10000),
        ("max_wall_seconds", 0, 86400),
        ("max_attempts", 1, 10),
        ("lease_seconds", 1, 3600),
    ):
        if type(policy.get(name)) is not int or not low <= policy[name] <= high:
            raise ValueError("CAMPAIGN_POLICY_BOUND:" + name)


@source_validation_operation
def authorize_plan(
    store: Any,
    campaign_id: str,
    plan: dict[str, Any],
    policy: dict[str, Any],
    actor: str,
    action_ids: list[str] | None = None,
) -> dict[str, Any]:
    """An explicit operator authorization is separate from the pure request."""
    if not actor.strip():
        raise ValueError("CAMPAIGN_AUTHORIZATION_ACTOR")
    validate_record(plan)
    _validate_policy(policy)
    prior = [
        a
        for a in store.records(campaign_id, "OperationAuthorization")
        if a.get("plan_id") == plan["id"]
        and a["policy_id"] == policy["id"]
        and a["actor"] == actor
        and a["action_ids"]
        == sorted(
            action_ids if action_ids is not None else [row["id"] for row in plan.get("actions", [])]
        )
    ]
    if prior:
        authorization = prior[-1]
        selected_tasks = [
            t for t in tasks(store, campaign_id) if t["authorization_id"] == authorization["id"]
        ]
        if selected_tasks and not any(t["state"] in {"STALE", "CANCELLED"} for t in selected_tasks):
            return {
                "authorization": authorization,
                "tasks": [
                    {
                        k: v
                        for k, v in t.items()
                        if k
                        in {
                            "task_id",
                            "state",
                            "generation",
                            "attempt_count",
                            "lease_token",
                            "lease_owner",
                            "lease_until",
                            "attempt_id",
                            "last_result",
                            "usage_seconds",
                            "reserved_seconds",
                            "last_event",
                        }
                    }
                    for t in selected_tasks
                ],
            }
    if (
        plan["kind"] != "CampaignPlan"
        or plan["campaign_id"] != campaign_id
        or plan["snapshot_id"] != store.current_snapshot(campaign_id)["id"]
    ):
        raise ValueError("CAMPAIGN_STALE_PLAN")
    if canonical_bytes(store.get_record(plan["id"])) != canonical_bytes(plan):
        raise ValueError("CAMPAIGN_UNKNOWN_PLAN")
    available = {a["id"]: a for a in plan["actions"]}
    selected = list(available) if action_ids is None else action_ids
    if len(selected) != len(set(selected)) or set(selected) - available.keys():
        raise ValueError("CAMPAIGN_AUTHORIZATION_SELECTION")
    if plan.get("profile_digest") is not None and plan["profile_digest"] != policy.get(
        "profile_digest"
    ):
        raise ValueError("CAMPAIGN_POLICY_PROFILE")
    for action in available.values():
        if canonical_bytes(action["target"]) != canonical_bytes(
            qualified_ref(store, action["target"]["run_id"], action["target"]["assertion_id"])
        ):
            raise ValueError("CAMPAIGN_ACTION_BINDING_STALE")
    store.add_record(policy, campaign_id)
    snapshot = store.current_snapshot(campaign_id)
    if snapshot["operation_policy"] != policy["id"]:
        from .service import snapshot_update

        snapshot = snapshot_update(store, campaign_id, policy=policy, actor=actor)
        stale_tasks(store, campaign_id, actor=actor)
    authorization = record(
        "OperationAuthorization",
        campaign_id=campaign_id,
        plan_id=plan["id"],
        policy_id=policy["id"],
        snapshot_id=snapshot["id"],
        action_ids=sorted(selected),
        actor=actor,
        authorized_at=queue.utc_now(),
    )
    store.add_record(authorization, campaign_id)
    results = []
    for aid in selected:
        action = available[aid]
        ref = action["target"]
        if canonical_bytes(ref) != canonical_bytes(
            qualified_ref(store, ref["run_id"], ref["assertion_id"])
        ):
            raise ValueError("CAMPAIGN_ACTION_BINDING_STALE")
        paper_plan = next(p["paper_plan"] for p in plan["papers"] if p["run_id"] == ref["run_id"])
        validate_action_record(paper_plan)
        pure = request_action(
            paper_plan,
            action["paper_action"]["id"],
            actor=actor,
            requested_at=authorization["authorized_at"],
        )
        request = record(
            "ActionRequest",
            campaign_id=campaign_id,
            plan_id=plan["id"],
            action_id=aid,
            authorization_id=authorization["id"],
            actor=actor,
            pure_request=pure,
            requested_at=authorization["authorized_at"],
        )
        store.add_record(request, campaign_id)
        work_key = digest(
            "campaign-work.v1",
            {
                "kind": action["paper_action"]["kind"],
                "target": ref,
                "input": action["paper_action"]["subject"],
                "profile": policy.get("profile_digest"),
                "operation_policy": policy["id"],
                "assessment_policy": plan["assessment_policy"],
            },
        )
        task = record(
            "Task",
            campaign_id=campaign_id,
            action=action,
            action_id=aid,
            target=ref,
            work_key=work_key,
            request_id=request["id"],
            authorization_id=authorization["id"],
            policy_id=policy["id"],
            snapshot_id=snapshot["id"],
            created_at=authorization["authorized_at"],
            actor=actor,
        )
        kind = action["paper_action"]["kind"]
        state = (
            "AWAITING_REVIEW"
            if kind in HUMAN
            else "QUEUED"
            if kind in policy["allowed_kinds"]
            else "BLOCKED"
        )
        if set(action["prerequisites"]) - set(selected) and state == "QUEUED":
            state = "BLOCKED"
        results.append(queue.enqueue(store, campaign_id, task, actor=actor, state=state))
    return {"authorization": authorization, "tasks": results}


def tasks(store: Any, campaign_id: str) -> list[dict[str, Any]]:
    return queue.tasks(store, campaign_id)


@source_validation_operation
def request_stage(
    store: Any,
    campaign_id: str,
    kind: str,
    inputs: dict[str, Any],
    policy: dict[str, Any],
    actor: str,
    config: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Authorize one exact operator-owned source or pure-analysis stage.

    Inputs for source stages are source_path, optional entrypoint/paper_id. Other
    stages take run_id/assertion_id. Extraction configuration/replay bytes are
    bound here and supplied again through controller_config at dispatch; secrets
    are never retained. Manuscript text cannot call this API through extraction.
    """
    from ..paper_sources import acquire
    from .service import snapshot_update

    if kind not in AUTOMATIC or not actor.strip():
        raise ValueError("CAMPAIGN_STAGE_KIND_OR_ACTOR")
    _validate_policy(policy)
    if kind not in policy["allowed_kinds"]:
        raise ValueError("CAMPAIGN_STAGE_NOT_AUTHORIZED_BY_POLICY")
    if kind in SOURCE_STAGES:
        if set(inputs) - {"source_path", "entrypoint", "paper_id"} or not inputs.get("source_path"):
            raise ValueError("CAMPAIGN_SOURCE_STAGE_INPUTS")
        supplied_source = Path(inputs["source_path"])
        if supplied_source.is_symlink() or (
            hasattr(supplied_source, "is_junction") and supplied_source.is_junction()
        ):
            raise ValueError("CAMPAIGN_SOURCE_LINK_FORBIDDEN")
        source = supplied_source.resolve(strict=True)
        if policy["source_roots"] and not any(
            source.is_relative_to(Path(root).resolve(strict=True))
            for root in policy["source_roots"]
        ):
            raise ValueError("CAMPAIGN_SOURCE_OUTSIDE_OPERATION_POLICY")
        manifest, source_bytes = acquire(source, inputs.get("entrypoint"))
        source_material = {
            "manifest": asdict(manifest),
            "artifacts": {name: store.put(raw) for name, raw in source_bytes.items()},
        }
        target = {
            "source_stage": kind,
            "source_path": str(source),
            "revision": manifest.revision,
            "paper_id": inputs.get("paper_id") or source.stem,
            "entrypoint": inputs.get("entrypoint"),
        }
    else:
        source_material = None
        if set(inputs) != {"run_id", "assertion_id"}:
            raise ValueError("CAMPAIGN_ANALYSIS_STAGE_INPUTS")
        target = qualified_ref(store, inputs["run_id"], inputs["assertion_id"])
        if not any(
            s["run_id"] == target["run_id"]
            for s in store.current_snapshot(campaign_id)["selections"]
        ):
            raise ValueError("CAMPAIGN_STAGE_RUN_NOT_SELECTED")
    if kind == "EXTRACT_CONFIGURED":
        from ..extractor import validate_config

        if config is None or not policy["allow_model"]:
            raise ValueError("CAMPAIGN_MODEL_DISCLOSURE_NOT_AUTHORIZED")
        validate_config(config)
        if (
            config.get("max_requests", 64) > policy["model_max_requests"]
            or config.get("max_total_output_tokens", 65536) > policy["model_max_tokens"]
        ):
            raise ValueError("CAMPAIGN_MODEL_STAGE_BUDGET")
    if kind == "EXTRACT_RECORDED" and (config is None or replay is None):
        raise ValueError("CAMPAIGN_RECORDED_STAGE_INPUTS")
    if config is not None:
        # Config protocol rejects credentials, unknown fields and arbitrary URLs.
        from ..extractor import validate_config

        validate_config(config)
    snapshot = store.current_snapshot(campaign_id)
    if snapshot["operation_policy"] != policy["id"]:
        snapshot = snapshot_update(store, campaign_id, policy=policy, actor=actor)
        stale_tasks(store, campaign_id, actor=actor)
    request = record(
        "ActionRequest",
        campaign_id=campaign_id,
        stage_kind=kind,
        target=target,
        actor=actor,
        requested_at=queue.utc_now(),
        config_digest=digest("campaign-stage-config.v1", config) if config else None,
        replay_digest=digest("campaign-stage-replay.v1", replay) if replay else None,
        authority="EXPLICIT_OPERATOR_REQUEST",
    )
    action = {
        "target": target,
        "paper_action": {"kind": kind},
        "prerequisites": [],
        "goal_ids": [],
        "adapter": kind,
        "config_digest": request["config_digest"],
        "replay_digest": request["replay_digest"],
        "model_reservation": {
            "requests": config.get("max_requests", 64),
            "tokens": config.get("max_total_output_tokens", 65536),
            "seconds": config.get("max_total_seconds", 120),
        }
        if kind == "EXTRACT_CONFIGURED" and config
        else None,
    }
    action["id"] = digest("campaign-stage-action.v1", action)
    authorization = record(
        "OperationAuthorization",
        campaign_id=campaign_id,
        plan_id=None,
        request_id=request["id"],
        policy_id=policy["id"],
        snapshot_id=snapshot["id"],
        action_ids=[action["id"]],
        actor=actor,
        authorized_at=queue.utc_now(),
    )
    store.add_record(request, campaign_id)
    store.add_record(authorization, campaign_id)
    task = record(
        "Task",
        campaign_id=campaign_id,
        action=action,
        action_id=action["id"],
        target=target,
        work_key=digest("campaign-stage-work.v1", {"action": action, "policy_id": policy["id"]}),
        request_id=request["id"],
        authorization_id=authorization["id"],
        policy_id=policy["id"],
        snapshot_id=snapshot["id"],
        created_at=queue.utc_now(),
        actor=actor,
        source_material=source_material,
    )
    return queue.enqueue(store, campaign_id, task, actor=actor)


def cancel_task(store: Any, task_id: str, actor: str = "operator") -> dict[str, Any]:
    return queue.cancel_task(store, task_id, actor=actor)


def recover(
    store: Any, campaign_id: str, actor: str = "operator", now: str | None = None
) -> list[str]:
    return queue.recover(store, campaign_id, actor=actor, now=now)


def retry_task(store: Any, task_id: str, actor: str = "operator") -> dict[str, Any]:
    task = next(
        t for t in tasks(store, store.get_record(task_id)["campaign_id"]) if t["id"] == task_id
    )
    policy = store.get_record(task["policy_id"])
    if (
        task["state"] not in {"ERROR", "UNAVAILABLE"}
        or task.get("model_unknown_effect")
        or task["attempt_count"] >= policy["max_attempts"]
    ):
        raise ValueError("CAMPAIGN_RETRY_NOT_ELIGIBLE")
    if not _applicable(store, task, policy, None):
        raise ValueError("CAMPAIGN_RETRY_SUBJECT_STALE")
    return queue.transition(store, task_id, "QUEUED", actor=actor, reason="EXPLICIT_OPERATOR_RETRY")


def _applicable(
    store: Any, task: dict[str, Any], policy: dict[str, Any], profile: dict[str, Any] | None
) -> bool:
    authorization = store.get_record(task["authorization_id"])
    request = store.get_record(task["request_id"])
    kind = task["action"]["paper_action"]["kind"]
    if (
        authorization["kind"] != "OperationAuthorization"
        or request["kind"] != "ActionRequest"
        or authorization["campaign_id"] != task["campaign_id"]
        or request["campaign_id"] != task["campaign_id"]
        or authorization["policy_id"] != policy["id"]
        or task["action_id"] not in authorization["action_ids"]
        or authorization["actor"] != task["actor"]
        or request["actor"] != task["actor"]
        or (kind not in HUMAN and kind not in policy["allowed_kinds"])
    ):
        return False
    current = store.current_snapshot(task["campaign_id"])
    # Explicit old authorization cannot silently authorize a new policy.
    if current.get("operation_policy") not in {None, task["policy_id"]}:
        return False
    if task["target"].get("source_stage"):
        from ..paper_sources import acquire

        target = task["target"]
        try:
            source = Path(target["source_path"]).resolve(strict=True)
            if policy["source_roots"] and not any(
                source.is_relative_to(Path(root).resolve(strict=True))
                for root in policy["source_roots"]
            ):
                return False
            manifest, _ = acquire(source, target.get("entrypoint"))
            return bool(manifest.revision == target["revision"])
        except (OSError, ValueError):
            return False
    if not any(
        s["run_id"] == task["target"]["run_id"] and s["revision"] == task["target"]["revision"]
        for s in current["selections"]
    ):
        return False
    if canonical_bytes(task["target"]) != canonical_bytes(
        qualified_ref(store, task["target"]["run_id"], task["target"]["assertion_id"])
    ):
        return False
    if (
        profile is not None
        and policy.get("profile_digest") != VerifierProfile.from_dict(profile).digest
    ):
        return False
    return True


@source_validation_operation
def stale_tasks(store: Any, campaign_id: str, actor: str = "revision-refresh") -> list[str]:
    affected = []
    for task in tasks(store, campaign_id):
        if task["state"] in queue.TERMINAL:
            continue
        if not _applicable(store, task, store.get_record(task["policy_id"]), None):
            queue.transition(
                store, task["id"], "STALE", actor=actor, reason="SUBJECT_OR_POLICY_CHANGED"
            )
            affected.append(task["id"])
    return affected


def invalidate_changed_tasks(store: Any, campaign_id: str) -> list[str]:
    return stale_tasks(store, campaign_id)


def _controller(config: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bytes | None, str]:
    config = config or {}
    profile = config.get("profile")
    if isinstance(profile, str):
        profile = load_json(Path(profile))
    if profile is not None:
        VerifierProfile.from_dict(profile)
    key_path = config.get("private_key_path") or config.get("controller_key")
    key = Path(key_path).read_bytes() if key_path else None
    return profile, key, config.get("controller_id", "local-unsigned")


def _lease_cancellation(
    store: Any,
    task: dict[str, Any],
    lease: dict[str, Any],
    policy: dict[str, Any],
    actor: str,
    started: float,
    call_seconds: int,
) -> tuple[Callable[[], bool], list[bool]]:
    last_pulse = [0.0]
    cancellation = [False]

    def cancelled() -> bool:
        clock = time.monotonic()
        if clock - last_pulse[0] < min(0.5, policy["lease_seconds"] / 4):
            return cancellation[0]
        last_pulse[0] = clock
        cancellation[0] = clock - started >= call_seconds or not queue.heartbeat(
            store,
            task["id"],
            lease["lease_token"],
            lease["generation"],
            lease_seconds=policy["lease_seconds"],
            owner=actor,
        )
        return cancellation[0]

    return cancelled, cancellation


def _promote_staged_runs(
    store: Any, task: dict[str, Any], evidence: dict[str, Any], actor: str
) -> None:
    """Publish produced immutable runs inside queue.transition's writer fence."""
    old = store.current_snapshot(task["campaign_id"])
    selections = list(old["selections"])
    for row in evidence["manuscripts"]:
        run = store.inspect(row["run_id"])["bundle"]
        paper = store.db.execute(
            "SELECT paper_id FROM revisions WHERE id=?", (row["revision"],)
        ).fetchone()
        if (
            row["revision"] != task["target"]["revision"]
            or row["paper_id"] != task["target"]["paper_id"]
            or run["input_manifest"]["revision"] != row["revision"]
            or paper != (row["paper_id"],)
        ):
            raise ValueError("CAMPAIGN_STAGE_RESULT_SUBJECT_BINDING")
        selected = {name: row[name] for name in ("paper_id", "run_id", "revision")}
        selections = [s for s in selections if s["paper_id"] != selected["paper_id"]] + [selected]
    selections.sort(key=lambda s: s["paper_id"])
    if selections == old["selections"]:
        return
    snapshot = record(
        "CampaignSnapshot",
        campaign_id=task["campaign_id"],
        objective=old["objective"],
        selections=selections,
        goals=old["goals"],
        operation_policy=old["operation_policy"],
        parent_snapshot=old["id"],
        actor=actor,
        created_at=queue.utc_now(),
    )
    store.validate_snapshot(snapshot)
    queue._insert(store, task["campaign_id"], snapshot)
    event = record(
        "CampaignMembershipEvent",
        campaign_id=task["campaign_id"],
        from_snapshot=old["id"],
        to_snapshot=snapshot["id"],
        reason="LEASE_FENCED_INTAKE",
        actor=actor,
        created_at=queue.utc_now(),
    )
    queue._insert(store, task["campaign_id"], event)
    store.db.execute(
        "UPDATE campaign_heads SET snapshot_id=? WHERE campaign_id=? AND snapshot_id=?",
        (snapshot["id"], task["campaign_id"], old["id"]),
    )


def _satisfied_actions(store: Any, current: list[dict[str, Any]]) -> set[str]:
    fresh = {
        task["action_id"]: task
        for task in sorted(current, key=lambda t: (t["created_at"], t["id"]))
        if task["action"]["paper_action"]["kind"] in queue.FRESH_EVALUATIONS
        and _applicable(store, task, store.get_record(task["policy_id"]), None)
    }
    return {
        task["action_id"]
        for task in current
        if task["state"] == "SUCCEEDED"
        and (task["action_id"] not in fresh or fresh[task["action_id"]]["id"] == task["id"])
    }


def _finalize_work(
    store: Any,
    task: dict[str, Any],
    policy: dict[str, Any],
    profile: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
    status: str,
    actor: str,
) -> None:
    if status in {"CANCELLED", "ERROR"}:
        return
    if not _applicable(store, task, policy, profile):
        raise ValueError("CAMPAIGN_LEASE_FENCED")
    if (
        task["action"]["paper_action"]["kind"] in SOURCE_STAGES
        and evidence
        and evidence.get("manuscripts")
    ):
        _promote_staged_runs(store, task, evidence, actor)


@source_validation_operation
def run_campaign(
    store: Any,
    campaign_id: str,
    controller_config: dict[str, Any] | None = None,
    max_tasks: int | None = None,
    max_wall_seconds: int | None = None,
    until: str = "review",
    actor: str = "local-controller",
    task_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Run the admitted adapters with isolated execution; no host fallback."""
    from ..execution import execute

    if until not in {"review", "idle"}:
        raise ValueError("CAMPAIGN_RUN_BOUNDARY")
    profile, key, controller_id = _controller(controller_config)
    stale_tasks(store, campaign_id, actor=actor)
    started = time.monotonic()
    outputs: list[dict[str, Any]] = []
    initial = tasks(store, campaign_id)
    if task_ids is not None and (
        len(task_ids) != len(set(task_ids)) or set(task_ids) - {t["id"] for t in initial}
    ):
        raise ValueError("CAMPAIGN_RUN_TASK_SELECTION")
    if max_tasks is not None and (type(max_tasks) is not int or max_tasks < 1):
        raise ValueError("CAMPAIGN_RUN_TASK_BUDGET")
    if max_wall_seconds is not None and (type(max_wall_seconds) is not int or max_wall_seconds < 1):
        raise ValueError("CAMPAIGN_RUN_TIME_BUDGET")
    queued = [
        t for t in initial if t["state"] == "QUEUED" and (task_ids is None or t["id"] in task_ids)
    ]
    policies = {t["policy_id"]: store.get_record(t["policy_id"]) for t in queued}
    for policy in policies.values():
        _validate_policy(policy)
    call_tasks = min(
        [p["max_tasks"] for p in policies.values()] + ([max_tasks] if max_tasks else [10000])
    )
    call_seconds = min(
        [p["max_wall_seconds"] for p in policies.values()]
        + ([max_wall_seconds] if max_wall_seconds else [86400])
    )
    stop_reason = "IDLE"
    while len(outputs) < call_tasks and time.monotonic() - started < call_seconds:
        current = tasks(store, campaign_id)
        done = _satisfied_actions(store, current)
        ready = [
            t
            for t in current
            if t["state"] == "QUEUED"
            and set(t["action"]["prerequisites"]) <= done
            and (task_ids is None or t["id"] in task_ids)
        ]
        if not ready:
            break
        task = ready[0]
        policy = store.get_record(task["policy_id"])
        if not _applicable(store, task, policy, profile):
            queue.transition(
                store, task["id"], "STALE", actor=actor, reason="DISPATCH_MATERIAL_CHANGED"
            )
            continue
        kind = task["action"]["paper_action"]["kind"]
        reserve = (
            int(profile["limits"]["seconds"]) + 35
            if profile and kind in {"VERIFY_FORMAL_SUBJECT", "REFRESH_EVIDENCE"}
            else 60 + int(task["action"]["model_reservation"]["seconds"])
            if kind == "EXTRACT_CONFIGURED"
            else min(60, policy["max_wall_seconds"])
            if kind in SOURCE_STAGES
            else min(60, policy["max_wall_seconds"])
        )
        if time.monotonic() - started + reserve > call_seconds:
            stop_reason = "BUDGET_EXHAUSTED"
            break
        lease = queue.claim(
            store,
            campaign_id,
            owner=actor,
            lease_seconds=policy["lease_seconds"],
            max_attempts=policy["max_attempts"],
            reserve_seconds=reserve,
            max_tasks=policy["max_tasks"],
            max_wall_seconds=policy["max_wall_seconds"],
            ready={task["id"]},
            model_reserve_requests=int(task["action"]["model_reservation"]["requests"])
            if kind == "EXTRACT_CONFIGURED"
            else 0,
            model_reserve_tokens=int(task["action"]["model_reservation"]["tokens"])
            if kind == "EXTRACT_CONFIGURED"
            else 0,
            model_max_requests=policy["model_max_requests"],
            model_max_tokens=policy["model_max_tokens"],
        )
        if lease is None:
            stop_reason = "LEASE_OR_BUDGET_BOUNDARY"
            break
        attempt_started = time.monotonic()
        cancelled, cancellation = _lease_cancellation(
            store, task, lease, policy, actor, started, call_seconds
        )
        status = "ERROR"
        evidence: dict[str, Any] | None = None
        error: str | None = None
        model_effect = "NOT_DISPATCHED"
        try:
            if kind in {"VERIFY_FORMAL_SUBJECT", "REFRESH_EVIDENCE"}:
                bundle = _bundle(store, task["target"]["run_id"])
                row = next(
                    r
                    for r in bundle["formalizations"]
                    if r["assertion_id"] == task["target"]["assertion_id"]
                )
                if profile is None:
                    status, error = (
                        "UNAVAILABLE",
                        "EXTERNAL_EXECUTION_PROFILE_REQUIRED; host fallback forbidden",
                    )
                elif row["status"] != "SUPPORTED":
                    status, error = "CHECK_FAILED", "FORMALIZATION_UNSUPPORTED"
                else:
                    evidence = execute(
                        row["binding"],
                        FormalObligation.from_dict(row["obligation"]),
                        row["candidate"].encode("utf-8"),
                        profile,
                        controller_id=controller_id,
                        private_key=key,
                        cancelled=cancelled,
                    )
                    outcome = evidence["event"]["outcome"]
                    status = (
                        "SUCCEEDED"
                        if outcome == "VERIFIED"
                        else "UNAVAILABLE"
                        if outcome == "UNAVAILABLE"
                        else "CHECK_FAILED"
                        if outcome == "COMPILER_REJECTED"
                        else "ERROR"
                    )
            else:
                from .lifecycle import run_adapter

                supplied = controller_config or {}
                config: dict[str, Any] = {
                    name: supplied[name]
                    for name in (
                        "extractor_config",
                        "extractor_replay",
                        "trust_store",
                        "evaluation_time",
                    )
                    if name in supplied
                }
                if isinstance(config.get("trust_store"), str):
                    config["trust_store"] = load_json(Path(config["trust_store"]))
                if profile is not None:
                    config["profile"] = profile
                if kind == "EXTRACT_CONFIGURED":
                    # An unexpected transport/cleanup failure after the gate
                    # must never release a possibly dispatched model budget.
                    model_effect = "POSSIBLE_EXTERNAL_EFFECT"
                response = run_adapter(
                    {
                        "store_root": str(store.root.resolve()),
                        "task_id": task["id"],
                        "kind": kind,
                        "lease_token": lease["lease_token"],
                        "generation": lease["generation"],
                        "actor": actor,
                        "reserve": reserve,
                        "config": config,
                    },
                    cancelled,
                    partial(
                        queue._retain_for_cleanup,
                        store,
                        task["id"],
                        lease["lease_token"],
                        lease["generation"],
                        owner=actor,
                    ),
                )
                status, evidence, error = (
                    response["state"],
                    response.get("evidence"),
                    response.get("error"),
                )
                model_effect = response["model_effect"]
                if evidence is None:
                    evidence = {}
                evidence["worker_cleanup"] = response["cleanup"]
        except (ValueError, OSError, KeyError, TypeError) as exc:
            error = type(exc).__name__ + ":" + str(exc)[:256]
        elapsed = time.monotonic() - attempt_started
        if cancellation[0]:
            status = (
                "CANCELLED"
                if evidence and evidence.get("runner_status") == "CANCELLED"
                else "ERROR"
            )
        result = record(
            "TaskResult",
            campaign_id=campaign_id,
            task_id=task["id"],
            attempt_id=lease["attempt_id"],
            generation=lease["generation"],
            target=task["target"],
            state=status,
            evidence=evidence,
            error=error,
            duration_seconds=elapsed,
            created_at=queue.utc_now(),
            mathematical_acceptance="NOT_IMPLIED",
            model_effect=model_effect,
        )
        try:
            queue.transition(
                store,
                task["id"],
                status,
                actor=actor,
                reason=error or status,
                token=lease["lease_token"],
                generation=lease["generation"],
                result=result,
                usage_seconds=elapsed,
                publication=partial(
                    _finalize_work, store, task, policy, profile, evidence, status, actor
                ),
            )
            stale_tasks(store, campaign_id, actor=actor)
            outputs.append({"task_id": task["id"], "state": status, "result_id": result["id"]})
        except ValueError as exc:
            if str(exc) != "CAMPAIGN_LEASE_FENCED":
                raise
            outputs.append({"task_id": task["id"], "state": "FENCED", "result_id": None})
            stale_tasks(store, campaign_id, actor=actor)
    if len(outputs) >= call_tasks or time.monotonic() - started >= call_seconds:
        stop_reason = "BUDGET_EXHAUSTED"
    pending_reviews = sum(t["state"] == "AWAITING_REVIEW" for t in tasks(store, campaign_id))
    return {
        "campaign_id": campaign_id,
        "outcomes": outputs,
        "boundary": "AWAITING_REVIEW" if pending_reviews else stop_reason,
        "stop_reason": stop_reason,
        "pending_reviews": pending_reviews,
        "duration_seconds": time.monotonic() - started,
        "acceptance": "REQUIRES_CURRENT_POLICY_ASSESSMENT",
    }


def _assessment_for_run(
    store: Any,
    bundle: dict[str, Any],
    profile: dict[str, Any],
    trust_store: dict[str, Any],
    evaluation_time: str,
) -> dict[str, Any]:
    verified_profile = VerifierProfile.from_dict(profile)
    records, dimensions = [], []
    events = _events(store, bundle)
    reviews = store.list_audit(bundle["run_manifest"]["run_id"], "ReviewDecision")
    for row in bundle["formalizations"]:
        if row["status"] != "SUPPORTED":
            continue
        binding = FormalizationBinding.from_dict(row["binding"])
        selected = [e for e in events if e["event"]["binding_digest"] == binding.digest]
        current_envelope = selected[-1].get("envelope") if selected else None
        relevant = [
            r["envelope"]
            for r in reviews
            if r["record"]["binding_digest"] == binding.digest and r.get("envelope")
        ]
        acceptance = assess_binding(
            binding,
            FormalObligation.from_dict(row["obligation"]),
            verified_profile,
            current_envelope,
            relevant,
            trust_store,
            evaluation_time=evaluation_time,
            historical_execution=row.get("historical_execution")
            if current_envelope is None
            else None,
        )
        records.append(acceptance.to_dict())
        dimensions.extend(assessment_records(acceptance, binding))
    return {
        "run_id": bundle["run_manifest"]["run_id"],
        "records": records,
        "assessment_records": dimensions,
        "evaluation_time": evaluation_time,
    }


@source_validation_operation
def assess_campaign(
    store: Any,
    campaign_id: str,
    profile: dict[str, Any],
    trust_store: dict[str, Any],
    evaluation_time: str,
    actor: str = "policy-evaluator",
) -> dict[str, Any]:
    snapshot = store.current_snapshot(campaign_id)
    runs = [
        _assessment_for_run(
            store, _bundle(store, s["run_id"]), profile, trust_store, evaluation_time
        )
        for s in snapshot["selections"]
    ]
    all_records = [r for run in runs for r in run["records"]]
    for run in runs:
        store.add_audits(
            run["run_id"],
            [{"record": r, "envelope": None} for r in run["records"] + run["assessment_records"]],
        )
    result = record(
        "CampaignAssessmentSnapshot",
        campaign_id=campaign_id,
        snapshot_id=snapshot["id"],
        runs=runs,
        counts={
            "formalized": len(all_records),
            "verified": sum(r["formal_status"] == "VERIFIED" for r in all_records),
            "reviewed": sum(
                r["source_fidelity"] == "APPROVE" and r["formal_fidelity"] == "APPROVE"
                for r in all_records
            ),
            "accepted": sum(r["assessment"] == "ACCEPTED_UNDER_POLICY" for r in all_records),
        },
        profile_digest=VerifierProfile.from_dict(profile).digest,
        trust_digest=digest("campaign-external-authority.v1", trust_store),
        evaluation_time=evaluation_time,
        actor=actor,
        created_at=queue.utc_now(),
        scholarly_novelty="NOT_ASSESSED",
    )
    store.add_record(result, campaign_id)
    return result


@source_validation_operation
def review_packets(
    store: Any, campaign_id: str, out: Path | None = None, profile: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    packets = []
    seen = set()
    for task in tasks(store, campaign_id):
        if task["state"] != "AWAITING_REVIEW":
            continue
        ref = task["target"]
        key = (ref["run_id"], ref["assertion_id"])
        if key in seen:
            continue
        seen.add(key)
        if not _applicable(store, task, store.get_record(task["policy_id"]), profile):
            queue.transition(
                store, task["id"], "STALE", actor="review-packet", reason="REVIEW_MATERIAL_CHANGED"
            )
            continue
        bundle = _bundle(store, ref["run_id"])
        assertion = next(a for a in bundle["assertions"] if a["id"] == ref["assertion_id"])
        formal = next(
            r for r in bundle["formalizations"] if r["assertion_id"] == ref["assertion_id"]
        )
        original = [
            e
            for e in bundle["document_ir"]["elements"]
            if e["id"] in assertion.get("source_ids", []) + assertion.get("proof_ids", [])
            or e.get("locator") in formal.get("source_locators", [])
        ]
        held = store.inspect(ref["run_id"])["artifacts"]
        interpreted = bundle.get("interpreted_ir", bundle["document_ir"])
        packet = record(
            "ReviewHandoff",
            campaign_id=campaign_id,
            target=ref,
            source=original,
            assertion=assertion,
            interpretation={
                "elements": [e for e in interpreted["elements"] if e["id"] == ref["assertion_id"]],
                "semantic_overlay": bundle.get("semantic_overlay", {}),
                "candidate_fidelity": bundle.get("candidate_fidelity", {}),
                "context": assertion.get("source_context", []),
            },
            source_material={"manifest": bundle["input_manifest"], "artifacts": held},
            formalization=formal,
            execution=[
                e
                for e in _events(store, bundle)
                if e["event"]["binding_digest"] == ref.get("binding_digest")
            ],
            assessment_policy=POLICY,
            operation_policy=task["policy_id"],
            decision="PENDING_HUMAN_REVIEW",
            reviewer_id=None,
            reason=None,
            created_at=queue.utc_now(),
        )
        store.add_record(packet, campaign_id)
        packets.append(packet)
        if out is not None:
            if out.is_symlink():
                raise ValueError("CAMPAIGN_REVIEW_OUTPUT_SYMLINK")
            out.mkdir(parents=True, exist_ok=True)
            source_root = (out / packet["id"] / "source").resolve()
            if not source_root.is_relative_to(out.resolve()):
                raise ValueError("CAMPAIGN_REVIEW_SOURCE_DESTINATION")
            for name, sha in held.items():
                target = (source_root / relative_path(name)).resolve()
                if not target.is_relative_to(source_root):
                    raise ValueError("CAMPAIGN_REVIEW_SOURCE_DESTINATION")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(store.get(sha))
            write_json(out / (packet["id"] + ".json"), packet)
            text = canonical_bytes(packet).decode("utf-8")
            (out / (packet["id"] + ".html")).write_text(
                "<!doctype html><meta charset='utf-8'><meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'\"><title>ProofMap review packet</title><h1>Pending human review</h1><p>Task completion supplies no fidelity approval.</p><pre>"
                + html.escape(text)
                + "</pre>",
                encoding="utf-8",
            )
    return packets


@source_validation_operation
def review_decision(
    store: Any,
    campaign_id: str,
    run_id: str,
    assertion_id: str,
    profile: dict[str, Any],
    dimension: str,
    decision: str,
    reviewer_id: str,
    reason: str,
    key: bytes | None = None,
    supersedes: str | None = None,
) -> dict[str, Any]:
    from ..paper_evidence import fidelity_draft, sign_fidelity_draft

    if (
        decision not in {"APPROVE", "REJECT", "ABSTAIN"}
        or not reason.strip()
        or dimension not in {"source-fidelity", "formal-fidelity"}
    ):
        raise ValueError("CAMPAIGN_EXPLICIT_REVIEW_DECISION")
    if not any(s["run_id"] == run_id for s in store.current_snapshot(campaign_id)["selections"]):
        raise ValueError("CAMPAIGN_REVIEW_RUN_NOT_SELECTED")
    ref = qualified_ref(store, run_id, assertion_id)
    metadata = record(
        "ReviewHandoff",
        campaign_id=campaign_id,
        target=ref,
        reviewer_id=reviewer_id,
        dimension=dimension,
        decision=decision,
        reason=reason,
        created_at=queue.utc_now(),
    )
    store.add_record(metadata, campaign_id)
    if decision == "ABSTAIN":
        return metadata
    draft = fidelity_draft(_bundle(store, run_id), assertion_id, profile, dimension, reviewer_id)
    draft.update(decision=decision, supersedes=supersedes)
    draft["method"] = "human-review-v1; campaign-handoff:" + metadata["id"]
    return sign_fidelity_draft(draft, key) if key is not None else draft


@source_validation_operation
def apply_decision(
    store: Any,
    campaign_id: str,
    run_id: str,
    envelope: dict[str, Any],
    profile: dict[str, Any],
    trust_store: dict[str, Any],
    evaluation_time: str,
) -> dict[str, Any]:
    from ..paper_evidence import apply_fidelity
    from ..trust import authenticated_record

    decision = authenticated_record(envelope)
    if not any(s["run_id"] == run_id for s in store.current_snapshot(campaign_id)["selections"]):
        raise ValueError("CAMPAIGN_REVIEW_RUN_NOT_SELECTED")
    apply_fidelity(_bundle(store, run_id), envelope, store, profile, trust_store, evaluation_time)
    for task in tasks(store, campaign_id):
        if (
            task["state"] == "AWAITING_REVIEW"
            and task["target"]["run_id"] == run_id
            and task["target"].get("binding_digest") == decision["binding_digest"]
            and task["action"]["paper_action"]["mode"] == decision["dimension"] + "-review"
        ):
            queue.transition(
                store,
                task["id"],
                "DECISION_RECORDED" if decision["decision"] == "APPROVE" else "REJECTED",
                actor=decision["reviewer_id"],
                reason="AUTHENTICATED_EXPLICIT_" + decision["decision"],
            )
    return assess_campaign(store, campaign_id, profile, trust_store, evaluation_time)
