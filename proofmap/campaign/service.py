"""Operator-owned campaign intake, membership, exact goals and capabilities."""

from __future__ import annotations

import stat
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from ..integrity import canonical_bytes, digest
from ..paper import ci
from ..paper_sources import source_validation_operation
from .inventory import unresolved_region_count
from .models import operation_policy, qualified_ref, record, utc_now, validate_policy
from .store import CampaignStore


def initialize(
    store: CampaignStore,
    name: str,
    objective: str,
    *,
    actor: str = "operator",
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or operation_policy()
    validate_policy(policy)
    campaign = record("Campaign", name=name, objective=objective, actor=actor, created_at=utc_now())
    campaign_id = campaign["id"]
    store.add_record(campaign, campaign_id)
    store.add_record(policy, campaign_id)
    snapshot = record(
        "CampaignSnapshot",
        campaign_id=campaign_id,
        objective=objective,
        selections=[],
        goals=[],
        operation_policy=policy["id"],
        parent_snapshot=None,
        actor=actor,
        created_at=utc_now(),
    )
    store.set_current_snapshot(snapshot)
    return {
        "campaign_id": campaign_id,
        "snapshot_id": snapshot["id"],
        "campaign": campaign,
        "operation_status": "INITIALIZED",
        "dispatch_authorized": False,
    }


@source_validation_operation
def snapshot_update(
    store: CampaignStore,
    campaign_id: str,
    *,
    actor: str = "operator",
    selections: list[dict[str, Any]] | None = None,
    goals: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
    reason: str = "MEMBERSHIP_UPDATE",
) -> dict[str, Any]:
    old = store.current_snapshot(campaign_id)
    if policy is not None:
        validate_policy(policy)
        store.add_record(policy, campaign_id)
    snapshot = record(
        "CampaignSnapshot",
        campaign_id=campaign_id,
        objective=old["objective"],
        selections=old["selections"] if selections is None else selections,
        goals=old["goals"] if goals is None else goals,
        operation_policy=policy["id"] if policy else old["operation_policy"],
        parent_snapshot=old["id"],
        actor=actor,
        created_at=utc_now(),
    )
    store.set_current_snapshot(snapshot)
    event = record(
        "CampaignMembershipEvent",
        campaign_id=campaign_id,
        from_snapshot=old["id"],
        to_snapshot=snapshot["id"],
        reason=reason,
        actor=actor,
        created_at=utc_now(),
    )
    store.add_record(event, campaign_id)
    return snapshot


@source_validation_operation
def select_run(
    store: CampaignStore, campaign_id: str, run_id: str, *, actor: str = "operator"
) -> dict[str, Any]:
    stored = store.inspect(run_id)
    bundle = stored["bundle"]
    revision = bundle["input_manifest"]["revision"]
    paper_id = store.db.execute(
        "SELECT paper_id FROM revisions WHERE id=?", (revision,)
    ).fetchone()[0]
    old = store.current_snapshot(campaign_id)
    selection = {"paper_id": paper_id, "run_id": run_id, "revision": revision}
    if selection in old["selections"]:
        return old
    selections = [s for s in old["selections"] if s["paper_id"] != paper_id] + [selection]
    result = snapshot_update(
        store, campaign_id, selections=sorted(selections, key=lambda s: s["paper_id"]), actor=actor
    )
    from .queue import invalidate_changed_tasks

    invalidate_changed_tasks(store, campaign_id)
    return result


def _reject_source_links(path: Path) -> None:
    # Inspect before resolving: resolving a Windows junction loses the evidence
    # that intake crossed a link. st_file_attributes also covers Python 3.10/3.11.
    for candidate in (path.absolute(), *path.absolute().parents):
        attributes = getattr(candidate.lstat(), "st_file_attributes", 0)
        if candidate.is_symlink() or attributes & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024
        ):
            raise ValueError("CAMPAIGN_SOURCE_LINK_FORBIDDEN")


def _manuscripts(input_path: Path, entrypoint: str | None) -> list[tuple[Path, str | None, str]]:
    _reject_source_links(input_path)
    path = input_path.resolve(strict=True)
    if path.is_file():
        if path.suffix.lower() not in {".tex", ".pdf", ".zip", ".tar", ".gz", ".tgz"}:
            raise ValueError("CAMPAIGN_UNSUPPORTED_SOURCE")
        return [(path, entrypoint, path.name)]
    if entrypoint:
        return [(path, entrypoint, path.name)]
    # A main entry point denotes one multi-file manuscript. A collection has
    # standalone files or child directories with their own explicit entry points.
    if (path / "main.tex").is_file():
        return [(path, "main.tex", path.name)]
    entries: list[tuple[Path, str | None, str]] = []
    children = sorted(path.iterdir(), key=lambda p: p.name)
    if len(children) > 1000:
        raise ValueError("CAMPAIGN_CORPUS_LIMIT")
    for child in children:
        _reject_source_links(child)
        if not child.resolve(strict=True).is_relative_to(path):
            raise ValueError("CAMPAIGN_SOURCE_OUTSIDE_COLLECTION")
        if child.is_file() and child.suffix.lower() in {
            ".tex",
            ".pdf",
            ".zip",
            ".tar",
            ".gz",
            ".tgz",
        }:
            entries.append((child, None, child.name))
        elif child.is_dir() and not child.name.startswith("."):
            tex = sorted(child.glob("*.tex"))
            main = child / "main.tex"
            if main.is_file():
                entries.append((child, "main.tex", child.name))
            elif len(tex) == 1:
                entries.append((child, tex[0].name, child.name))
            elif len(tex) > 1:
                raise ValueError("CAMPAIGN_AMBIGUOUS_ENTRYPOINT: " + child.name)
    if not entries:
        raise ValueError("CAMPAIGN_EMPTY_CORPUS")
    return entries


@source_validation_operation
def ingest(
    store: CampaignStore,
    campaign_id: str,
    input_path: Path,
    *,
    extractor: str = "none",
    config: dict[str, Any] | None = None,
    replay: Any = None,
    entrypoint: str | None = None,
    paper_id: str | None = None,
    actor: str = "operator",
    _task_id: str | None = None,
    _lease_token: str | None = None,
    _lease_generation: int | None = None,
    _defer_selection: bool = False,
) -> dict[str, Any]:
    snapshot = store.current_snapshot(campaign_id)
    policy = store.get_record(snapshot["operation_policy"])
    if config is not None and not isinstance(config, dict):
        raise ValueError("CAMPAIGN_EXTRACTOR_CONFIGURATION")
    root = input_path.resolve(strict=True)
    if policy["source_roots"] and not any(
        root.is_relative_to(Path(p).resolve()) for p in policy["source_roots"]
    ):
        raise ValueError("CAMPAIGN_SOURCE_OUTSIDE_OPERATION_POLICY")
    if extractor == "configured" and not policy["allow_model"]:
        raise ValueError("CAMPAIGN_MODEL_DISCLOSURE_NOT_AUTHORIZED")
    if extractor == "configured":
        extractor_config = (config or {}).get("extractor", {})
        if not isinstance(extractor_config, dict):
            raise ValueError("CAMPAIGN_EXTRACTOR_CONFIGURATION")
        if (
            not extractor_config.get("max_requests")
            or extractor_config["max_requests"] > policy["model_max_requests"]
            or not extractor_config.get("max_total_output_tokens")
            or extractor_config["max_total_output_tokens"] > policy["model_max_tokens"]
        ):
            raise ValueError("CAMPAIGN_MODEL_TOKEN_BUDGET")
    manuscripts = _manuscripts(input_path, entrypoint)
    if paper_id and len(manuscripts) != 1:
        raise ValueError("CAMPAIGN_PAPER_ID_REQUIRES_SINGLE_MANUSCRIPT")
    if _defer_selection and _task_id is None:
        raise ValueError("CAMPAIGN_STAGED_INTAKE_REQUIRES_ACQUIRED_TASK")
    if extractor == "configured" and _task_id is None:
        # Configured intake is itself an explicit bounded operation. It shares
        # the campaign queue's durable reservations across documents and calls.
        from . import operations, queue

        stage_tasks = []
        for source, entry, identity in manuscripts:
            inputs = {"source_path": str(source), "paper_id": paper_id or identity}
            if entry is not None:
                inputs["entrypoint"] = entry
            stage_tasks.append(
                operations.request_stage(
                    store,
                    campaign_id,
                    "EXTRACT_CONFIGURED",
                    inputs,
                    policy,
                    actor,
                    config=extractor_config,
                )["task_id"]
            )
        unique_tasks = sorted(set(stage_tasks))
        outcome = operations.run_campaign(
            store,
            campaign_id,
            controller_config={"extractor_config": extractor_config},
            actor=actor,
            task_ids=unique_tasks,
        )
        rows = []
        for task_id in unique_tasks:
            task = store.get_record(task_id)
            projection = queue._projection(store, task_id)
            result = (
                store.get_record(projection["last_result"]) if projection["last_result"] else None
            )
            if result and result.get("evidence", {}).get("manuscripts"):
                rows.extend(result["evidence"]["manuscripts"])
            else:
                rows.append(
                    {
                        "paper_id": task["target"]["paper_id"],
                        "task_id": task_id,
                        "revision": task["target"]["revision"],
                        "intake": "SOURCE_RETAINED_EXTRACTION_NOT_COMPLETED",
                        "task_state": projection["state"],
                        "exit_code": 3,
                    }
                )
        return {
            "campaign_id": campaign_id,
            "snapshot_id": store.current_snapshot(campaign_id)["id"],
            "manuscripts": rows,
            "dispatch_authorized": True,
            "operations": outcome,
            "coverage": coverage(store, campaign_id),
        }
    if _task_id is not None:
        from . import queue

        task = store.get_record(_task_id)
        projection = queue._projection(store, _task_id)
        if (
            len(manuscripts) != 1
            or task["campaign_id"] != campaign_id
            or task["policy_id"] != policy["id"]
            or task["action"]["paper_action"]["kind"]
            != {
                "none": "INGEST_SOURCE",
                "replay": "EXTRACT_RECORDED",
                "configured": "EXTRACT_CONFIGURED",
            }.get(extractor)
            or projection["state"] != "RUNNING"
            or projection.get("cancel_requested")
            or projection["lease_token"] != _lease_token
            or projection["generation"] != _lease_generation
            or projection["lease_owner"] != actor
            or queue._time(projection["lease_until"]) <= queue._time(queue.utc_now())
            or task["target"]["source_path"] != str(root)
            or (
                extractor == "configured"
                and (
                    not projection.get("model_reserved_requests")
                    or projection["model_reserved_requests"] != extractor_config["max_requests"]
                    or projection["model_reserved_tokens"]
                    != extractor_config["max_total_output_tokens"]
                    or task["action"]["config_digest"]
                    != digest("campaign-stage-config.v1", extractor_config)
                )
            )
        ):
            raise ValueError("CAMPAIGN_CONFIGURED_INTAKE_REQUIRES_ACQUIRED_TASK")
    rows = []
    for source, entry, identity in manuscripts:
        selected_paper = paper_id or identity
        previous = next(
            (s for s in snapshot["selections"] if s["paper_id"] == selected_paper), None
        )
        from ..paper_sources import acquire

        manifest, _ = acquire(source, entry)
        if _task_id is not None and manifest.revision != task["target"]["revision"]:
            raise ValueError("CAMPAIGN_CONFIGURED_INTAKE_SUBJECT_CHANGED")
        # The same pinned source/config can be reused without new expensive work.
        if (
            previous
            and previous["revision"] == manifest.revision
            and extractor == "none"
            and not config
        ):
            rows.append({**previous, "intake": "EXACT_PINNED_RUN_REUSED", "exit_code": 0})
            continue
        output = (
            store.root
            / "campaign-intake"
            / digest(
                "campaign-intake-name.v1", {"paper": selected_paper, "revision": manifest.revision}
            )
        )
        if _task_id is not None:
            import tempfile

            from ..integrity import relative_path

            material = task["source_material"]
            with tempfile.TemporaryDirectory(prefix="campaign-source-", dir=store.root) as folder:
                retained = Path(folder).resolve()
                if not retained.is_relative_to(store.root.resolve()):
                    raise ValueError("CAMPAIGN_SOURCE_SNAPSHOT_DESTINATION")
                for name, sha in material["artifacts"].items():
                    target = (retained / relative_path(name)).resolve()
                    if not target.is_relative_to(retained):
                        raise ValueError("CAMPAIGN_SOURCE_SNAPSHOT_DESTINATION")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(store.get(sha))
                retained_manifest, _ = acquire(retained, material["manifest"]["entrypoint"])
                if retained_manifest.revision != manifest.revision:
                    raise ValueError("CAMPAIGN_SOURCE_SNAPSHOT_BINDING")
                bundle, code = ci(
                    retained,
                    output,
                    store.root,
                    extractor=extractor,
                    config=config,
                    replay=replay,
                    entrypoint=retained_manifest.entrypoint,
                    paper_id=selected_paper,
                )
        else:
            bundle, code = ci(
                source,
                output,
                store.root,
                extractor=extractor,
                config=config,
                replay=replay,
                entrypoint=entry,
                paper_id=selected_paper,
            )
        run_id = bundle["run_manifest"]["run_id"]
        if not _defer_selection:
            if _task_id is not None:
                raise ValueError("CAMPAIGN_STAGED_INTAKE_SELECTION_REQUIRES_CONTROLLER_FENCE")
            select_run(store, campaign_id, run_id, actor=actor)
        rows.append(
            {
                "paper_id": selected_paper,
                "run_id": run_id,
                "revision": manifest.revision,
                "intake": "INGESTED_PARTIAL" if code == 3 else "INGESTED",
                "exit_code": code,
            }
        )
    return {
        "campaign_id": campaign_id,
        "snapshot_id": store.current_snapshot(campaign_id)["id"],
        "manuscripts": rows,
        "dispatch_authorized": False,
        "coverage": coverage(store, campaign_id),
    }


@source_validation_operation
def add_goal(
    store: CampaignStore,
    campaign_id: str,
    *,
    run_id: str | None = None,
    assertion_id: str | None = None,
    label: str | None = None,
    question: str | None = None,
    actor: str = "operator",
) -> dict[str, Any]:
    snapshot = store.current_snapshot(campaign_id)
    if question is not None:
        if any((run_id, assertion_id, label)):
            raise ValueError("QUESTION_CANNOT_HAVE_PAPER_ANCHOR")
        goal = record(
            "Goal",
            campaign_id=campaign_id,
            question=question,
            target=None,
            origin="RESEARCHER_QUESTION",
            actor=actor,
        )
    else:
        if not run_id or bool(assertion_id) == bool(label):
            raise ValueError("GOAL_REQUIRES_RUN_AND_EXACT_ASSERTION_OR_LABEL")
        if run_id not in {s["run_id"] for s in snapshot["selections"]}:
            raise ValueError("GOAL_RUN_NOT_SELECTED")
        if label:
            bundle = store.inspect(run_id)["bundle"]
            candidates = [
                e["id"]
                for e in bundle["document_ir"]["elements"]
                if label in e.get("labels", [])
                and e["id"] in {a["id"] for a in bundle["assertions"]}
            ]
            if len(candidates) != 1:
                raise ValueError("GOAL_LABEL_MISSING_OR_AMBIGUOUS")
            assertion_id = candidates[0]
        goal = record(
            "Goal",
            campaign_id=campaign_id,
            target=qualified_ref(store, run_id, str(assertion_id)),
            question=None,
            origin="SOURCE_BOUND_CLAIM",
            actor=actor,
        )
    if any(
        canonical_bytes(g.get("target")) == canonical_bytes(goal.get("target"))
        and g.get("question") == goal.get("question")
        for g in snapshot["goals"]
    ):
        raise ValueError("CAMPAIGN_DUPLICATE_GOAL_TARGET")
    store.add_record(goal, campaign_id)
    snapshot_update(
        store, campaign_id, goals=snapshot["goals"] + [goal], actor=actor, reason="GOAL_ADDED"
    )
    return goal


@source_validation_operation
def rebind_goal(
    store: CampaignStore,
    campaign_id: str,
    goal_id: str,
    run_id: str,
    assertion_id: str,
    *,
    actor: str = "operator",
    reason: str,
) -> dict[str, Any]:
    snapshot = store.current_snapshot(campaign_id)
    old = next((g for g in snapshot["goals"] if g["id"] == goal_id), None)
    if old is None or not old.get("target") or not reason.strip():
        raise ValueError("GOAL_REBINDING_REQUIRES_SOURCE_GOAL_AND_REASON")
    if run_id not in {s["run_id"] for s in snapshot["selections"]}:
        raise ValueError("GOAL_RUN_NOT_SELECTED")
    ref = qualified_ref(store, run_id, assertion_id)
    before = old["target"]
    if before["paper_id"] != ref["paper_id"]:
        raise ValueError("GOAL_REBINDING_CROSS_PAPER_UNSUPPORTED")
    bundle = store.inspect(run_id)["bundle"]
    mapping = next(
        (
            r
            for r in bundle.get("revision_plan", {}).get("rows", [])
            if r["assertion_id"] == assertion_id
            and r.get("previous_assertion_id") == before["assertion_id"]
        ),
        None,
    )
    if mapping is None:
        raise ValueError("GOAL_REBINDING_NO_SOURCE_BACKED_MAPPING")
    new = record(
        "Goal",
        campaign_id=campaign_id,
        target=ref,
        question=None,
        origin="SOURCE_BOUND_CLAIM",
        actor=actor,
        persistent_goal_id=old.get("persistent_goal_id", old["id"]),
    )
    event = record(
        "GoalRebinding",
        campaign_id=campaign_id,
        from_goal=goal_id,
        to_goal=new["id"],
        mapping=mapping,
        reason=reason,
        actor=actor,
        created_at=utc_now(),
    )
    store.add_record(new, campaign_id)
    store.add_record(event, campaign_id)
    snapshot_update(
        store,
        campaign_id,
        goals=[new if g["id"] == goal_id else g for g in snapshot["goals"]],
        actor=actor,
        reason="EXPLICIT_GOAL_REBINDING",
    )
    return event


@source_validation_operation
def coverage(store: CampaignStore, campaign_id: str) -> dict[str, Any]:
    snapshot = store.current_snapshot(campaign_id)
    counts = {
        k: 0
        for k in (
            "discovered",
            "unresolved_regions",
            "supported",
            "selected_goals",
            "attempted",
            "verified",
            "reviewed",
            "accepted",
        )
    }
    inventory = []
    for selection in snapshot["selections"]:
        bundle = store.inspect(selection["run_id"])["bundle"]
        counts["discovered"] += len(bundle["assertions"])
        counts["unresolved_regions"] += unresolved_region_count(
            bundle.get("interpreted_ir", bundle["document_ir"])
        )
        for row in bundle["formalizations"]:
            counts["supported"] += int(row["status"] == "SUPPORTED")
            inventory.append(
                {
                    "ref": qualified_ref(store, selection["run_id"], row["assertion_id"]),
                    "status": row["status"],
                    "reason": row.get("reason"),
                }
            )
    counts["selected_goals"] = len(snapshot["goals"])
    # Formal/current review counts require authenticated external assessment;
    # historical cached labels never establish fresh coverage here.
    return {
        **counts,
        "authority_evaluated": False,
        "overall_denominator": counts["discovered"],
        "full_verification": False,
        "inventory": inventory,
        "unresolved_goals": [
            g["id"]
            for g in snapshot["goals"]
            if g.get("target")
            and g["target"]["run_id"] not in {s["run_id"] for s in snapshot["selections"]}
        ],
    }


@source_validation_operation
def capabilities(
    store: CampaignStore,
    campaign_id: str,
    *,
    profile: dict[str, Any] | None = None,
    controller_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from ..paper_evidence import preflight

    store.current_snapshot(campaign_id)
    packages: dict[str, str | None] = {}
    for package in ("pypdf", "pylatexenc", "cryptography"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    external = controller_config or {}
    configured_extraction = "NOT_CONFIGURED"
    if external.get("extractor_config"):
        from ..extractor import validate_config

        try:
            extractor_config = external["extractor_config"]
            if not isinstance(extractor_config, dict):
                raise ValueError("INVALID_EXTRACTOR_CONFIGURATION")
            validate_config(extractor_config.get("extractor", extractor_config))
            configured_extraction = "CONFIGURED_NOT_PROBED"
        except (ValueError, TypeError, KeyError):
            configured_extraction = "INVALID_CONFIGURATION"
    execution_signing = "NOT_CONFIGURED"
    if external.get("private_key_path"):
        if not packages["cryptography"]:
            execution_signing = "UNAVAILABLE"
        else:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

            try:
                key_path = Path(external["private_key_path"])
                if key_path.stat().st_size != 32:
                    raise ValueError("INVALID_KEY_SIZE")
                Ed25519PrivateKey.from_private_bytes(key_path.read_bytes())
                execution_signing = "AVAILABLE_EXTERNAL_KEY"
            except (OSError, ValueError, TypeError):
                execution_signing = "UNAVAILABLE_OR_INVALID_KEY"
    value = record(
        "CapabilityAssessment",
        campaign_id=campaign_id,
        created_at=utc_now(),
        ingestion="SUPPORTED"
        if all(packages[p] for p in ("pypdf", "pylatexenc"))
        else "UNAVAILABLE",
        recorded_extraction="SUPPORTED",
        configured_extraction=configured_extraction,
        exact_computation="SUPPORTED",
        isolated_lean=preflight(profile),
        execution_signing=execution_signing,
        execution_authority="NOT_EVALUATED",
        fidelity_signing="EXTERNAL_REVIEWER_REQUIRED",
        review_verification="SUPPORTED" if packages["cryptography"] else "UNAVAILABLE",
        archive_export="SUPPORTED",
        report_generation="SUPPORTED",
        parser_packages=packages,
        host_fallback=False,
        coverage=coverage(store, campaign_id),
    )
    store.add_record(value, campaign_id)
    return value
