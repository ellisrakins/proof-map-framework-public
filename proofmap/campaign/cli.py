"""Typed local operator commands. No manuscript-generated command templates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..integrity import load_json, write_json
from . import service
from .models import operation_policy, qualified_ref
from .store import CampaignStore


def _load(path: str | None) -> Any:
    return load_json(path) if path else None


def run(args: argparse.Namespace) -> int:
    from . import operations
    from .portable import audit_campaign, export_campaign, import_campaign
    from .reports import campaign_report_model, candidate_relation, write_campaign_report
    from .revisions import revision_impact

    command = args.campaign_command
    value: Any
    if command == "policy":
        from ..evidence_records import VerifierProfile

        profile = _load(args.execution_profile)
        changes = {
            "max_tasks": args.max_tasks,
            "max_wall_seconds": args.max_wall_seconds,
            "max_attempts": args.max_attempts,
            "lease_seconds": args.lease_seconds,
            "source_roots": [str(Path(root).resolve(strict=True)) for root in args.source_root],
            "allow_model": args.allow_model,
            "model_max_requests": args.model_max_requests,
            "model_max_tokens": args.model_max_tokens,
            "profile_digest": VerifierProfile.from_dict(profile).digest if profile else None,
        }
        if args.allow_kind:
            changes["allowed_kinds"] = args.allow_kind
        value = operation_policy(**changes)
    else:
        store = CampaignStore(Path(args.store))
        try:
            if command == "init":
                value = service.initialize(
                    store, args.name, args.objective, actor=args.actor, policy=_load(args.policy)
                )
            elif command == "list":
                ids = [
                    r[0]
                    for r in store.db.execute(
                        "SELECT id FROM campaign_records WHERE kind='Campaign' ORDER BY sequence"
                    )
                ]
                value = [
                    {
                        "campaign": store.get_record(i),
                        "snapshot_id": store.current_snapshot(i)["id"],
                    }
                    for i in ids
                ]
            elif command == "inspect":
                value = campaign_report_model(store, args.campaign)
            elif command == "capabilities":
                value = service.capabilities(
                    store,
                    args.campaign,
                    profile=_load(args.execution_profile),
                    controller_config=_load(args.controller_config),
                )
            elif command == "ingest":
                value = service.ingest(
                    store,
                    args.campaign,
                    Path(args.input),
                    extractor=args.extractor,
                    config=_load(args.config),
                    replay=_load(args.replay_event),
                    entrypoint=args.entrypoint,
                    paper_id=args.paper_id,
                    actor=args.actor,
                )
            elif command == "select":
                value = service.select_run(store, args.campaign, args.run, actor=args.actor)
            elif command == "goals":
                if args.goal_command == "list":
                    value = store.current_snapshot(args.campaign)["goals"]
                elif args.goal_command == "add":
                    value = service.add_goal(
                        store,
                        args.campaign,
                        run_id=args.run,
                        assertion_id=args.assertion,
                        label=args.label,
                        question=args.question,
                        actor=args.actor,
                    )
                else:
                    value = service.rebind_goal(
                        store,
                        args.campaign,
                        args.goal,
                        args.run,
                        args.assertion,
                        reason=args.reason,
                        actor=args.actor,
                    )
            elif command == "plan":
                value = operations.plan_campaign(
                    store,
                    args.campaign,
                    formal_scope=args.formal_scope,
                    profile=_load(args.execution_profile),
                    trust_store=_load(args.trust_store),
                    evaluation_time=args.evaluation_time,
                )
            elif command == "authorize":
                value = operations.authorize_plan(
                    store,
                    args.campaign,
                    _load(args.plan),
                    _load(args.policy),
                    args.actor,
                    action_ids=args.action,
                )
            elif command == "request-stage":
                if args.source:
                    inputs = {"source_path": args.source}
                    if args.entrypoint:
                        inputs["entrypoint"] = args.entrypoint
                    if args.paper_id:
                        inputs["paper_id"] = args.paper_id
                else:
                    if not args.run or not args.assertion:
                        raise ValueError("STAGE_REQUIRES_SOURCE_OR_RUN_AND_ASSERTION")
                    inputs = {"run_id": args.run, "assertion_id": args.assertion}
                value = operations.request_stage(
                    store,
                    args.campaign,
                    args.kind,
                    inputs,
                    _load(args.policy),
                    args.actor,
                    config=_load(args.config),
                    replay=_load(args.replay_event),
                )
            elif command == "run":
                value = operations.run_campaign(
                    store,
                    args.campaign,
                    controller_config=_load(args.controller_config),
                    max_tasks=args.max_tasks,
                    max_wall_seconds=args.max_wall_seconds,
                    until=args.until,
                    actor=args.actor,
                )
            elif command == "tasks":
                value = operations.tasks(store, args.campaign)
            elif command == "cancel":
                value = operations.cancel_task(store, args.task, args.actor)
            elif command == "retry":
                from .queue import retry_task

                value = retry_task(store, args.task, args.actor)
            elif command == "recover":
                value = operations.recover(store, args.campaign, args.actor)
            elif command == "review-packet":
                value = operations.review_packets(
                    store, args.campaign, out=Path(args.out), profile=_load(args.execution_profile)
                )
                # The packet command owns its output directory.
                print(json.dumps(value, indent=2, ensure_ascii=True))
                return 0
            elif command == "review-decision":
                if args.out and args.key and Path(args.out).resolve() == Path(args.key).resolve():
                    raise ValueError("REVIEW_OUTPUT_CANNOT_OVERWRITE_KEY")
                value = operations.review_decision(
                    store,
                    args.campaign,
                    args.run,
                    args.assertion,
                    _load(args.execution_profile),
                    args.dimension,
                    args.decision,
                    args.reviewer_id,
                    key=Path(args.key).read_bytes() if args.key else None,
                    reason=args.reason,
                )
            elif command == "review-apply":
                value = operations.apply_decision(
                    store,
                    args.campaign,
                    args.run,
                    _load(args.review),
                    _load(args.execution_profile),
                    _load(args.trust_store),
                    args.evaluation_time,
                )
            elif command == "assess":
                value = operations.assess_campaign(
                    store,
                    args.campaign,
                    _load(args.execution_profile),
                    _load(args.trust_store),
                    args.evaluation_time,
                )
            elif command == "impact":
                value = revision_impact(
                    store, args.campaign, args.from_snapshot, args.to_snapshot, actor=args.actor
                )
            elif command == "relation":
                value = candidate_relation(
                    store,
                    args.campaign,
                    qualified_ref(store, args.left_run, args.left_assertion),
                    qualified_ref(store, args.right_run, args.right_assertion),
                    relation=args.relation,
                    reason=args.reason,
                    actor=args.actor,
                )
            elif command == "report":
                value = write_campaign_report(
                    store,
                    args.campaign,
                    Path(args.out),
                    execution_profile=_load(args.execution_profile),
                    trust_store=_load(args.trust_store),
                    evaluation_time=args.evaluation_time,
                )
                print(
                    json.dumps(
                        {
                            "campaign_id": args.campaign,
                            "out": args.out,
                            "snapshot_id": value.get("snapshot_id"),
                        },
                        indent=2,
                    )
                )
                return 0
            elif command == "export":
                value = export_campaign(
                    store,
                    args.campaign,
                    Path(args.out),
                    include_source=args.include_source,
                    qualification_files=_load(args.qualification_files),
                    qualification_identity=_load(args.qualification_identity),
                )
                print(json.dumps(value, indent=2, ensure_ascii=True))
                return 0
            elif command == "import":
                value = import_campaign(Path(args.archive), store)
            elif command == "audit":
                value = audit_campaign(store, args.campaign)
            else:
                raise ValueError("UNKNOWN_CAMPAIGN_COMMAND")
        finally:
            store.close()
    if getattr(args, "out", None):
        write_json(args.out, value)
        if command not in {"init", "policy"}:
            print(
                json.dumps(
                    {
                        "command": command,
                        "out": args.out,
                        "record_id": value.get("id") if isinstance(value, dict) else None,
                    },
                    indent=2,
                )
            )
        else:
            print(json.dumps(value, indent=2, ensure_ascii=True))
    else:
        print(json.dumps(value, indent=2, ensure_ascii=True))
    if isinstance(value, dict) and value.get("operation_status") in {"ERROR", "BLOCKED"}:
        return 3
    return 0


def run_conops(args: argparse.Namespace) -> int:
    from .conops import run_research_conops

    value = run_research_conops(
        Path(args.out),
        profile=args.profile,
        execution_profile=_load(args.execution_profile),
        wheel=Path(args.wheel) if args.wheel else None,
        candidate_identity=_load(args.identity),
        fixtures=Path(args.fixtures) if args.fixtures else None,
    )
    print(
        json.dumps(
            {
                "validation": value.get("validation"),
                "profile": value.get("profile"),
                "checks": value.get("checks"),
                "out": args.out,
                "material": value.get("material"),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0 if value.get("validation") == "PASS" else 3


def run_pilot(args: argparse.Namespace) -> int:
    from .pilot import evaluate_realism

    value = evaluate_realism(
        Path(args.corpus),
        Path(args.out),
        live_config=_load(args.live_config),
        disclosure_authorized=args.authorize_disclosure,
    )
    print(json.dumps(value, indent=2, ensure_ascii=True))
    return 0


def run_dossier_utility(args: argparse.Namespace) -> int:
    from .portable import extract_dossier_report, preserve_qualification, verify_dossier

    if args.dossier_command == "preserve":
        files = {name: Path(path) for name, path in load_json(args.files).items()}
        value = preserve_qualification(files, Path(args.out), identity=load_json(args.identity))
    elif args.dossier_command == "extract-report":
        value = extract_dossier_report(Path(args.archive), Path(args.out))
    else:
        value = verify_dossier(Path(args.archive))
    print(
        json.dumps(
            {"id": value.get("id"), "integrity": "PASS", "out": getattr(args, "out", None)},
            indent=2,
        )
    )
    return 0


def add_commands(sub: Any) -> None:
    campaign = sub.add_parser("campaign", help="Persistent bounded local research operations")
    commands = campaign.add_subparsers(dest="campaign_command", required=True)

    def parser(name: str, help_text: str, *, target: bool = True, output: bool = False) -> Any:
        p = commands.add_parser(name, help=help_text)
        if target:
            p.add_argument("campaign", help="Exact campaign ID returned by init")
        p.add_argument("--store", default=".paper-store")
        p.add_argument("--actor", default="operator")
        p.add_argument("--out", required=output)
        p.set_defaults(func=run)
        return p

    def authority(p: Any, *, required: bool = False) -> None:
        p.add_argument("--execution-profile", required=required)
        p.add_argument("--trust-store", required=required)
        p.add_argument("--evaluation-time", required=required, help="Explicit UTC evaluation time")

    p = parser("init", "Create objective and immutable empty snapshot", target=False)
    p.add_argument("--name", required=True)
    p.add_argument("--objective", required=True)
    p.add_argument("--policy")
    parser("list", "List campaigns", target=False)
    parser("inspect", "Inspect shared campaign report as JSON")
    p = parser("policy", "Generate an operator-owned bounded operation policy", target=False)
    p.add_argument("--execution-profile")
    p.add_argument("--allow-kind", action="append")
    p.add_argument("--source-root", action="append", default=[])
    p.add_argument("--max-tasks", type=int, default=20)
    p.add_argument("--max-wall-seconds", type=int, default=600)
    p.add_argument("--max-attempts", type=int, default=2)
    p.add_argument("--lease-seconds", type=int, default=360)
    p.add_argument("--allow-model", action="store_true")
    p.add_argument("--model-max-requests", type=int, default=0)
    p.add_argument("--model-max-tokens", type=int, default=0)
    p = parser("capabilities", "Assess this host without dispatch")
    p.add_argument("--execution-profile")
    p.add_argument("--controller-config")
    p = parser("ingest", "Automatically ingest a local TeX/PDF collection")
    p.add_argument("input")
    p.add_argument("--extractor", choices=["none", "configured", "replay"], default="none")
    p.add_argument("--config")
    p.add_argument("--replay-event")
    p.add_argument("--entrypoint")
    p.add_argument("--paper-id")
    p = parser("select", "Pin an existing immutable paper run")
    p.add_argument("--run", required=True)

    g = commands.add_parser(
        "goals", help="Exact claim goals or separately labeled research questions"
    )
    goals = g.add_subparsers(dest="goal_command", required=True)
    for name in ("add", "list", "rebind"):
        p = goals.add_parser(name)
        p.add_argument("campaign")
        p.add_argument("--store", default=".paper-store")
        p.add_argument("--actor", default="operator")
        p.add_argument("--out")
        p.set_defaults(func=run)
        if name == "add":
            p.add_argument("--run")
            targets = p.add_mutually_exclusive_group(required=True)
            targets.add_argument("--assertion")
            targets.add_argument("--label")
            targets.add_argument("--question")
        elif name == "rebind":
            p.add_argument("--goal", required=True)
            p.add_argument("--run", required=True)
            p.add_argument("--assertion", required=True)
            p.add_argument("--reason", required=True)
    p = parser("plan", "Aggregate existing planner; never dispatch")
    p.add_argument("--formal-scope", choices=["supported", "selected", "all"], default="supported")
    authority(p)
    p = parser("authorize", "Explicitly authorize exact tasks under an external bounded policy")
    p.add_argument("--plan", required=True)
    p.add_argument("--policy", required=True)
    p.add_argument("--action", action="append")
    p = parser("request-stage", "Explicitly authorize bounded intake/extraction/pure stage work")
    p.add_argument(
        "--kind",
        choices=[
            "INGEST_SOURCE",
            "REPARSE_SOURCE",
            "EXTRACT_RECORDED",
            "EXTRACT_CONFIGURED",
            "ANALYZE_SOURCE",
            "FORMALIZE_SUPPORTED",
            "EXACT_COMPUTATION",
            "REASSESS_POLICY",
            "REFRESH_REPORT",
        ],
        required=True,
    )
    p.add_argument("--policy", required=True)
    p.add_argument("--source")
    p.add_argument("--entrypoint")
    p.add_argument("--paper-id")
    p.add_argument("--run")
    p.add_argument("--assertion")
    p.add_argument("--config")
    p.add_argument("--replay-event")
    p = parser("run", "Execute the authorized queue synchronously until a work/review boundary")
    p.add_argument("--until", choices=["review", "idle"], default="review")
    p.add_argument("--max-tasks", type=int)
    p.add_argument("--max-wall-seconds", type=int)
    p.add_argument("--controller-config")
    parser("tasks", "Inspect work states and attempts")
    p = parser("cancel", "Cancel a task and request bounded worker cleanup", target=False)
    p.add_argument("task")
    p = parser(
        "retry", "Explicitly retry eligible failed work within its attempt budget", target=False
    )
    p.add_argument("task")
    parser("recover", "Recover interrupted attempts under bounded policy")
    p = parser("review-packet", "Export exact source/formal reviewer handoffs", output=True)
    p.add_argument("--execution-profile")
    p = parser(
        "review-decision", "Explicit approve/reject/abstain; optional external reviewer signing"
    )
    p.add_argument("--run", required=True)
    p.add_argument("--assertion", required=True)
    p.add_argument("--execution-profile", required=True)
    p.add_argument("--dimension", choices=["source-fidelity", "formal-fidelity"], required=True)
    p.add_argument("--decision", choices=["APPROVE", "REJECT", "ABSTAIN"], required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--reviewer-id", required=True)
    p.add_argument("--key", help="External reviewer private key; never persisted or exported")
    p = parser("review-apply", "Apply externally signed reviews through existing trust checks")
    p.add_argument("--run", required=True)
    p.add_argument("--review", required=True)
    authority(p, required=True)
    p = parser("assess", "Fresh evaluation under supplied external authority")
    authority(p, required=True)
    p = parser("impact", "Compare exact snapshots and dependency-aware revision reuse")
    p.add_argument("--from", dest="from_snapshot", required=True)
    p.add_argument("--to", dest="to_snapshot", required=True)
    p = parser("relation", "Record a namespaced candidate relation without deductive closure")
    p.add_argument("--left-run", required=True)
    p.add_argument("--left-assertion", required=True)
    p.add_argument("--right-run", required=True)
    p.add_argument("--right-assertion", required=True)
    p.add_argument(
        "--relation",
        choices=["CITES", "CANDIDATE_DEPENDENCY", "POSSIBLE_DUPLICATE", "POSSIBLE_CONTRADICTION"],
        required=True,
    )
    p.add_argument("--reason", required=True)
    p = parser("report", "Write navigable offline JSON/Markdown/HTML and graph ledger", output=True)
    authority(p)
    p = parser(
        "export", "Save a validated hashed local dossier; raw source requires opt-in", output=True
    )
    p.add_argument("--include-source", action="store_true")
    p.add_argument("--qualification-files")
    p.add_argument("--qualification-identity")
    p = parser(
        "import", "Validate and restore; imported work requires new authorization", target=False
    )
    p.add_argument("archive")
    parser("audit", "Verify retained records, references and task projections")

    p = sub.add_parser(
        "validate-research-conops", help="Run installed campaign operational scenarios"
    )
    p.add_argument("--profile", choices=["offline", "isolated"], default="offline")
    p.add_argument("--execution-profile")
    p.add_argument("--wheel")
    p.add_argument("--identity")
    p.add_argument(
        "--fixtures",
        help="Explicit retained operational corpus for installed-package qualification",
    )
    p.add_argument("--out", required=True)
    p.set_defaults(func=run_conops)
    p = sub.add_parser(
        "campaign-pilot",
        help="Measure rights-backed corpus intake; optional explicit live evaluation",
    )
    p.add_argument("--corpus", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--live-config")
    p.add_argument("--authorize-disclosure", action="store_true")
    p.set_defaults(func=run_pilot)
    p = sub.add_parser(
        "preserve-qualification",
        help="Retain selected local software evidence with identity and checksums",
    )
    p.add_argument(
        "--files", required=True, help="Operator-owned JSON mapping archive names to local files"
    )
    p.add_argument("--identity", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=run_dossier_utility, dossier_command="preserve")
    p = sub.add_parser(
        "inspect-dossier",
        help="Verify a local dossier or extract its non-authoritative offline report",
    )
    p.add_argument("archive")
    p.add_argument("--out")
    p.set_defaults(
        func=lambda args: run_dossier_utility(
            argparse.Namespace(
                **vars(args), dossier_command="extract-report" if args.out else "verify"
            )
        )
    )
