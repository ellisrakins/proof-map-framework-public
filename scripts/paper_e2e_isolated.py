"""Mandatory installed-wheel integration; missing infrastructure is a failure, never a skip."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import venv
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MANUSCRIPT = r"""\documentclass{article}
\newtheorem{theorem}{Theorem}
\begin{document}
\begin{theorem}\label{runtime-derived}
For every $z\in\mathbb{Z}$, \[(z+3)^2=z^2+6*z+9\].
\end{theorem}
\end{document}
"""

BRANCH_MANUSCRIPT = r"""\documentclass{article}
\newtheorem{theorem}{Theorem}
\begin{document}
{\newcommand{\offset}{1}
\begin{theorem}\label{branch-a}
For every $x\in\mathbb{Z}$, \[(x+\offset)^2=x^2+2*\offset*x+\offset^2.\]
\end{theorem}}
{\begin{theorem}\label{branch-b}
For every $x\in\mathbb{Z}$, if $x=2$, then \[x^2=4.\]
\end{theorem}}
\end{document}
"""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validator_revision(repository: Path) -> str:
    """Resolve checkout identity before copying the driver out of its repository."""
    revision = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD^{commit}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    check(bool(re.fullmatch(r"[a-f0-9]{40}", revision)), "Invalid validator revision")
    return revision


def data_only_check(
    corpus_script: Path, submission: Path, output: Path, validator_sha: str, manuscript_sha: str
) -> dict[str, Any]:
    from proofmap.integrity import load_json

    check(
        all(re.fullmatch(r"[a-f0-9]{40}", value) for value in (validator_sha, manuscript_sha)),
        "Invalid data-only revision",
    )
    subprocess.run(
        [
            sys.executable,
            "-I",
            str(corpus_script),
            str(submission / "papers"),
            str(output),
            "--validator-sha",
            validator_sha,
            "--manuscript-sha",
            manuscript_sha,
        ],
        cwd=submission,
        check=True,
        timeout=120,
    )
    summary = load_json(output / "summary.json")
    check(
        summary["status"] == "PASS" and summary["paper_count"] == 1,
        "Data-only integration did not inspect manuscript",
    )
    check(
        summary.get("validator_sha") == validator_sha
        and summary.get("manuscript_sha") == manuscript_sha,
        "Data-only integration revision provenance mismatch",
    )
    return dict(summary)


def independent_revision_scenario(
    root: Path,
    profile_dict: dict[str, Any],
    keys: dict[str, bytes],
    authority: dict[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    """Installed real execution: change only A's definition and measure reuse of B."""
    from proofmap.evidence_records import FormalizationBinding, ReviewDecision, VerifierProfile
    from proofmap.paper import ci
    from proofmap.paper_evidence import apply_fidelity, reassess
    from proofmap.paper_sources import acquire, parse
    from proofmap.paper_store import PaperStore
    from proofmap.trust import sign_record

    root.mkdir()
    manuscript = root / "branches.tex"
    manuscript.write_text(BRANCH_MANUSCRIPT, encoding="utf-8")
    trust = deepcopy(authority)
    profile = VerifierProfile.from_dict(profile_dict)
    options: dict[str, Any] = {
        "paper_id": "original-independent-branches",
        "execution_profile": profile_dict,
        "controller_key": keys["ci-ephemeral-controller"],
        "controller_id": "ci-ephemeral-controller",
        "trust_store": trust,
        "evaluation_time": timestamp,
        "require_formal": True,
    }

    def authorize_source() -> None:
        manifest, artifacts = acquire(manuscript)
        ir = parse(manifest, artifacts)
        subjects = [row["id"] for row in ir["elements"] if row["kind"] == "ASSERTION"]
        check(len(subjects) == 2, "Independent fixture must extract two source assertions")
        for key in trust["keys"]:
            key["subjects"] = sorted(set(key["subjects"] + subjects))

    def approve(bundle: dict[str, Any], store: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        envelopes = []
        assessment = reassess(bundle, store, profile_dict, trust, timestamp)
        for row in bundle["formalizations"]:
            binding = FormalizationBinding.from_dict(row["binding"])
            for dimension in ("source-fidelity", "formal-fidelity"):
                decision = ReviewDecision.create(
                    binding=binding,
                    profile=profile,
                    dimension=dimension,
                    decision="APPROVE",
                    reviewer_id="ci-ephemeral-reviewer",
                    method="original-fixture-test-review-v1",
                )
                envelope = sign_record(
                    decision.to_dict(), keys["ci-ephemeral-reviewer"], "ci-ephemeral-reviewer"
                )
                envelopes.append(envelope)
                assessment = apply_fidelity(bundle, envelope, store, profile_dict, trust, timestamp)
        return assessment, envelopes

    authorize_source()
    initial, code = ci(manuscript, root / "initial", root / "store", **options)
    initial_sources = {manuscript.name: base64.b64encode(manuscript.read_bytes()).decode("ascii")}
    check(
        code == 0 and len(initial["execution_events"]) == 2,
        "Both independent branches require actual initial executions",
    )
    check(
        all(row["event"]["outcome"] == "VERIFIED" for row in initial["execution_events"]),
        "Initial independent branch execution failed",
    )
    branch_b = next(
        row for row in initial["formalizations"] if row["obligation"]["statement"].find("→") >= 0
    )
    check(
        "x = 2" in branch_b["obligation"]["statement"],
        "Source antecedent was not preserved in generated Lean",
    )
    store = PaperStore(root / "store")
    try:
        initial_before = reassess(initial, store, profile_dict, trust, timestamp)
        check(
            initial_before["counts"]["verified"] == 2 and initial_before["counts"]["accepted"] == 0,
            "Independent fixture bypassed fidelity",
        )
        initial_after, old_reviews = approve(initial, store)
        check(
            initial_after["counts"]["accepted"] == 2,
            "Independent fixture test reviews did not authorize exact subjects",
        )
        initial_events = deepcopy(initial["execution_events"])
        manuscript.write_text(
            BRANCH_MANUSCRIPT.replace(r"\offset}{1}", r"\offset}{2}"), encoding="utf-8"
        )
        authorize_source()
        revised, code = ci(manuscript, root / "revised", root / "store", **options)
        revised_sources = {
            manuscript.name: base64.b64encode(manuscript.read_bytes()).decode("ascii")
        }
        check(code == 0, "Revised independent fixture failed actual qualification")
        decisions = {row["label"]: row for row in revised["revision_plan"]["rows"]}
        check(
            decisions["branch-a"]["pure_execution"] == "EXECUTED",
            "Changed definition A was incorrectly reused",
        )
        check(
            decisions["branch-b"]["pure_execution"] == "REUSED",
            "Independent B pure computation was rerun",
        )
        check(
            decisions["branch-b"]["formal_execution"] == "HISTORICAL_REUSE",
            "Independent B formal fact was not reused",
        )
        check(len(revised["execution_events"]) == 1, "Revision forged or repeated B's execution")
        current_b = next(
            row
            for row in revised["formalizations"]
            if row["assertion_id"] == decisions["branch-b"]["assertion_id"]
        )
        check(
            current_b["binding"] != branch_b["binding"],
            "Source revision did not receive a new formal binding",
        )
        check(
            current_b["historical_execution"]["binding"] == branch_b["binding"],
            "Historical binding was rewritten",
        )
        revised_before = reassess(revised, store, profile_dict, trust, timestamp)
        check(
            revised_before["counts"]["verified"] == 2 and revised_before["counts"]["accepted"] == 0,
            "Historical proof reuse transplanted source acceptance",
        )
        stale_rejected = 0
        for envelope in old_reviews:
            try:
                apply_fidelity(revised, envelope, store, profile_dict, trust, timestamp)
            except ValueError:
                stale_rejected += 1
        check(stale_rejected == len(old_reviews), "A stale review survived source rebinding")
        revised_after, current_reviews = approve(revised, store)
        check(revised_after["counts"]["accepted"] == 2, "Current independent reviews failed")
        revoked = deepcopy(trust)
        revoked["keys"][0]["revoked"] = True
        revoked_view = reassess(revised, store, profile_dict, revoked, timestamp)
        check(
            revoked_view["counts"]["accepted"] == 0 and revoked_view["counts"]["verified"] == 0,
            "Revocation did not affect reused proof facts",
        )
        check(initial["execution_events"] == initial_events, "Revision rewrote historical events")
        store.rebuild()
        check(
            len(store.list_audit(initial["run_manifest"]["run_id"], "ReviewDecision")) == 4,
            "Historical reviews lost on rebuild",
        )
        manuscript.write_text(
            BRANCH_MANUSCRIPT.replace(r"\offset}{1}", r"\offset}{\unknown}"), encoding="utf-8"
        )
        authorize_source()
        unresolved, unresolved_code = ci(
            manuscript,
            root / "unresolved",
            root / "store",
            **options,
        )
        check(unresolved_code == 1, "Unknown macro must fail required full formal coverage")
        check(
            not unresolved["execution_events"],
            "Unknown A cannot trigger an inherited proof or rerun B",
        )
        unresolved_a = next(
            row for row in unresolved["revision_plan"]["rows"] if row["label"] == "branch-a"
        )
        check(
            not unresolved_a["reuse_eligible"]
            and unresolved_a["pure_execution"] == "EXECUTED"
            and any("UNRESOLVED" in reason for reason in unresolved_a["reasons"]),
            "Unresolved source context did not conservatively invalidate A",
        )
        return {
            "status": "PASS",
            "authentication": "EPHEMERAL_TEST_AUTHORITY_ONLY",
            "initial_before_review": initial_before["counts"],
            "initial_after_review": initial_after["counts"],
            "revised_before_review": revised_before["counts"],
            "revised_after_review": revised_after["counts"],
            "after_revocation": revoked_view["counts"],
            "stale_reviews_rejected": stale_rejected,
            "initial_execution_count": len(initial_events),
            "revised_execution_count": len(revised["execution_events"]),
            "initial_execution_events": initial_events,
            "revised_execution_events": revised["execution_events"],
            "revision_plan": revised["revision_plan"],
            "initial_ir": initial["document_ir"],
            "revised_ir": revised["document_ir"],
            "initial_input_manifest": initial["input_manifest"],
            "revised_input_manifest": revised["input_manifest"],
            "initial_sources": initial_sources,
            "revised_sources": revised_sources,
            "initial_formalizations": initial["formalizations"],
            "revised_formalizations": revised["formalizations"],
            "unresolved_ir": unresolved["document_ir"],
            "unresolved_input_manifest": unresolved["input_manifest"],
            "unresolved_sources": {
                manuscript.name: base64.b64encode(manuscript.read_bytes()).decode("ascii")
            },
            "unresolved_plan": unresolved["revision_plan"],
            "unresolved_formalizations": unresolved["formalizations"],
            "unresolved_execution_count": len(unresolved["execution_events"]),
            "unresolved_execution_events": unresolved["execution_events"],
            "unresolved_exit_code": unresolved_code,
            "reused_formalization": current_b,
            "initial_reviews": old_reviews,
            "current_reviews": current_reviews,
            "trust_store": trust,
            "evaluation_time": timestamp,
            "historical_events_unchanged": initial["execution_events"] == initial_events,
        }
    finally:
        store.close()


def worker(profile_path: Path, output: Path, corpus_script: Path, validator_sha: str) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    import proofmap
    from proofmap.attempts import FormalObligation
    from proofmap.evidence_adapter import resolve_execution
    from proofmap.evidence_records import FormalizationBinding, ReviewDecision, VerifierProfile
    from proofmap.integrity import load_json, write_json
    from proofmap.paper import ci, diff
    from proofmap.paper_evidence import apply_fidelity, reassess
    from proofmap.paper_store import PaperStore
    from proofmap.replay import replay_bound_execution
    from proofmap.trust import sign_record

    check(
        Path(proofmap.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()),
        "Validator must be the installed wheel",
    )
    profile_dict = load_json(profile_path)
    profile = VerifierProfile.from_dict(profile_dict)
    root = Path.cwd()
    manuscript = root / "unmapped.tex"
    manuscript.write_text(MANUSCRIPT, encoding="utf-8")
    store_root = root / "store"
    initial, code = ci(manuscript, root / "indexed", store_root)
    check(code == 0 and len(initial["assertions"]) == 1, "Automatic source extraction failed")
    check(not initial["assessment"]["closure"]["closed"], "Authorship accepted a claim")
    subject = initial["assertions"][0]["id"]
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    keys: dict[str, bytes] = {}
    trust: dict[str, Any] = {"schema_version": "2.0", "keys": []}
    for ident, roles in (
        ("ci-ephemeral-controller", ["verification-execution"]),
        ("ci-ephemeral-reviewer", ["source-fidelity-review", "formal-fidelity-review"]),
    ):
        key = Ed25519PrivateKey.generate()
        keys[ident] = key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        public = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        trust["keys"].append(
            {
                "id": ident,
                "public_key": base64.b64encode(public).decode("ascii"),
                "roles": roles,
                "subjects": [subject],
                "profiles": [profile.digest],
                "revoked": False,
                "not_before": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
                "not_after": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            }
        )
    options = {
        "execution_profile": profile_dict,
        "controller_key": keys["ci-ephemeral-controller"],
        "controller_id": "ci-ephemeral-controller",
        "trust_store": trust,
        "evaluation_time": timestamp,
        "require_formal": True,
    }
    verified, code = ci(manuscript, root / "verified", store_root, **options)
    check(code == 0, "Mandatory isolated Lean verification failed or unavailable")
    row = verified["formalizations"][0]
    binding = FormalizationBinding.from_dict(row["binding"])
    obligation = FormalObligation.from_dict(row["obligation"])
    event = verified["execution_events"][0]
    check(event["event"]["outcome"] == "VERIFIED", "No actual verified execution event")
    check(
        bool(row["resolution"]["closure"]["closed"]), "Authenticated evidence did not enter kernel"
    )
    store = PaperStore(store_root)
    try:
        before = reassess(verified, store, profile_dict, trust, timestamp)
        check(
            before["counts"]["verified"] == 1 and before["counts"]["accepted"] == 0,
            "Fidelity gate failed",
        )
        review_envelopes = []
        for dimension in ("source-fidelity", "formal-fidelity"):
            decision = ReviewDecision.create(
                binding=binding,
                profile=profile,
                dimension=dimension,
                decision="APPROVE",
                reviewer_id="ci-ephemeral-reviewer",
                method="known-fixture-review-v1",
            )
            envelope = sign_record(
                decision.to_dict(), keys["ci-ephemeral-reviewer"], "ci-ephemeral-reviewer"
            )
            review_envelopes.append(envelope)
            after = apply_fidelity(verified, envelope, store, profile_dict, trust, timestamp)
        check(after["counts"]["accepted"] == 1, "Exact reviewed assertion was not accepted")
        wrong_role = deepcopy(trust)
        wrong_role["keys"][0]["roles"] = ["receipt-content"]
        revoked = deepcopy(trust)
        revoked["keys"][0]["revoked"] = True
        tampered = deepcopy(event["envelope"])
        tampered["payload"] = base64.b64encode(b"{}").decode("ascii")
        rejections = {}
        for name, envelope, authority in (
            ("wrong-role", event["envelope"], wrong_role),
            ("revoked", event["envelope"], revoked),
            ("tampered", tampered, trust),
        ):
            result = resolve_execution(
                envelope, authority, binding, obligation, profile, evaluation_time=timestamp
            )
            check(not result["accepted"], "Tampering or authority mismatch was accepted: " + name)
            rejections[name] = result["reason"]
        check(
            reassess(verified, store, profile_dict, revoked, timestamp)["counts"]["accepted"] == 0,
            "Cached acceptance survived authority revocation",
        )
        try:
            replay_bound_execution(
                event["event"], binding.to_dict(), row["obligation"], b"by rfl", profile_dict
            )
        except ValueError as exc:
            rejections["replay-binding"] = str(exc)
        else:
            raise ValueError("Replay accepted changed candidate")
        replayed = replay_bound_execution(
            event["event"],
            binding.to_dict(),
            row["obligation"],
            row["candidate"].encode(),
            profile_dict,
            controller_id="ci-ephemeral-controller",
            private_key=keys["ci-ephemeral-controller"],
        )
        check(
            replayed["event"]["outcome"] == "VERIFIED"
            and replayed["event"]["parent_event"] == event["event"]["id"],
            "Fresh replay did not verify",
        )
        resumed, resume_code = ci(manuscript, root / "resumed", store_root, resume=True, **options)
        check(
            resume_code == 0 and bool(resumed["run_manifest"]["cache_provenance"]["reused_stages"]),
            "Same revision resume did not reuse completed stage",
        )
        check(
            resumed["assertions"] == verified["assertions"],
            "Resume duplicated or changed assertions",
        )
        manuscript.write_text(MANUSCRIPT.replace(r"\mathbb{Z}", r"\mathbb{R}"), encoding="utf-8")
        revised, _ = ci(manuscript, root / "revised", store_root)
        invalidated = diff(verified, revised)
        check(
            bool(invalidated["invalidated_assertions"]), "Changed domain did not invalidate subject"
        )
        try:
            apply_fidelity(revised, review_envelopes[0], store, profile_dict, trust, timestamp)
        except ValueError:
            rejections["stale-review"] = "REJECTED"
        else:
            raise ValueError("Old source review accepted on new revision")
        revised_assessment = reassess(revised, store, profile_dict, trust, timestamp)
        check(
            revised_assessment["counts"]["accepted"] == 0, "New revision retained stale acceptance"
        )
        store.rebuild()
        check(
            len(store.list_audit(verified["run_manifest"]["run_id"], "ReviewDecision")) == 2,
            "Audit history lost during rebuild",
        )
    finally:
        store.close()
    # Invoke the same installed, isolated trusted-validator/data-only script used by Paper CI.
    submission = root / "submission"
    (submission / "papers").mkdir(parents=True)
    (submission / "papers" / "new.tex").write_text(MANUSCRIPT, encoding="utf-8")
    (submission / "proofmap").mkdir()
    (submission / "proofmap" / "__init__.py").write_text(
        "raise RuntimeError('submission import executed')\n"
    )
    subprocess.run(["git", "init", "-q", str(submission)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(submission), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(submission),
            "-c",
            "user.name=CI fixture",
            "-c",
            "user.email=fixture@invalid.example",
            "commit",
            "-qm",
            "Ephemeral manuscript fixture",
        ],
        check=True,
        capture_output=True,
    )
    submission_sha = subprocess.run(
        ["git", "-C", str(submission), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    data_only = data_only_check(
        corpus_script,
        submission,
        root / "data-only",
        validator_sha,
        submission_sha,
    )
    alpha_revision = independent_revision_scenario(
        root / "independent-revision", profile_dict, keys, trust, timestamp
    )
    write_json(
        output / "outcomes.json",
        {
            "status": "PASS",
            "authentication": "EPHEMERAL_TEST_AUTHORITY_ONLY",
            "installed_package": str(Path(proofmap.__file__).resolve()),
            "validator_sha": validator_sha,
            "manuscript_sha": submission_sha,
            "profile": profile_dict,
            "binding": binding.to_dict(),
            "obligation": obligation.to_dict(),
            # Public ephemeral test authority permits independent validation of
            # these diagnostics; private controller/reviewer keys stay in memory.
            "trust_store": trust,
            "evaluation_time": timestamp,
            "before_review": before["counts"],
            "after_review": after["counts"],
            "after_revision": revised_assessment["counts"],
            "invalidated": len(invalidated["invalidated_assertions"]),
            "resume_reused": resumed["run_manifest"]["cache_provenance"]["reused_stages"],
            "rejections": rejections,
            "data_only": data_only,
            "environment": event["event"]["environment"],
            "execution": event,
            "replay": replayed["event"],
            "replay_envelope": replayed["envelope"],
            "alpha_revision": alpha_revision,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--corpus-script", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--validator-sha", help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        if args.worker:
            check(
                args.corpus_script is not None
                and isinstance(args.validator_sha, str)
                and bool(re.fullmatch(r"[a-f0-9]{40}", args.validator_sha)),
                "Worker requires trusted corpus script and immutable validator revision",
            )
            worker(args.profile.resolve(), output, args.corpus_script.resolve(), args.validator_sha)
            return 0
        check(
            args.wheel is not None and args.wheel.is_file(), "Exactly one built wheel is required"
        )
        check(args.profile.is_file(), "Prepared isolated verifier profile is required")
        validator_sha = validator_revision(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory(prefix="proofmap-installed-e2e-") as temporary:
            root = Path(temporary)
            venv.EnvBuilder(with_pip=True).create(root / "env")
            python = root / "env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            constraints = Path(__file__).resolve().parents[1] / "constraints-ci.txt"
            subprocess.run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "-c",
                    str(constraints),
                    str(args.wheel.resolve()) + "[paper,trust]",
                ],
                cwd=root,
                check=True,
                timeout=300,
            )
            driver = root / "driver.py"
            corpus = root / "paper_ci_corpus.py"
            shutil.copyfile(__file__, driver)
            shutil.copyfile(Path(__file__).with_name("paper_ci_corpus.py"), corpus)
            subprocess.run(
                [
                    str(python),
                    "-I",
                    str(driver),
                    "--worker",
                    "--profile",
                    str(args.profile.resolve()),
                    "--out",
                    str(output),
                    "--corpus-script",
                    str(corpus),
                    "--validator-sha",
                    validator_sha,
                ],
                cwd=root,
                check=True,
                timeout=1200,
            )
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # The outer CalledProcessError is only a summary; retain the child's
        # original diagnostic instead of replacing it with launcher metadata.
        failure_name = "failure.json" if args.worker else "launcher-failure.json"
        (output / failure_name).write_text(
            json.dumps({"status": "FAIL", "error": str(exc)[:4000], "type": type(exc).__name__}),
            encoding="utf-8",
        )
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
