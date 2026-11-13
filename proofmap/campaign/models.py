"""Versioned immutable campaign records and exact qualified claim references."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from ..integrity import canonical_bytes, digest, require_digest, strict_loads
from ..paper_sources import source_validation_operation

KINDS = {
    "Campaign",
    "CampaignSnapshot",
    "CampaignPaperSelection",
    "Goal",
    "QualifiedClaimRef",
    "CampaignRelationCandidate",
    "OperationPolicy",
    "CapabilityAssessment",
    "ActionRequest",
    "Task",
    "TaskAttempt",
    "TaskEvent",
    "TaskResult",
    "ReviewHandoff",
    "CampaignAssessmentSnapshot",
    "CampaignExportManifest",
    "CampaignPlan",
    "OperationAuthorization",
    "CampaignMembershipEvent",
    "GoalRebinding",
    "CampaignRevisionImpact",
    "CampaignImport",
    "CampaignRecovery",
    "CampaignPilot",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_time(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("CAMPAIGN_TIME")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("CAMPAIGN_TIME") from exc
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError("CAMPAIGN_TIME_REQUIRES_UTC")


def record(kind: str, **fields: Any) -> dict[str, Any]:
    if {"schema_version", "kind", "id"} & fields.keys():
        raise ValueError("CAMPAIGN_RESERVED_FIELDS")
    value = {"schema_version": "1.0", "kind": kind, **fields}
    value["id"] = digest("campaign-record.v1", value)
    validate_record(value)
    return cast(dict[str, Any], strict_loads(canonical_bytes(value)))


def validate_record(value: dict[str, Any]) -> None:
    from ..schema import validate

    raw = canonical_bytes(value)
    if len(raw) > 8_000_000 or not isinstance(value, dict):
        raise ValueError("CAMPAIGN_RECORD_LIMIT")
    if value.get("schema_version") != "1.0" or value.get("kind") not in KINDS:
        raise ValueError("CAMPAIGN_RECORD_VERSION_OR_KIND")
    if validate("campaign-record", value):
        raise ValueError("CAMPAIGN_RECORD_SCHEMA")
    if value.get("id") != digest(
        "campaign-record.v1", {k: v for k, v in value.items() if k != "id"}
    ):
        raise ValueError("CAMPAIGN_RECORD_IDENTITY")
    if "created_at" in value:
        validate_time(value["created_at"])
    kind = value["kind"]
    if kind == "Campaign":
        for name in ("name", "objective", "actor"):
            if not isinstance(value.get(name), str) or not value[name].strip():
                raise ValueError("CAMPAIGN_REQUIRED_" + name.upper())
        if len(value["objective"]) > 32_000 or len(value["name"]) > 512:
            raise ValueError("CAMPAIGN_TEXT_LIMIT")
    if kind == "OperationPolicy":
        validate_policy(value)
    if kind == "Goal":
        if bool(value.get("target")) == bool(value.get("question")):
            raise ValueError("GOAL_REQUIRES_TARGET_OR_QUESTION")
        if value.get("target"):
            validate_ref(value["target"])
        elif not isinstance(value["question"], str) or not value["question"].strip():
            raise ValueError("GOAL_QUESTION")
    if kind == "CampaignSnapshot":
        require_digest(value["campaign_id"])
        require_digest(value["operation_policy"])
        if value.get("parent_snapshot") is not None:
            require_digest(value["parent_snapshot"])
        selections, goals = value["selections"], value["goals"]
        if not isinstance(selections, list) or not isinstance(goals, list):
            raise ValueError("CAMPAIGN_SNAPSHOT_MEMBERSHIP")
        if len(selections) > 1000 or len(goals) > 10_000:
            raise ValueError("CAMPAIGN_SNAPSHOT_LIMIT")
        papers = []
        runs = []
        for selection in selections:
            if set(selection) != {"paper_id", "run_id", "revision"}:
                raise ValueError("CAMPAIGN_SELECTION_FIELDS")
            require_digest(selection["revision"])
            papers.append(selection["paper_id"])
            runs.append(selection["run_id"])
        if len(set(papers)) != len(papers) or len(set(runs)) != len(runs):
            raise ValueError("CAMPAIGN_DUPLICATE_SELECTION")
        for goal in goals:
            validate_record(goal)
            if goal["kind"] != "Goal":
                raise ValueError("CAMPAIGN_GOAL_KIND")
        if len({g["id"] for g in goals}) != len(goals):
            raise ValueError("CAMPAIGN_DUPLICATE_GOAL")


def validate_policy(value: dict[str, Any]) -> None:
    expected = {
        "schema_version",
        "kind",
        "id",
        "allowed_kinds",
        "profile_digest",
        "max_tasks",
        "max_wall_seconds",
        "max_attempts",
        "lease_seconds",
        "source_roots",
        "allow_model",
        "model_max_requests",
        "model_max_tokens",
        "concurrency",
    }
    if set(value) != expected:
        raise ValueError("OPERATION_POLICY_FIELDS")
    allowed = {
        "INGEST_SOURCE",
        "REPARSE_SOURCE",
        "ANALYZE_SOURCE",
        "EXTRACT_RECORDED",
        "EXTRACT_CONFIGURED",
        "FORMALIZE_SUPPORTED",
        "EXACT_COMPUTATION",
        "VERIFY_FORMAL_SUBJECT",
        "AUTHENTICATE_EVIDENCE",
        "REFRESH_EVIDENCE",
        "REASSESS_POLICY",
        "REFRESH_REPORT",
        "SOURCE_FIDELITY_REVIEW",
        "FORMAL_FIDELITY_REVIEW",
        "RESOLVE_CONTEXT",
        "REVIEW_BRIDGE",
    }
    kinds = value["allowed_kinds"]
    if not isinstance(kinds, list) or len(set(kinds)) != len(kinds) or set(kinds) - allowed:
        raise ValueError("OPERATION_POLICY_TASK_KINDS")
    for field, maximum in (
        ("max_tasks", 1000),
        ("max_wall_seconds", 86400),
        ("max_attempts", 5),
        ("lease_seconds", 900),
        ("model_max_requests", 100),
        ("model_max_tokens", 1_000_000),
    ):
        if type(value[field]) is not int or not 0 <= value[field] <= maximum:
            raise ValueError("OPERATION_POLICY_LIMIT: " + field)
    if value["lease_seconds"] < 1 or value["max_attempts"] < 1:
        raise ValueError("OPERATION_POLICY_POSITIVE_LIMIT")
    if type(value["concurrency"]) is not int or value["concurrency"] != 1:
        raise ValueError("OPERATION_POLICY_SINGLE_WORKER")
    if type(value["allow_model"]) is not bool:
        raise ValueError("OPERATION_POLICY_MODEL_FLAG")
    if value["allow_model"] and not (value["model_max_requests"] and value["model_max_tokens"]):
        raise ValueError("OPERATION_POLICY_MODEL_BUDGET_REQUIRED")
    if value["profile_digest"] is not None:
        require_digest(value["profile_digest"])
    roots = value["source_roots"]
    if (
        not isinstance(roots, list)
        or len(roots) > 100
        or any(not isinstance(root, str) or not root or "\x00" in root for root in roots)
    ):
        raise ValueError("OPERATION_POLICY_SOURCE_ROOTS")


def operation_policy(**overrides: Any) -> dict[str, Any]:
    return record(
        "OperationPolicy",
        **{
            "allowed_kinds": [
                "ANALYZE_SOURCE",
                "FORMALIZE_SUPPORTED",
                "EXACT_COMPUTATION",
                "VERIFY_FORMAL_SUBJECT",
                "AUTHENTICATE_EVIDENCE",
                "REFRESH_EVIDENCE",
                "REASSESS_POLICY",
                "REFRESH_REPORT",
            ],
            "profile_digest": None,
            "max_tasks": 20,
            "max_wall_seconds": 600,
            "max_attempts": 2,
            "lease_seconds": 360,
            "source_roots": [],
            "allow_model": False,
            "model_max_requests": 0,
            "model_max_tokens": 0,
            "concurrency": 1,
            **overrides,
        },
    )


REF_FIELDS = {
    "paper_id",
    "run_id",
    "revision",
    "assertion_id",
    "assertion_digest",
    "binding_digest",
    "interpretation_digest",
    "assessment_policy",
}


def validate_ref(ref: dict[str, Any]) -> None:
    if not isinstance(ref, dict) or set(ref) != REF_FIELDS:
        raise ValueError("QUALIFIED_CLAIM_REF_FIELDS")
    for name in REF_FIELDS - {"paper_id", "run_id", "binding_digest"}:
        require_digest(ref[name])
    if ref["binding_digest"] is not None:
        require_digest(ref["binding_digest"])
    if not all(isinstance(ref[k], str) and ref[k] for k in ("paper_id", "run_id")):
        raise ValueError("QUALIFIED_CLAIM_REF_IDENTITY")


@source_validation_operation
def qualified_ref(store: Any, run_id: str, assertion_id: str) -> dict[str, Any]:
    from ..evidence_adapter import POLICY

    bundle = store.inspect(run_id)["bundle"]
    candidates = [a for a in bundle["assertions"] if a["id"] == assertion_id]
    if len(candidates) != 1:
        raise ValueError("CLAIM_MISSING_OR_AMBIGUOUS")
    paper = store.db.execute(
        "SELECT paper_id FROM revisions WHERE id=?", (bundle["input_manifest"]["revision"],)
    ).fetchone()
    if paper is None:
        raise ValueError("QUALIFIED_PAPER_MISSING")
    row: dict[str, Any] = next(
        (r for r in bundle["formalizations"] if r["assertion_id"] == assertion_id), {}
    )
    interpreted = bundle.get("interpreted_ir", bundle["document_ir"])
    element = next(e for e in interpreted["elements"] if e["id"] == assertion_id)
    ref = {
        "paper_id": paper[0],
        "run_id": run_id,
        "revision": bundle["input_manifest"]["revision"],
        "assertion_id": assertion_id,
        "assertion_digest": digest("assertion.v1", candidates[0]),
        "binding_digest": row.get("binding", {}).get("id"),
        "interpretation_digest": digest("campaign-interpretation.v1", element),
        "assessment_policy": digest("acceptance-policy.v1", POLICY),
    }
    validate_ref(ref)
    return ref


def validate_ref_material(store: Any, ref: dict[str, Any]) -> None:
    validate_ref(ref)
    if canonical_bytes(qualified_ref(store, ref["run_id"], ref["assertion_id"])) != canonical_bytes(
        ref
    ):
        raise ValueError("STALE_QUALIFIED_CLAIM_REF")


@dataclass(frozen=True)
class CampaignRecord:
    """Canonical bytes protect persisted records from caller mutation."""

    _canonical: bytes

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CampaignRecord:
        validate_record(value)
        return cls(canonical_bytes(value))

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], strict_loads(self._canonical))
