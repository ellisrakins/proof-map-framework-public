"""SQLite-fenced, event-sourced campaign queue. Task state never grants trust.

Every mutable index value is retained in an immutable TaskEvent. Transactions
use BEGIN IMMEDIATE for claim/finalization, and no verifier runs inside them.
Delivery is at least once after explicit recovery; fenced publication is once.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from ..integrity import canonical_bytes, digest, strict_loads

TERMINAL = {
    "SUCCEEDED",
    "CHECK_FAILED",
    "UNAVAILABLE",
    "ERROR",
    "CANCELLED",
    "STALE",
    "DECISION_RECORDED",
    "REJECTED",
    "BLOCKED",
}
FRESH_EVALUATIONS = {"AUTHENTICATE_EVIDENCE", "REASSESS_POLICY", "REFRESH_REPORT"}
TRANSITIONS = {
    "REQUESTED": {"AUTHORIZED", "BLOCKED", "AWAITING_REVIEW", "STALE", "CANCELLED"},
    "AUTHORIZED": {"QUEUED", "BLOCKED", "STALE", "CANCELLED"},
    "QUEUED": {"RUNNING", "STALE", "CANCELLED", "BLOCKED"},
    "RUNNING": {
        "RUNNING",
        "SUCCEEDED",
        "CHECK_FAILED",
        "UNAVAILABLE",
        "ERROR",
        "CANCELLED",
        "STALE",
        "QUEUED",
    },
    "AWAITING_REVIEW": {"DECISION_RECORDED", "REJECTED", "STALE", "CANCELLED"},
    "UNAVAILABLE": {"QUEUED", "STALE"},
    "ERROR": {"QUEUED", "STALE"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("CAMPAIGN_TIME_REQUIRES_ZONE")
    return parsed.astimezone(timezone.utc)


def migrate(db: sqlite3.Connection) -> None:
    """Add reconstructible indexes; no existing manuscript objects are changed."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS campaign_tasks(
            task_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, state TEXT NOT NULL,
            generation INTEGER NOT NULL, lease_token TEXT, lease_owner TEXT,
            lease_until TEXT, attempt_count INTEGER NOT NULL, projection TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS campaign_tasks_ready ON campaign_tasks(campaign_id,state,task_id);
    """)


def _insert(store: Any, campaign_id: str, value: dict[str, Any]) -> None:
    from .models import validate_record

    validate_record(value)
    body = store.put(canonical_bytes(value))
    old = store.db.execute(
        "SELECT body,campaign_id FROM campaign_records WHERE id=?", (value["id"],)
    ).fetchone()
    if old is not None:
        if old != (body, campaign_id):
            raise ValueError("CAMPAIGN_IMMUTABLE_RECORD_COLLISION")
        return
    sequence = store.db.execute(
        "SELECT COALESCE(MAX(sequence),0)+1 FROM campaign_records"
    ).fetchone()[0]
    store.db.execute(
        "INSERT INTO campaign_records VALUES(?,?,?,?,?)",
        (value["id"], campaign_id, value["kind"], body, sequence),
    )


def _projection(store: Any, task_id: str) -> dict[str, Any]:
    row = store.db.execute(
        "SELECT projection FROM campaign_tasks WHERE task_id=?", (task_id,)
    ).fetchone()
    if row is None:
        raise ValueError("CAMPAIGN_UNKNOWN_TASK")
    return cast(dict[str, Any], strict_loads(store.get(row[0])))


def _publish(
    store: Any,
    campaign_id: str,
    projection: dict[str, Any],
    *,
    actor: str,
    reason: str,
    previous: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .models import record

    event = record(
        "TaskEvent",
        task_id=projection["task_id"],
        campaign_id=campaign_id,
        state=projection["state"],
        previous=previous,
        actor=actor,
        reason=reason,
        created_at=utc_now(),
        projection=projection,
        details=details or {},
    )
    _insert(store, campaign_id, event)
    body = store.put(canonical_bytes(projection))
    store.db.execute(
        "INSERT INTO campaign_tasks VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET state=excluded.state,generation=excluded.generation,lease_token=excluded.lease_token,lease_owner=excluded.lease_owner,lease_until=excluded.lease_until,attempt_count=excluded.attempt_count,projection=excluded.projection",
        (
            projection["task_id"],
            campaign_id,
            projection["state"],
            projection["generation"],
            projection.get("lease_token"),
            projection.get("lease_owner"),
            projection.get("lease_until"),
            projection["attempt_count"],
            body,
        ),
    )
    return event


def enqueue(
    store: Any, campaign_id: str, task: dict[str, Any], *, actor: str, state: str = "QUEUED"
) -> dict[str, Any]:
    """Publish all authorization transitions atomically; duplicate work is reused."""
    if state not in {"QUEUED", "AWAITING_REVIEW", "BLOCKED"}:
        raise ValueError("CAMPAIGN_ENQUEUE_STATE")
    store.db.execute("BEGIN IMMEDIATE")
    try:
        existing = store.db.execute(
            "SELECT task_id FROM campaign_tasks WHERE campaign_id=?", (campaign_id,)
        ).fetchall()
        for (ident,) in existing:
            other = store.get_record(ident)
            projection = _projection(store, ident)
            reusable = (
                projection["state"] in {"QUEUED", "RUNNING"}
                if task["action"]["paper_action"]["kind"] in FRESH_EVALUATIONS
                else projection["state"] not in {"STALE", "CANCELLED"}
            )
            if other["work_key"] == task["work_key"] and reusable:
                _publish(
                    store,
                    campaign_id,
                    projection,
                    actor=actor,
                    reason="SEMANTIC_WORK_REUSED",
                    details={
                        "request_id": task["request_id"],
                        "authorization_id": task["authorization_id"],
                        "requested_task_id": task["id"],
                    },
                )
                store.db.commit()
                return projection
        _insert(store, campaign_id, task)
        projection = {
            "task_id": task["id"],
            "state": "REQUESTED",
            "generation": 0,
            "attempt_count": 0,
            "lease_token": None,
            "lease_owner": None,
            "lease_until": None,
            "attempt_id": None,
            "last_result": None,
            "usage_seconds": 0.0,
            "reserved_seconds": 0,
            "last_event": None,
            "cancel_requested": False,
            "model_reserved_requests": 0,
            "model_reserved_tokens": 0,
            "model_consumed_requests": 0,
            "model_consumed_tokens": 0,
            "model_unknown_effect": False,
        }
        event = _publish(store, campaign_id, projection, actor=actor, reason="EXPLICIT_REQUEST")
        previous = event["id"]
        for target in ["AUTHORIZED", "QUEUED"] if state == "QUEUED" else [state]:
            projection["state"] = target
            event = _publish(
                store,
                campaign_id,
                projection,
                actor=actor,
                reason="EXPLICIT_AUTHORIZATION" if target == "AUTHORIZED" else target,
                previous=previous,
            )
            previous = event["id"]
        store.db.commit()
        return projection
    except BaseException:
        store.db.rollback()
        raise


def tasks(store: Any, campaign_id: str) -> list[dict[str, Any]]:
    return [
        {**store.get_record(ident), **_projection(store, ident)}
        for (ident,) in store.db.execute(
            "SELECT task_id FROM campaign_tasks WHERE campaign_id=? ORDER BY task_id",
            (campaign_id,),
        )
    ]


def transition(
    store: Any,
    task_id: str,
    state: str,
    *,
    actor: str,
    reason: str,
    token: str | None = None,
    generation: int | None = None,
    result: dict[str, Any] | None = None,
    usage_seconds: float = 0.0,
    now: str | None = None,
    publication: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """A late/cancelled worker can retain diagnostics but cannot publish results."""
    task = store.get_record(task_id)
    store.db.execute("BEGIN IMMEDIATE")
    try:
        projection = _projection(store, task_id)
        old = projection["state"]
        if reason == "EXPIRED_LEASE_RECOVERY" and (
            old != "RUNNING"
            or projection["generation"] != generation
            or _time(projection["lease_until"]) > _time(now or utc_now())
        ):
            raise ValueError("CAMPAIGN_RECOVERY_LEASE_RENEWED")
        if token is not None and (
            old != "RUNNING"
            or projection["lease_token"] != token
            or projection["generation"] != generation
            or _time(projection["lease_until"]) <= _time(now or utc_now())
            or (projection.get("cancel_requested", False) and state not in {"CANCELLED", "ERROR"})
        ):
            _publish(
                store,
                task["campaign_id"],
                projection,
                actor=actor,
                reason="FENCED_LATE_RESULT",
                details={"attempt_generation": generation, "discarded_result": result},
            )
            store.db.commit()
            raise ValueError("CAMPAIGN_LEASE_FENCED")
        if state not in TRANSITIONS.get(old, set()):
            raise ValueError("CAMPAIGN_TASK_TRANSITION:" + old + "->" + state)
        if publication is not None:
            publication()
        if result is not None:
            if (
                result.get("task_id") != task_id
                or result.get("generation") != projection["generation"]
                or canonical_bytes(result.get("target")) != canonical_bytes(task["target"])
            ):
                raise ValueError("CAMPAIGN_RESULT_SUBJECT_BINDING")
            evidence = result.get("evidence")
            if (
                evidence
                and "event" in evidence
                and state != "CANCELLED"
                and not projection.get("cancel_requested", False)
            ):
                from ..paper_store import _audit_record

                wrapper = {"record": evidence["event"], "envelope": evidence["envelope"]}
                typed = _audit_record(wrapper)
                if (
                    typed["binding_digest"] != task["target"]["binding_digest"]
                    or typed["revision_id"] != task["target"]["revision"]
                    or typed["assertion_id"] != task["target"]["assertion_id"]
                ):
                    raise ValueError("CAMPAIGN_EXECUTION_SUBJECT_BINDING")
                policy = store.get_record(task["policy_id"])
                if typed["profile_digest"] != policy["profile_digest"]:
                    raise ValueError("CAMPAIGN_EXECUTION_PROFILE_BINDING")
                run_id = task["target"]["run_id"]
                run = store.db.execute("SELECT revision FROM runs WHERE id=?", (run_id,)).fetchone()
                if run != (typed["revision_id"],):
                    raise ValueError("CAMPAIGN_EXECUTION_RUN_BINDING")
                ident = digest("paper-audit.v1", {"run_id": run_id, "record": wrapper})
                sha = store.put(canonical_bytes(wrapper))
                # Evidence, task result, and status become visible in one fence.
                store.db.execute(
                    "INSERT OR IGNORE INTO audit_records VALUES(?,?,?,?,?)",
                    (ident, run_id, typed["revision_id"], "ExecutionEvent", sha),
                )
            _insert(store, task["campaign_id"], result)
            projection["last_result"] = result["id"]
        projection["state"] = state
        projection["usage_seconds"] += max(0.0, usage_seconds)
        if old == "RUNNING" and state != "RUNNING":
            requests = projection.get("model_reserved_requests", 0)
            tokens = projection.get("model_reserved_tokens", 0)
            if result is not None and result.get("model_effect") == "NOT_DISPATCHED":
                requests, tokens = 0, 0
            projection["model_consumed_requests"] = (
                projection.get("model_consumed_requests", 0) + requests
            )
            projection["model_consumed_tokens"] = (
                projection.get("model_consumed_tokens", 0) + tokens
            )
            if requests and state != "SUCCEEDED":
                projection["model_unknown_effect"] = True
            projection["model_reserved_requests"] = 0
            projection["model_reserved_tokens"] = 0
        if state != "RUNNING":
            projection.update(
                lease_token=None, lease_owner=None, lease_until=None, reserved_seconds=0
            )
            if old == "RUNNING":
                projection["generation"] += 1
            if state == "QUEUED":
                projection["cancel_requested"] = False
        event = _publish(store, task["campaign_id"], projection, actor=actor, reason=reason)
        if old == "RUNNING" and state != "RUNNING":
            from .models import record

            attempt = record(
                "TaskAttempt",
                task_id=task_id,
                campaign_id=task["campaign_id"],
                phase="FINISHED",
                parent_attempt=projection["attempt_id"],
                generation=generation,
                state=state,
                result_id=projection["last_result"],
                usage_seconds=usage_seconds,
                model_charged_requests=requests,
                model_charged_tokens=tokens,
                model_unknown_effect=projection.get("model_unknown_effect", False),
                ended_at=utc_now(),
                reason=reason,
            )
            _insert(store, task["campaign_id"], attempt)
        store.db.commit()
        return {**projection, "event_id": event["id"]}
    except BaseException:
        store.db.rollback()
        raise


def claim(
    store: Any,
    campaign_id: str,
    *,
    owner: str,
    lease_seconds: int,
    max_attempts: int,
    reserve_seconds: int,
    max_tasks: int,
    max_wall_seconds: int,
    ready: set[str] | None = None,
    now: str | None = None,
    model_reserve_requests: int = 0,
    model_reserve_tokens: int = 0,
    model_max_requests: int = 0,
    model_max_tokens: int = 0,
) -> dict[str, Any] | None:
    """Claim one task and reserve global campaign budgets under a writer fence."""
    from .models import record

    current = now or utc_now()
    store.db.execute("BEGIN IMMEDIATE")
    try:
        projections = [
            _projection(store, row[0])
            for row in store.db.execute(
                "SELECT task_id FROM campaign_tasks WHERE campaign_id=? ORDER BY task_id",
                (campaign_id,),
            )
        ]
        if any(p["state"] == "RUNNING" for p in projections):
            store.db.commit()
            return None  # The admitted beta execution profile is concurrency=1.
        consumed = sum(p["attempt_count"] for p in projections)
        reserved = sum(p["reserved_seconds"] + p["usage_seconds"] for p in projections)
        if consumed >= max_tasks or reserved + reserve_seconds > max_wall_seconds:
            store.db.commit()
            return None
        model_requests = sum(
            p.get("model_consumed_requests", 0) + p.get("model_reserved_requests", 0)
            for p in projections
        )
        model_tokens = sum(
            p.get("model_consumed_tokens", 0) + p.get("model_reserved_tokens", 0)
            for p in projections
        )
        if model_reserve_requests and (
            model_requests + model_reserve_requests > model_max_requests
            or model_tokens + model_reserve_tokens > model_max_tokens
        ):
            store.db.commit()
            return None
        selected = next(
            (
                p
                for p in projections
                if p["state"] == "QUEUED"
                and p["attempt_count"] < max_attempts
                and not p.get("model_unknown_effect", False)
                and (ready is None or p["task_id"] in ready)
            ),
            None,
        )
        if selected is None:
            store.db.commit()
            return None
        selected.update(
            state="RUNNING",
            generation=selected["generation"] + 1,
            attempt_count=selected["attempt_count"] + 1,
            lease_token=uuid.uuid4().hex,
            lease_owner=owner,
            lease_until=(_time(current) + timedelta(seconds=lease_seconds))
            .isoformat()
            .replace("+00:00", "Z"),
            reserved_seconds=reserve_seconds,
            model_reserved_requests=model_reserve_requests,
            model_reserved_tokens=model_reserve_tokens,
        )
        attempt = record(
            "TaskAttempt",
            task_id=selected["task_id"],
            campaign_id=campaign_id,
            phase="STARTED",
            parent_attempt=selected["attempt_id"],
            generation=selected["generation"],
            lease_owner=owner,
            lease_token=selected["lease_token"],
            started_at=current,
            lease_until=selected["lease_until"],
            reserved_seconds=reserve_seconds,
            model_reserved_requests=model_reserve_requests,
            model_reserved_tokens=model_reserve_tokens,
        )
        selected["attempt_id"] = attempt["id"]
        _insert(store, campaign_id, attempt)
        _publish(store, campaign_id, selected, actor=owner, reason="LEASE_ACQUIRED")
        store.db.commit()
        return selected
    except BaseException:
        store.db.rollback()
        raise


def heartbeat(
    store: Any, task_id: str, token: str, generation: int, *, lease_seconds: int, owner: str
) -> bool:
    store.db.execute("BEGIN IMMEDIATE")
    try:
        projection = _projection(store, task_id)
        if (
            projection["state"] != "RUNNING"
            or projection["generation"] != generation
            or projection["lease_token"] != token
            or _time(projection["lease_until"]) <= _time(utc_now())
            or projection.get("cancel_requested", False)
        ):
            store.db.commit()
            return False
        projection["lease_until"] = (
            (_time(utc_now()) + timedelta(seconds=lease_seconds)).isoformat().replace("+00:00", "Z")
        )
        task = store.get_record(task_id)
        _publish(store, task["campaign_id"], projection, actor=owner, reason="HEARTBEAT")
        store.db.commit()
        return True
    except BaseException:
        store.db.rollback()
        raise


def _retain_for_cleanup(
    store: Any, task_id: str, token: str, generation: int, *, owner: str
) -> bool:
    """One bounded cleanup scope; never resurrect an expired or replaced lease."""
    store.db.execute("BEGIN IMMEDIATE")
    try:
        projection = _projection(store, task_id)
        if (
            projection["state"] != "RUNNING"
            or projection["generation"] != generation
            or projection["lease_token"] != token
            or projection["lease_owner"] != owner
            or _time(projection["lease_until"]) <= _time(utc_now())
        ):
            store.db.commit()
            return False
        projection["lease_until"] = (
            (_time(utc_now()) + timedelta(seconds=15)).isoformat().replace("+00:00", "Z")
        )
        task = store.get_record(task_id)
        _publish(store, task["campaign_id"], projection, actor=owner, reason="BOUNDED_CLEANUP")
        store.db.commit()
        return True
    except BaseException:
        store.db.rollback()
        raise


def cancel_task(store: Any, task_id: str, *, actor: str) -> dict[str, Any]:
    state = _projection(store, task_id)["state"]
    if state in TERMINAL:
        return _projection(store, task_id)
    if state == "RUNNING":
        store.db.execute("BEGIN IMMEDIATE")
        try:
            projection = _projection(store, task_id)
            if projection["state"] == "RUNNING":
                projection["cancel_requested"] = True
                task = store.get_record(task_id)
                _publish(
                    store, task["campaign_id"], projection, actor=actor, reason="CANCEL_REQUESTED"
                )
                store.db.commit()
                return projection
            store.db.commit()
        except BaseException:
            store.db.rollback()
            raise
    return transition(store, task_id, "CANCELLED", actor=actor, reason="OPERATOR_CANCELLED")


def recover(store: Any, campaign_id: str, *, actor: str, now: str | None = None) -> list[str]:
    """Explicitly recover expired leases; retain failed attempts and fence workers."""
    affected = []
    for task in tasks(store, campaign_id):
        if task["state"] == "RUNNING" and _time(task["lease_until"]) <= _time(now or utc_now()):
            # Fenced generation and deadline are rechecked by transition, so a
            # heartbeat arriving between selection and write cannot be stolen.
            try:
                model_pending = task.get("model_reserved_requests", 0) > 0
                transition(
                    store,
                    task["id"],
                    "ERROR" if model_pending else "QUEUED",
                    actor=actor,
                    reason="EXPIRED_LEASE_RECOVERY",
                    generation=task["generation"],
                    now=now,
                )
                affected.append(task["id"])
            except ValueError as exc:
                if str(exc) != "CAMPAIGN_RECOVERY_LEASE_RENEWED":
                    raise
    return affected


def rebuild(store: Any) -> None:
    """Reconstruct task indexes entirely from ordered immutable queue events."""
    rows = store.db.execute(
        "SELECT body FROM campaign_records WHERE kind='TaskEvent' ORDER BY sequence"
    ).fetchall()
    with store.db:
        store.db.execute("DELETE FROM campaign_tasks")
        for (body,) in rows:
            event = strict_loads(store.get(body))
            from .models import validate_record

            validate_record(event)
            p = event["projection"]
            sha = store.put(canonical_bytes(p))
            store.db.execute(
                "INSERT INTO campaign_tasks VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET state=excluded.state,generation=excluded.generation,lease_token=excluded.lease_token,lease_owner=excluded.lease_owner,lease_until=excluded.lease_until,attempt_count=excluded.attempt_count,projection=excluded.projection",
                (
                    p["task_id"],
                    event["campaign_id"],
                    p["state"],
                    p["generation"],
                    p["lease_token"],
                    p["lease_owner"],
                    p["lease_until"],
                    p["attempt_count"],
                    sha,
                ),
            )


def invalidate_changed_tasks(store: Any, campaign_id: str) -> list[str]:
    from .operations import stale_tasks

    return stale_tasks(store, campaign_id)


def retry_task(store: Any, task_id: str, actor: str = "operator") -> dict[str, Any]:
    from .operations import retry_task as retry

    return retry(store, task_id, actor)
