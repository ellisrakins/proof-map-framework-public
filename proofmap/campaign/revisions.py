"""Campaign revision impact built on the existing dependency-aware paper plan."""

from __future__ import annotations

from typing import Any

from ..paper_revision import revision_plan
from .models import record, utc_now


def revision_impact(
    store: Any,
    campaign_id: str,
    from_snapshot: str,
    to_snapshot: str,
    *,
    actor: str = "operator",
    persist: bool = True,
) -> dict[str, Any]:
    before, after = store.get_record(from_snapshot), store.get_record(to_snapshot)
    if any(
        s["kind"] != "CampaignSnapshot" or s["campaign_id"] != campaign_id for s in (before, after)
    ):
        raise ValueError("REVISION_IMPACT_SNAPSHOT_CAMPAIGN")
    store.validate_snapshot(before)
    store.validate_snapshot(after)
    old = {s["paper_id"]: s for s in before["selections"]}
    new = {s["paper_id"]: s for s in after["selections"]}
    papers, stale_targets, required_reviews, retained_results, reused_artifacts = [], [], [], [], []
    mappings = []
    for paper in sorted(old.keys() | new.keys()):
        previous: dict[str, Any] | None = old.get(paper)
        current: dict[str, Any] | None = new.get(paper)
        if previous == current:
            papers.append(
                {
                    "paper_id": paper,
                    "membership": "UNCHANGED",
                    "claims": [],
                    "policy_reassessment_required": before["operation_policy"]
                    != after["operation_policy"],
                }
            )
            continue
        earlier = store.inspect(previous["run_id"])["bundle"] if previous else None
        later = store.inspect(current["run_id"])["bundle"] if current else None
        if earlier:
            assert previous is not None
            retained_results += [
                {
                    "paper_id": paper,
                    "run_id": previous["run_id"],
                    "execution": event,
                    "applicability": "HISTORICAL_ONLY_REAUTHENTICATION_REQUIRED",
                }
                for event in earlier.get("execution_events", [])
            ]
            retained_results += [
                {
                    "paper_id": paper,
                    "run_id": previous["run_id"],
                    "audit": audit,
                    "applicability": "HISTORICAL_ONLY_REAUTHENTICATION_REQUIRED",
                }
                for audit in store.list_audit(previous["run_id"])
            ]
            stale_targets += [
                {
                    "paper_id": paper,
                    "run_id": previous["run_id"],
                    "assertion_id": assertion["id"],
                    "reason": "EXACT_SELECTED_RUN_REPLACED_OR_REMOVED",
                }
                for assertion in earlier["assertions"]
            ]
        if later is None:
            assert earlier is not None
            papers.append(
                {
                    "paper_id": paper,
                    "membership": "REMOVED",
                    "claims": [],
                    "unresolved_removed_claims": [r["id"] for r in earlier["assertions"]],
                }
            )
            continue
        assert current is not None
        plan = revision_plan(
            earlier, later["document_ir"], later["run_manifest"].get("analysis_context", {})
        )
        observed = later.get("revision_plan", {})
        observed_rows = (
            {r["assertion_id"]: r for r in observed.get("rows", [])}
            if observed.get("parent_run") == (previous or {}).get("run_id")
            else {}
        )
        claims = []
        matched = set()
        for row in plan["rows"]:
            prior = row["previous_assertion_id"]
            if prior:
                assert previous is not None
                matched.add(prior)
                mappings.append(
                    {
                        "paper_id": paper,
                        "from_run": previous["run_id"],
                        "from_assertion": prior,
                        "to_run": current["run_id"],
                        "to_assertion": row["assertion_id"],
                        "identity_method": "EXISTING_UNAMBIGUOUS_SOURCE_LOGICAL_ID",
                        "goal_rebinding": "EXPLICIT_OPERATOR_EVENT_REQUIRED",
                    }
                )
            state = (
                "UNRESOLVED"
                if prior is None
                else "MOVED"
                if row["changes"] == ["SOURCE_REANCHORED"]
                else "CHANGED"
                if not row["reuse_eligible"]
                else "MATCHED"
            )
            claims.append(
                {
                    "assertion_id": row["assertion_id"],
                    "previous_assertion_id": prior,
                    "state": state,
                    "changes": row["changes"],
                    "reasons": row["reasons"],
                    "pure_reuse_eligible": row["reuse_eligible"],
                    "acceptance_carried": False,
                }
            )
            formal: dict[str, Any] = next(
                (f for f in later["formalizations"] if f["assertion_id"] == row["assertion_id"]), {}
            )
            if formal.get("status") == "SUPPORTED":
                required_reviews.append(
                    {
                        "paper_id": paper,
                        "run_id": current["run_id"],
                        "assertion_id": row["assertion_id"],
                        "binding_digest": formal.get("binding", {}).get("id"),
                        "dimensions": ["source-fidelity", "formal-fidelity"],
                        "reason": "NEW_EXACT_SOURCE_BINDING",
                    }
                )
            produced = observed_rows.get(row["assertion_id"], {})
            if (
                produced.get("pure_execution") == "REUSED"
                or produced.get("formal_execution") == "HISTORICAL_REUSE"
            ):
                reused_artifacts.append(
                    {
                        "paper_id": paper,
                        "run_id": current["run_id"],
                        "assertion_id": row["assertion_id"],
                        "stage_id": produced.get("pure_stage"),
                        "parent_stage": produced.get("parent_stage"),
                        "cache_validation": produced.get("cache_validation"),
                        "historical_event": produced.get("historical_event"),
                        "justification": "EXISTING_DEPENDENCY_MATERIAL_CHECKS",
                        "acceptance_carried": False,
                    }
                )
        removed = [r["id"] for r in (earlier or {}).get("assertions", []) if r["id"] not in matched]
        papers.append(
            {
                "paper_id": paper,
                "membership": "ADDED" if earlier is None else "REPLACED",
                "from_run": (previous or {}).get("run_id"),
                "to_run": current["run_id"],
                "claims": claims,
                "unresolved_removed_claims": removed,
                "configuration_changes": plan["configuration_changes"],
            }
        )
    stale_keys = {(r["run_id"], r["assertion_id"]) for r in stale_targets}
    affected_tasks = []
    for task in store.records(campaign_id, "Task"):
        target = task.get("target", task.get("subject", {}))
        key = (
            target.get("run_id", task.get("run_id")),
            target.get("assertion_id", target.get("id")),
        )
        if key in stale_keys or (
            before["operation_policy"] != after["operation_policy"]
            and task.get("policy_id") == before["operation_policy"]
        ):
            affected_tasks.append(
                {
                    "task_id": task["id"],
                    "exact_target": target,
                    "reason": "SUBJECT_OR_OPERATION_POLICY_CHANGED",
                    "result_retained": True,
                    "new_dispatch": "REQUIRES_FRESH_REQUEST_AND_AUTHORIZATION",
                }
            )
    current_keys = {(s["paper_id"], s["run_id"], s["revision"]) for s in after["selections"]}
    unresolved_goals = [
        g["id"]
        for g in after["goals"]
        if g.get("target")
        and (g["target"]["paper_id"], g["target"]["run_id"], g["target"]["revision"])
        not in current_keys
    ]
    value = record(
        "CampaignRevisionImpact",
        campaign_id=campaign_id,
        from_snapshot=from_snapshot,
        to_snapshot=to_snapshot,
        papers=papers,
        matched_source_mappings=mappings,
        affected_tasks=affected_tasks,
        stale_source_bindings=stale_targets,
        retained_historical_results=retained_results,
        required_new_reviews=required_reviews,
        observed_reused_artifacts=reused_artifacts,
        unresolved_goals=unresolved_goals,
        policy_reassessment_required=before["operation_policy"] != after["operation_policy"],
        trust_reassessment="ALWAYS_CURRENT_EXTERNAL_AUTHORITY_REQUIRED",
        acceptance_carried=False,
        actor=actor,
        created_at=utc_now(),
    )
    if persist:
        store.add_record(value, campaign_id)
    return value
