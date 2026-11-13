from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .integrity import load_json, write_json
from .paper import ci, diff, load_bundle, review_apply, review_export
from .paper_store import PaperStore


def run(args: argparse.Namespace) -> int:
    value: Any
    command = args.paper_command
    if command == "preflight":
        from .paper_evidence import preflight

        value = preflight(load_json(args.execution_profile) if args.execution_profile else None)
        print(json.dumps(value, indent=2))
        return 0 if value["execution"] == "READY" else 3
    if command == "review-sign":
        from .paper_evidence import sign_fidelity_draft

        if Path(args.out).resolve() in {Path(args.draft).resolve(), Path(args.key).resolve()}:
            raise ValueError("Output must not overwrite a draft or private key")
        write_json(
            args.out, sign_fidelity_draft(load_json(args.draft), Path(args.key).read_bytes())
        )
        return 0
    if command == "benchmark":
        from .benchmark import benchmark

        value = benchmark(Path(args.corpus))
        write_json(args.out, value)
        print(json.dumps({"sample_size": value["sample_size"], "out": args.out}))
        return 0
    if command in {"ci", "resume"}:
        if bool(args.candidate) != bool(args.candidate_for):
            raise ValueError("--candidate and --candidate-for must be supplied together")
        if args.candidate and Path(args.candidate).stat().st_size > 128:
            raise ValueError("UNSUPPORTED_CANDIDATE: maximum 128 bytes")
        bundle, code = ci(
            Path(args.input),
            Path(args.out),
            Path(args.store),
            extractor=args.extractor,
            config=load_json(args.config) if args.config else None,
            parser=args.parser,
            entrypoint=args.entrypoint,
            paper_id=args.paper_id,
            replay=load_json(args.replay_event) if args.replay_event else None,
            execution_profile=load_json(args.execution_profile) if args.execution_profile else None,
            controller_key=Path(args.controller_key).read_bytes() if args.controller_key else None,
            controller_id=args.controller_id,
            trust_store=load_json(args.trust_store) if args.trust_store else None,
            evaluation_time=args.evaluation_time,
            require_formal=args.require_formal,
            resume=command == "resume",
            candidate_overrides={args.candidate_for: Path(args.candidate).read_bytes()}
            if args.candidate
            else None,
        )
        print(json.dumps(bundle["run_manifest"], indent=2))
        return code
    if command == "diff":
        value = diff(load_bundle(Path(args.old)), load_bundle(Path(args.new)))
    elif command == "override-export":
        from .paper_overrides import override_export

        value = override_export(load_bundle(Path(args.bundle)), args.author)
    elif command == "override-apply":
        from .paper_overrides import apply_override

        store = PaperStore(Path(args.store))
        try:
            derived = apply_override(
                load_bundle(Path(args.bundle)), load_json(args.override), store, Path(args.out)
            )
            print(json.dumps(derived["run_manifest"], indent=2))
            return 0
        finally:
            store.close()
    elif command == "report":
        from .paper_reports import write_reports

        bundle = load_bundle(Path(args.bundle))
        store = PaperStore(Path(args.store))
        try:
            indexed = store.inspect(bundle["run_manifest"]["run_id"])
            from .integrity import canonical_bytes

            if canonical_bytes(indexed["bundle"]) != canonical_bytes(bundle):
                raise ValueError("REPORT_REQUIRES_IMMUTABLE_INDEXED_RUN")
            artifacts = {name: store.get(sha) for name, sha in indexed["artifacts"].items()}
            reviews = store.list_reviews(
                bundle["input_manifest"]["revision"], bundle["run_manifest"]["analysis_digest"]
            )
            model = write_reports(bundle, Path(args.out), artifacts, reviews=reviews)
            print(
                json.dumps({"run": model["run"], "claims": len(model["claims"]), "out": args.out})
            )
            return 0
        finally:
            store.close()
    elif command in {"review-export", "assess"}:
        bundle = load_bundle(Path(args.bundle))
        if command == "review-export" and args.dimension:
            from .paper_evidence import fidelity_draft

            if not args.assertion or not args.execution_profile:
                raise ValueError("Fidelity review requires --assertion and --execution-profile")
            value = fidelity_draft(
                bundle,
                args.assertion,
                load_json(args.execution_profile),
                args.dimension,
                args.author,
            )
        elif command == "assess" and args.trust_store:
            from .paper_evidence import reassess, report_assessment

            if not args.execution_profile or not args.evaluation_time:
                raise ValueError(
                    "Current assessment requires external profile and explicit evaluation time"
                )
            store = PaperStore(Path(args.store))
            try:
                value = reassess(
                    bundle,
                    store,
                    load_json(args.execution_profile),
                    load_json(args.trust_store),
                    args.evaluation_time,
                )
                if args.report_out:
                    report_assessment(bundle, value, store, Path(args.report_out))
            finally:
                store.close()
        else:
            value = (
                review_export(bundle, args.author)
                if command == "review-export"
                else {
                    **bundle["assessment"],
                    "assessment_scope": "HISTORICAL_RUN_SNAPSHOT; current authority requires --trust-store, --execution-profile and --evaluation-time",
                }
            )
    else:
        store = PaperStore(Path(args.store))
        try:
            if command == "query":
                from .paper_reports import query_store

                value = query_store(
                    store,
                    paper=args.paper,
                    revision=args.revision,
                    role=args.role,
                    state=args.state,
                    finding=args.finding,
                )
            elif command == "list":
                value = store.list(args.query)
            elif command == "inspect":
                value = store.inspect(args.run)
                if args.view == "review" or args.assertion:
                    from .paper_reports import report_model

                    bundle = value["bundle"]
                    artifacts = {name: store.get(sha) for name, sha in value["artifacts"].items()}
                    reviews = store.list_reviews(
                        bundle["input_manifest"]["revision"],
                        bundle["run_manifest"]["analysis_digest"],
                    )
                    value = report_model(bundle, artifacts, reviews)
                    if args.assertion:
                        matches = [
                            row
                            for row in value["claims"]
                            if row["id"] == args.assertion or row["title"] == args.assertion
                        ]
                        if len(matches) != 1:
                            raise ValueError("UNKNOWN_OR_AMBIGUOUS_ASSERTION")
                        value = matches[0]
            elif command == "rebuild":
                store.rebuild()
                value = {"rebuilt": True}
            else:
                review = load_json(args.review)
                if "payloadType" in review:
                    from .paper_evidence import apply_fidelity, report_assessment

                    if (
                        not args.execution_profile
                        or not args.trust_store
                        or not args.evaluation_time
                    ):
                        raise ValueError(
                            "Authenticated review requires external profile, trust store and evaluation time"
                        )
                    value = apply_fidelity(
                        load_bundle(Path(args.bundle)),
                        review,
                        store,
                        load_json(args.execution_profile),
                        load_json(args.trust_store),
                        args.evaluation_time,
                    )
                    if args.report_out:
                        report_assessment(
                            load_bundle(Path(args.bundle)), value, store, Path(args.report_out)
                        )
                else:
                    value = {
                        "review_digest": review_apply(
                            load_bundle(Path(args.bundle)), review, store
                        ),
                        "accepted_proof": False,
                    }
        finally:
            store.close()
    if getattr(args, "out", None):
        write_json(args.out, value)
    else:
        print(json.dumps(value, indent=2, ensure_ascii=True))
    return 0


def add_commands(sub: Any) -> None:
    paper = sub.add_parser("paper", help="Source-faithful manuscript CI; conformance is not proof")
    commands = paper.add_subparsers(dest="paper_command", required=True)
    p = commands.add_parser(
        "preflight",
        help="Check local isolated verification capability without downloading or executing Lean",
    )
    p.add_argument("--execution-profile")
    p.set_defaults(func=run)
    p = commands.add_parser(
        "review-sign",
        help="Sign an explicitly APPROVE/REJECT fidelity draft using reviewer authority",
    )
    p.add_argument("draft")
    p.add_argument("--key", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=run)
    benchmark_parser = commands.add_parser("benchmark")
    benchmark_parser.add_argument("--corpus", required=True)
    benchmark_parser.add_argument("--out", required=True)
    benchmark_parser.set_defaults(func=run)
    p = commands.add_parser(
        "ci",
        aliases=["resume"],
        help="Ingest and analyze; resume reuses validated pure stages for identical source/configuration",
    )
    p.add_argument("input")
    p.add_argument("--extractor", choices=["none", "configured", "replay"], default="none")
    p.add_argument("--config")
    p.add_argument(
        "--replay-event",
        help="Recorded extraction_events.json, document replay, or legacy single event",
    )
    p.add_argument("--parser", choices=["auto", "pylatexenc", "pypdf"], default="auto")
    p.add_argument("--policy", choices=["paper-ci-alpha-v1"], default="paper-ci-alpha-v1")
    p.add_argument("--entrypoint")
    p.add_argument("--paper-id")
    p.add_argument(
        "--candidate", help="Explicit author proof program in the approved bounded grammar"
    )
    p.add_argument(
        "--candidate-for",
        help="Exact source assertion ID to bind --candidate; the source supplies the target",
    )
    p.add_argument(
        "--execution-profile",
        help="External prepared Lean/Std profile JSON; never read from manuscript configuration",
    )
    p.add_argument(
        "--require-formal",
        action="store_true",
        help="Require complete formal coverage of discovered theorem-like claims",
    )
    p.add_argument(
        "--controller-key", help="Controller-side raw Ed25519 key; never mounted into the worker"
    )
    p.add_argument("--controller-id", default="local-unsigned")
    p.add_argument("--trust-store", help="External role/subject/profile-scoped public authorities")
    p.add_argument(
        "--evaluation-time", help="Explicit UTC time for current trust validity/revocation checks"
    )
    p.add_argument("--out", required=True)
    p.add_argument("--store", default=".paper-store")
    p.set_defaults(func=run)
    for name in ("list", "inspect", "query", "rebuild", "review-apply"):
        p = commands.add_parser(name)
        p.add_argument("--store", default=".paper-store")
        if name == "list":
            p.add_argument("--query", default="")
        elif name == "inspect":
            p.add_argument("run")
            p.add_argument("--view", choices=["bundle", "review"], default="bundle")
            p.add_argument("--assertion", help="Exact assertion ID or unique label")
        elif name == "query":
            p.add_argument("--paper", default="", help="Paper identifier substring")
            p.add_argument("--revision")
            p.add_argument("--role")
            p.add_argument("--state")
            p.add_argument("--finding")
            p.add_argument("--out")
        elif name == "review-apply":
            p.add_argument("bundle")
            p.add_argument("review")
            p.add_argument("--execution-profile")
            p.add_argument("--trust-store")
            p.add_argument("--evaluation-time")
            p.add_argument(
                "--report-out", help="Write a separate current JSON/Markdown/HTML/SARIF view"
            )
        p.set_defaults(func=run)
    for name in ("override-export", "override-apply", "report"):
        p = commands.add_parser(name)
        p.add_argument("bundle")
        p.add_argument("--out", required=True)
        if name == "override-export":
            p.add_argument(
                "--author",
                required=True,
                help="Attribution only; does not authenticate or accept proofs",
            )
        else:
            p.add_argument("--store", default=".paper-store")
        if name == "override-apply":
            p.add_argument("override")
        p.set_defaults(func=run)
    for name in ("diff", "review-export", "assess"):
        p = commands.add_parser(name)
        if name == "diff":
            p.add_argument("old")
            p.add_argument("new")
        else:
            p.add_argument("bundle")
        if name == "review-export":
            p.add_argument("--author", required=True)
            p.add_argument("--dimension", choices=["source-fidelity", "formal-fidelity"])
            p.add_argument("--assertion")
            p.add_argument("--execution-profile")
        if name == "assess":
            p.add_argument("--execution-profile")
            p.add_argument("--trust-store")
            p.add_argument("--evaluation-time")
            p.add_argument("--store", default=".paper-store")
            p.add_argument(
                "--report-out", help="Write a separate current JSON/Markdown/HTML/SARIF view"
            )
        p.add_argument("--out")
        p.set_defaults(func=run)
