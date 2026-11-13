"""Executable local research-campaign demonstration with separate evidence states."""

from __future__ import annotations

import base64
import json
import shutil
import sys
import tempfile
import time
import zipfile
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path
from typing import Any

from ..integrity import artifact_digest, canonical_bytes, digest, load_json, write_json
from ..paper_sources import source_validation_operation

OFFLINE = {"OP-01", "OP-06", "OP-08", "OP-09", "OP-10"}
ISOLATED = {"OP-02", "OP-03", "OP-04", "OP-05"}


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("RESEARCH_CONOPS: " + reason)


def installed_material(wheel: Path | None) -> dict[str, Any]:
    import proofmap

    package = Path(proofmap.__file__).resolve().parent
    result: dict[str, Any] = {
        "package_version": version("proof-map-boundary-analysis"),
        "installed": False,
        "wheel_sha256": None,
        "verified_files": 0,
    }
    if wheel is None:
        return result
    _require(
        "site-packages" in package.parts and Path(sys.prefix).resolve() in package.parents,
        "Installed wheel outside checkout required",
    )
    verified = 0
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith("proofmap/") and not name.endswith("/"):
                relative = Path(name).relative_to("proofmap")
                _require(".." not in relative.parts, "Wheel traversal")
                _require(
                    (package / relative).read_bytes() == archive.read(name),
                    "Installed material changed",
                )
                verified += 1
    _require(verified > 0, "Empty installed package")
    result.update(
        installed=True, wheel_sha256=artifact_digest(wheel.read_bytes()), verified_files=verified
    )
    return result


def _recorded_extraction(store: Any, campaign_id: str, fixture: Path, out: Path) -> dict[str, Any]:
    from ..extractor import make_request
    from ..paper_sources import acquire, parse
    from ..semantic_candidates import source_anchors
    from .models import operation_policy
    from .operations import tasks
    from .service import ingest, initialize

    campaign_id = initialize(
        store,
        "Recorded interpretation pilot",
        "Replay source-bound interpretation without model disclosure or dispatch",
        policy=operation_policy(
            allowed_kinds=["EXTRACT_CONFIGURED"],
            allow_model=True,
            model_max_requests=1,
            model_max_tokens=512,
            source_roots=[str(fixture.resolve().parent)],
        ),
    )["campaign_id"]

    manifest, raw = acquire(fixture)
    ir = parse(manifest, raw)
    anchors = source_anchors(ir)
    target = next(e for e in ir["elements"] if e.get("role") == "THEOREM")
    owned = [ident for ident, anchor in anchors.items() if anchor["element"] == target["id"]]
    proposition_anchor = next(
        ident for ident in owned if anchors[ident]["text"].lstrip().startswith("For every")
    )
    config = {
        "provider": "ollama",
        "endpoint": "http://127.0.0.1:1",
        "model": "RECORDED_TEST_DOUBLE_ONLY",
        "timeout_seconds": 1,
        "max_output_tokens": 512,
        "stage": "decomposition",
    }
    candidate = {
        "element": target["id"],
        "quantifiers": [proposition_anchor],
        "hypotheses": [],
        "conclusion": proposition_anchor,
        "references": [],
        "symbol_bindings": [],
    }
    response = {"classifications": [], "dependencies": [], "candidates": [candidate]}
    raw_response = json.dumps(
        {"done": True, "model": config["model"], "message": {"content": json.dumps(response)}}
    )
    event = {
        "request_sha256": artifact_digest(canonical_bytes(make_request(ir, config))),
        "config_digest": digest("extractor-config.v1", config),
        "raw_response": raw_response,
        "response_sha256": artifact_digest(raw_response.encode()),
    }
    replay = {
        "revision": ir["revision"],
        "config_digest": event["config_digest"],
        "events": [event],
    }
    result = ingest(
        store,
        campaign_id,
        fixture,
        extractor="replay",
        config={"extractor": config},
        replay=replay,
        paper_id="identities.tex",
    )
    _require(result["manuscripts"][0]["exit_code"] == 0, "Recorded decomposition rejected")
    run = store.inspect(result["manuscripts"][0]["run_id"])["bundle"]
    _require(
        run["extraction_events"] and all(e["replayed"] for e in run["extraction_events"]),
        "Exact replay provenance missing",
    )
    altered = deepcopy(replay)
    altered["events"][0]["request_sha256"] = "0" * 64
    rejected = ingest(
        store,
        campaign_id,
        fixture,
        extractor="replay",
        config={"extractor": config},
        replay=altered,
        paper_id="identities.tex",
    )
    _require(rejected["manuscripts"][0]["exit_code"] != 0, "Altered replay accepted")
    # Retain two incompatible interpretations of the same source as ambiguity;
    # neither interpretation can authorize an operation or fidelity approval.
    conflicting = deepcopy(replay)
    other = {**candidate, "conclusion": owned[1]}
    reply = {"classifications": [], "dependencies": [], "candidates": [candidate, other]}
    conflicting["events"][0]["raw_response"] = json.dumps(
        {"done": True, "model": config["model"], "message": {"content": json.dumps(reply)}}
    )
    conflicting["events"][0]["response_sha256"] = artifact_digest(
        conflicting["events"][0]["raw_response"].encode()
    )
    conflict_intake = ingest(
        store,
        campaign_id,
        fixture,
        extractor="replay",
        config={"extractor": config},
        replay=conflicting,
        paper_id="identities.tex",
    )
    conflict_run = store.inspect(conflict_intake["manuscripts"][0]["run_id"])["bundle"]
    _require(
        conflict_intake["manuscripts"][0]["exit_code"] == 0
        and len(conflict_run["semantic_overlay"]["candidates"]) == 2
        and all(
            c["status"] == "CONFLICT_REVIEW_REQUIRED"
            for c in conflict_run["semantic_overlay"]["candidates"]
        ),
        "Source ambiguity discarded",
    )
    malformed = deepcopy(replay)
    malformed["events"][0]["raw_response"] = '{"done":'
    malformed["events"][0]["response_sha256"] = artifact_digest(
        malformed["events"][0]["raw_response"].encode()
    )
    malformed_intake = ingest(
        store,
        campaign_id,
        fixture,
        extractor="replay",
        config={"extractor": config},
        replay=malformed,
        paper_id="identities.tex",
    )
    _require(malformed_intake["manuscripts"][0]["exit_code"] != 0, "Malformed model reply accepted")
    _require(not tasks(store, campaign_id), "Model interpretation authorized dispatch")
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class InterruptedProtocol(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b'{"done":')
            self.wfile.flush()
            self.close_connection = True

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), InterruptedProtocol)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    interrupted_config = {
        **config,
        "endpoint": f"http://127.0.0.1:{server.server_port}",
        "max_requests": 1,
        "max_total_output_tokens": 512,
        "max_total_seconds": 1,
    }
    try:
        interrupted = ingest(
            store,
            campaign_id,
            fixture,
            extractor="configured",
            config={"extractor": interrupted_config},
            paper_id="identities.tex",
        )
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    _require(
        interrupted["manuscripts"][0]["exit_code"] != 0,
        "Interrupted protocol became successful extraction",
    )
    write_json(out / "recorded-replay.json", replay)
    return {
        "run_id": run["run_manifest"]["run_id"],
        "events": run["extraction_events"],
        "overlay": run["semantic_overlay"],
        "altered_replay_exit": rejected["manuscripts"][0]["exit_code"],
        "conflicting_candidates": conflict_run["semantic_overlay"]["candidates"],
        "malformed_reply_exit": malformed_intake["manuscripts"][0]["exit_code"],
        "interrupted_protocol_exit": interrupted["manuscripts"][0]["exit_code"],
        "interruption_provider": "LOCAL_HTTP_PROTOCOL_TEST_DOUBLE_ONLY",
        "model_suggestions_dispatched": False,
        "explicit_interruption_tasks": tasks(store, campaign_id),
        "model_quality": "NOT_MEASURED",
        "live_model": False,
    }


@source_validation_operation
def run_research_conops(
    out: Path,
    *,
    profile: str = "offline",
    execution_profile: dict[str, Any] | None = None,
    candidate_identity: dict[str, Any] | None = None,
    wheel: Path | None = None,
    fixtures: Path | None = None,
) -> dict[str, Any]:
    from .models import operation_policy
    from .operations import authorize_plan, plan_campaign, run_campaign, tasks
    from .portable import audit_campaign, export_campaign, import_campaign
    from .reports import candidate_relation, write_campaign_report
    from .service import add_goal, ingest, initialize
    from .store import CampaignStore

    if profile not in {"offline", "isolated"}:
        raise ValueError("RESEARCH_CONOPS_PROFILE")
    if fixtures is None:
        fixtures = Path(__file__).resolve().parents[1] / "resources/campaign_operational"
    expected = load_json(fixtures / "expected.json")
    out.mkdir(parents=True, exist_ok=True)
    copied = out / "manuscripts"
    shutil.copytree(fixtures, copied, dirs_exist_ok=True)
    started = time.monotonic()
    store = CampaignStore(out / "store")
    try:
        campaign = initialize(
            store,
            "Polynomial research pilot",
            "Audit selected claims and retain unsupported research boundaries",
        )
        campaign_id = campaign["campaign_id"]
        intake = ingest(store, campaign_id, copied)
        _require(len(intake["manuscripts"]) == 3, "Three-manuscript intake")
        runs = {row["paper_id"]: row["run_id"] for row in intake["manuscripts"]}
        goals = []
        for name, labels in expected["papers"].items():
            bundle = store.inspect(runs[name])["bundle"]
            _require(
                sum(r["status"] == "SUPPORTED" for r in bundle["formalizations"])
                == labels["supported"],
                "Independent supported-profile label",
            )
            for label in labels["labels"]:
                goals.append(add_goal(store, campaign_id, run_id=runs[name], label=label))
        plan = plan_campaign(store, campaign_id, profile=execution_profile)
        _require(
            plan["authority"] == "PLANNING_ONLY" and not tasks(store, campaign_id),
            "Planning dispatched work",
        )
        policy = operation_policy(
            allowed_kinds=["VERIFY_FORMAL_SUBJECT", "AUTHENTICATE_EVIDENCE"],
            profile_digest=plan["profile_digest"],
            max_tasks=20,
            max_wall_seconds=600,
        )
        authorization = authorize_plan(store, campaign_id, plan, policy, "explicit-test-operator")
        duplicate = authorize_plan(store, campaign_id, plan, policy, "explicit-test-operator")
        _require(
            len(tasks(store, campaign_id)) == len(authorization["tasks"]),
            "Duplicate enqueue changed work inventory",
        )
        relation = candidate_relation(
            store,
            campaign_id,
            goals[0]["target"],
            goals[3]["target"],
            relation="POSSIBLE_DUPLICATE",
            reason="Similar wording uses integer and real domains; no theorem equivalence inferred",
            ambiguity=["DOMAIN_MISMATCH"],
        )
        _require(relation["proof_closure"] is False, "Candidate relation grants closure")
        outcome = run_campaign(store, campaign_id, max_tasks=20, max_wall_seconds=600)
        _require(
            not any(
                r["state"] == "SUCCEEDED"
                for r in outcome["outcomes"]
                if store.get_record(r["task_id"])["action"]["paper_action"]["kind"]
                == "VERIFY_FORMAL_SUBJECT"
            ),
            "Unavailable work claimed verification",
        )
        recorded = _recorded_extraction(store, campaign_id, copied / "identities.tex", out)
        report = write_campaign_report(store, campaign_id, out / "report")
        archive = out / "dossier.zip"
        export_manifest = export_campaign(store, campaign_id, archive, include_source=True)
        tampered = out / "tampered.zip"
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(tampered, "w") as corrupt:
            victim = next(name for name in source.namelist() if name.startswith("objects/"))
            for name in source.namelist():
                raw = source.read(name)
                corrupt.writestr(name, raw + b"tampered" if name == victim else raw)
        clean = CampaignStore(out / "restored-store")
        try:
            rejected = False
            try:
                import_campaign(tampered, clean)
            except (ValueError, OSError, KeyError):
                rejected = True
            _require(rejected, "Corrupt dossier accepted")
            restored = import_campaign(archive, clean)
            audit = audit_campaign(clean, campaign_id)
            _require(
                restored["authority_imported"] is False
                and restored["tasks_require_fresh_authorization"] is True
                and audit["integrity"] == "PASS",
                "Restore authority/authorization boundary",
            )
        finally:
            clean.close()
        checks = {
            ident: {"status": "UNEXECUTED", "reason": "Required execution profile has not run"}
            for ident in [f"OP-{i:02d}" for i in range(1, 11)]
        }
        for ident in OFFLINE:
            checks[ident] = {"status": "PASS", "reason": "Observed normal campaign API execution"}
        checks["OP-07"] = {
            "status": "UNEXECUTED",
            "reason": "Chromium navigation/security is a separate mandatory browser profile",
        }
        result = {
            "schema_version": "1.0",
            "profile": profile,
            "candidate_identity": candidate_identity,
            "material": installed_material(wheel),
            "checks": checks,
            "campaign_id": campaign_id,
            "intake": intake,
            "goals": goals,
            "plan": plan,
            "authorization": authorization,
            "duplicate_authorization": duplicate,
            "offline_run": outcome,
            "relation": relation,
            "recorded_extraction": recorded,
            "report": report,
            "export": export_manifest,
            "restore": restored,
            "audit": audit,
            "corruption_rejected": rejected,
            "runtime_seconds": round(time.monotonic() - started, 6),
            "live_model_quality": "NOT_MEASURED",
            "external_user_pilot": "NOT_PERFORMED",
            "production_authority": "NOT_CONFIGURED",
            "publication": "NOT_REQUESTED",
            "formal": "UNAVAILABLE",
            "fidelity": "PENDING_EXPLICIT_HUMAN_DECISION",
            "accepted_under_policy": 0,
            "scholarly_novelty": "NOT_ASSESSED",
            "validation": "PASS" if profile == "offline" else "UNEXECUTED",
        }
        if profile == "isolated":
            _require(execution_profile is not None, "Prepared isolated profile required")
            assert execution_profile is not None
            with tempfile.TemporaryDirectory(
                prefix="proofmap-campaign-test-keys-"
            ) as secret_directory:
                result["isolated"] = _isolated_campaign(
                    store, campaign_id, runs, execution_profile, out, Path(secret_directory)
                )
            for ident in ISOLATED:
                checks[ident] = result["isolated"]["checks"][ident]
            result["formal"] = "OBSERVED_ISOLATED_EXECUTION"
            result["validation"] = "PASS"
        result["offline_runtime_seconds"] = result["runtime_seconds"]
        result["runtime_seconds"] = round(time.monotonic() - started, 6)
        write_json(out / "campaign-outcomes.json", result)
        return result
    finally:
        store.close()


@source_validation_operation
def _isolated_campaign(
    store: Any,
    campaign_id: str,
    runs: dict[str, str],
    profile: dict[str, Any],
    out: Path,
    secret_directory: Path,
) -> dict[str, Any]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    from ..evidence_records import VerifierProfile
    from ..paper_evidence import preflight
    from .models import operation_policy
    from .operations import (
        apply_decision,
        assess_campaign,
        authorize_plan,
        plan_campaign,
        request_stage,
        review_decision,
        review_packets,
        run_campaign,
        tasks,
    )
    from .portable import audit_campaign, export_campaign, import_campaign
    from .reports import write_campaign_report
    from .revisions import revision_impact
    from .service import ingest
    from .store import CampaignStore

    _require(
        preflight(profile)["execution"] == "READY",
        "Isolated runtime/image unavailable; host fallback forbidden",
    )
    checked = VerifierProfile.from_dict(profile)
    # Supply the prepared profile to the same campaign which retained missing
    # infrastructure outcomes, then explicitly reauthorize the changed policy.
    goals = []
    for paper, label in [
        ("identities.tex", "shift-square"),
        ("independent.tex", "independent-identity"),
        ("independent.tex", "deliberately-invalid"),
    ]:
        bundle = store.inspect(runs[paper])["bundle"]
        assertion = next(
            e["id"] for e in bundle["document_ir"]["elements"] if label in e.get("labels", [])
        )
        goals.append(
            next(
                g
                for g in store.current_snapshot(campaign_id)["goals"]
                if g.get("target", {}).get("run_id") == runs[paper]
                and g["target"]["assertion_id"] == assertion
            )
        )
    subjects = [g["target"]["assertion_id"] for g in goals]
    source_bundles = {}
    for name, run_id in runs.items():
        stored = store.inspect(run_id)
        source_bundles[name] = {
            "bundle": stored["bundle"],
            "artifacts": {
                name: base64.b64encode(store.get(sha)).decode()
                for name, sha in stored["artifacts"].items()
            },
        }
    private: dict[str, bytes] = {}
    trust: dict[str, Any] = {"schema_version": "2.0", "keys": []}
    for name, role in [
        ("test-controller", "verification-execution"),
        ("test-source-reviewer", "source-fidelity-review"),
        ("test-formal-reviewer", "formal-fidelity-review"),
    ]:
        key = Ed25519PrivateKey.generate()
        private[name] = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        trust["keys"].append(
            {
                "id": name,
                "public_key": base64.b64encode(
                    key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
                ).decode(),
                "roles": [role],
                "subjects": subjects,
                "profiles": [checked.digest],
                "revoked": False,
                "not_before": "2026-01-01T00:00:00Z",
                "not_after": "2027-01-01T00:00:00Z",
            }
        )
    timestamp = "2026-10-02T18:00:00Z"
    controller_key = secret_directory / "controller.key"
    controller_key.write_bytes(private["test-controller"])
    controller = {
        "profile": profile,
        "private_key_path": str(controller_key.resolve()),
        "controller_id": "test-controller",
        "trust_store": trust,
        "evaluation_time": timestamp,
    }
    plan = plan_campaign(
        store, campaign_id, profile=profile, trust_store=trust, evaluation_time=timestamp
    )
    policy = operation_policy(
        allowed_kinds=["VERIFY_FORMAL_SUBJECT", "AUTHENTICATE_EVIDENCE", "REFRESH_REPORT"],
        profile_digest=checked.digest,
        max_tasks=20,
        max_wall_seconds=600,
    )
    authorization = authorize_plan(store, campaign_id, plan, policy, "explicit-test-operator")
    executed = run_campaign(
        store, campaign_id, controller_config=controller, max_tasks=20, max_wall_seconds=600
    )
    before = assess_campaign(store, campaign_id, profile, trust, timestamp)
    _require(
        before["counts"]["verified"] == 2 and before["counts"]["accepted"] == 0,
        "Actual isolated evidence before fidelity",
    )
    events = [r for run_id in runs.values() for r in store.list_audit(run_id, "ExecutionEvent")]
    _require(
        sum(r["record"]["outcome"] == "VERIFIED" for r in events) == 2
        and any(r["record"]["outcome"] == "COMPILER_REJECTED" for r in events),
        "Real valid and invalid source execution",
    )
    packets = review_packets(store, campaign_id, out / "review-packets", profile)
    _require(
        bool(packets) and all(p["decision"] == "PENDING_HUMAN_REVIEW" for p in packets),
        "Review handoff missing",
    )
    reviewed = goals[0]["target"]
    decisions = []
    for dimension, reviewer in [
        ("source-fidelity", "test-source-reviewer"),
        ("formal-fidelity", "test-formal-reviewer"),
    ]:
        envelope = review_decision(
            store,
            campaign_id,
            reviewed["run_id"],
            reviewed["assertion_id"],
            profile,
            dimension,
            "APPROVE",
            reviewer,
            "Explicit ephemeral test decision after inspection",
            private[reviewer],
        )
        decisions.append(envelope)
        apply_decision(store, campaign_id, reviewed["run_id"], envelope, profile, trust, timestamp)
    approved = assess_campaign(store, campaign_id, profile, trust, timestamp)
    _require(approved["counts"]["accepted"] == 1, "Exactly reviewed target accepted")
    authenticated_report = write_campaign_report(
        store,
        campaign_id,
        out / "authenticated-report",
        execution_profile=profile,
        trust_store=trust,
        evaluation_time=timestamp,
    )
    authenticated_archive = out / "authenticated-dossier.zip"
    authenticated_export = export_campaign(
        store, campaign_id, authenticated_archive, include_source=True
    )
    destination = CampaignStore(out / "authenticated-restored-store")
    try:
        authenticated_restore = import_campaign(authenticated_archive, destination)
        imported_task_states = [t["state"] for t in tasks(destination, campaign_id)]
        _require(
            authenticated_restore["authority_imported"] is False
            and authenticated_restore["tasks_require_fresh_authorization"] is True
            and not any(
                state in {"AUTHORIZED", "QUEUED", "RUNNING"} for state in imported_task_states
            ),
            "Authenticated restore resumed authority or dispatch",
        )
        restored_without_authority = assess_campaign(
            destination, campaign_id, profile, {"schema_version": "2.0", "keys": []}, timestamp
        )
        _require(
            restored_without_authority["counts"]["verified"] == 0
            and restored_without_authority["counts"]["accepted"] == 0,
            "Historical archive supplied authority",
        )
        restored_with_authority = assess_campaign(
            destination, campaign_id, profile, trust, timestamp
        )
        _require(
            restored_with_authority["counts"]["verified"] == 2
            and restored_with_authority["counts"]["accepted"] == 1,
            "Clean restore failed fresh external authentication",
        )
        authenticated_audit = audit_campaign(destination, campaign_id)
        _require(authenticated_audit["integrity"] == "PASS", "Authenticated archive integrity")
    finally:
        destination.close()
    negatives = {}
    for name, authority in [
        ("revoked", deepcopy(trust)),
        ("expired", deepcopy(trust)),
        ("wrong-role", deepcopy(trust)),
    ]:
        row = next(k for k in authority["keys"] if k["id"] == "test-source-reviewer")
        if name == "revoked":
            row["revoked"] = True
        elif name == "expired":
            row["not_after"] = "2026-02-01T00:00:00Z"
        else:
            row["roles"] = ["receipt-content"]
        assessment = assess_campaign(store, campaign_id, profile, authority, timestamp)
        _require(assessment["counts"]["accepted"] == 0, "Invalid external reviewer authority")
        negatives[name] = assessment
    altered = deepcopy(decisions[0])
    altered["payload"] = base64.b64encode(b"{}").decode()
    rejected_tamper = False
    try:
        apply_decision(store, campaign_id, reviewed["run_id"], altered, profile, trust, timestamp)
    except (ValueError, KeyError, TypeError):
        rejected_tamper = True
    _require(rejected_tamper, "Altered review accepted")
    changed_target = deepcopy(decisions[0])
    altered_record = json.loads(base64.b64decode(changed_target["payload"]))
    altered_record["assertion_id"] = goals[1]["target"]["assertion_id"]
    changed_target["payload"] = base64.b64encode(canonical_bytes(altered_record)).decode()
    altered_target_rejected = False
    try:
        apply_decision(
            store, campaign_id, reviewed["run_id"], changed_target, profile, trust, timestamp
        )
    except (ValueError, KeyError, TypeError):
        altered_target_rejected = True
    _require(altered_target_rejected, "Changed review target accepted")
    rejection = review_decision(
        store,
        campaign_id,
        reviewed["run_id"],
        reviewed["assertion_id"],
        profile,
        "source-fidelity",
        "REJECT",
        "test-source-reviewer",
        "Explicit rejection conflicts with earlier approval",
        private["test-source-reviewer"],
    )
    conflict_assessment = apply_decision(
        store, campaign_id, reviewed["run_id"], rejection, profile, trust, timestamp
    )
    _require(
        conflict_assessment["counts"]["accepted"] == 0,
        "Conflicting signed rejection did not block acceptance",
    )
    # Queue current work before a used static-macro change. The independent
    # paper remains exactly selected and must retain eligible evidence.
    affected = request_stage(
        store,
        campaign_id,
        "REFRESH_REPORT",
        {"run_id": runs["identities.tex"], "assertion_id": reviewed["assertion_id"]},
        policy,
        "explicit-test-operator",
    )
    independent = request_stage(
        store,
        campaign_id,
        "REFRESH_REPORT",
        {"run_id": runs["independent.tex"], "assertion_id": goals[1]["target"]["assertion_id"]},
        policy,
        "explicit-test-operator",
    )
    old_snapshot = store.current_snapshot(campaign_id)["id"]
    revised = out / "revised-identities.tex"
    original = (out / "manuscripts/identities.tex").read_text(encoding="utf-8")
    revised.write_text(original.replace("\\offset}{2}", "\\offset}{5}"), encoding="utf-8")
    _require(
        revised.read_text(encoding="utf-8") != original, "Used definition revision was unchanged"
    )
    revision_intake = ingest(store, campaign_id, revised, paper_id="identities.tex")
    impact = revision_impact(
        store, campaign_id, old_snapshot, store.current_snapshot(campaign_id)["id"]
    )
    _require(
        impact["acceptance_carried"] is False and impact["required_new_reviews"],
        "Revision carried acceptance or omitted new review",
    )
    _require(
        any(
            p["paper_id"] == "independent.tex" and p["membership"] == "UNCHANGED"
            for p in impact["papers"]
        ),
        "Independent membership invalidated",
    )
    revised_assessment = assess_campaign(store, campaign_id, profile, trust, timestamp)
    _require(
        revised_assessment["counts"]["accepted"] == 0
        and revised_assessment["counts"]["verified"] == 1,
        "Source revision inherited acceptance or lost independent evidence",
    )
    projected = {t["id"]: t for t in tasks(store, campaign_id)}
    _require(
        projected[affected["task_id"]]["state"] == "STALE"
        and projected[independent["task_id"]]["state"] == "QUEUED",
        "Revision did not stale only affected queued work",
    )
    independent_events_before = store.list_audit(runs["independent.tex"], "ExecutionEvent")
    resumed = run_campaign(
        store, campaign_id, controller_config=controller, max_tasks=20, max_wall_seconds=600
    )
    projected = {t["id"]: t for t in tasks(store, campaign_id)}
    _require(
        projected[independent["task_id"]]["state"] == "SUCCEEDED"
        and store.list_audit(runs["independent.tex"], "ExecutionEvent")
        == independent_events_before,
        "Independent evidence/work was duplicated or not reused",
    )
    queue_observations = _queue_failures(store, runs["independent.tex"], profile, out)
    checks = {
        ident: {
            "status": "PASS",
            "reason": "Actual isolated campaign, explicit ephemeral fidelity decisions, revision and queue recovery observed",
        }
        for ident in ISOLATED
    }
    return {
        "campaign_id": campaign_id,
        "resumed_missing_infrastructure_campaign": True,
        "authentication": "EPHEMERAL_TEST_AUTHORITY_ONLY",
        "checks": checks,
        "profile": profile,
        "trust_store": trust,
        "evaluation_time": timestamp,
        "source_bundles": source_bundles,
        "goals": goals,
        "plan": plan,
        "authorization": authorization,
        "execution": executed,
        "events": events,
        "before_review": before,
        "review_packets": packets,
        "review_decisions": decisions,
        "after_review": approved,
        "authenticated_report": authenticated_report,
        "authenticated_export": authenticated_export,
        "authenticated_restore": authenticated_restore,
        "authenticated_restore_task_states": imported_task_states,
        "restored_without_authority": restored_without_authority,
        "restored_with_authority": restored_with_authority,
        "authenticated_restore_audit": authenticated_audit,
        "invalid_authority": negatives,
        "tampered_review_rejected": rejected_tamper,
        "altered_target_rejected": altered_target_rejected,
        "signed_rejection": rejection,
        "conflicting_review_assessment": conflict_assessment,
        "revision_intake": revision_intake,
        "revision_impact": impact,
        "after_revision": revised_assessment,
        "revision_tasks": {
            "affected": projected[affected["task_id"]],
            "independent": projected[independent["task_id"]],
        },
        "independent_evidence_reused": True,
        "revision_resumed": resumed,
        "queue": queue_observations,
        "tasks": tasks(store, campaign_id),
    }


def _queue_failures(store: Any, run_id: str, profile: dict[str, Any], out: Path) -> dict[str, Any]:
    import subprocess
    from datetime import datetime, timedelta, timezone

    from ..runner import Limits, run
    from . import queue
    from .models import operation_policy
    from .operations import request_stage
    from .service import add_goal, initialize, select_run

    campaign_id = initialize(
        store, "Queue recovery observation", "Exercise bounded delivery and fenced publication"
    )["campaign_id"]
    select_run(store, campaign_id, run_id)
    add_goal(store, campaign_id, run_id=run_id, label="independent-identity")
    policy = operation_policy(
        allowed_kinds=["REFRESH_REPORT"],
        profile_digest=profile["id"],
        max_tasks=10,
        max_wall_seconds=600,
        lease_seconds=1,
    )
    goal = next(g for g in store.current_snapshot(campaign_id)["goals"] if g.get("target"))
    request_stage(
        store,
        campaign_id,
        "REFRESH_REPORT",
        {"run_id": run_id, "assertion_id": goal["target"]["assertion_id"]},
        policy,
        "test-operator",
    )
    eligible = {t["task_id"] for t in queue.tasks(store, campaign_id) if t["state"] == "QUEUED"}
    _require(bool(eligible), "No queue task for crash observation")
    # A controller subprocess exits abruptly after leasing real persistent work.
    code = "import json,os,sys; from pathlib import Path; from proofmap.campaign.store import CampaignStore; from proofmap.campaign import queue; s=CampaignStore(Path(sys.argv[1])); x=queue.claim(s,sys.argv[2],owner='crashed-controller',lease_seconds=1,max_attempts=3,reserve_seconds=1,max_tasks=10,max_wall_seconds=600,ready=set(json.loads(sys.argv[3])),now='2026-10-02T18:00:00Z'); print(json.dumps(x),flush=True); os._exit(17)"
    crashed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            code,
            str(store.root.resolve()),
            campaign_id,
            json.dumps(sorted(eligible)),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    _require(crashed.returncode == 17, "Controller crash was not observed")
    lease = json.loads(crashed.stdout)
    recovered = queue.recover(
        store, campaign_id, actor="recovery-observer", now="2026-10-02T18:00:10Z"
    )
    _require(lease["task_id"] in recovered, "Expired controller lease not recovered")
    fenced = False
    try:
        queue.transition(
            store,
            lease["task_id"],
            "SUCCEEDED",
            actor="late-worker",
            reason="STALE_RESULT",
            token=lease["lease_token"],
            generation=lease["generation"],
        )
    except ValueError:
        fenced = True
    _require(fenced, "Late worker published after recovery")
    race_code = "import json,sys; from pathlib import Path; from proofmap.campaign.store import CampaignStore; from proofmap.campaign import queue; s=CampaignStore(Path(sys.argv[1])); sys.stdin.readline(); x=queue.claim(s,sys.argv[2],owner=sys.argv[4],lease_seconds=60,max_attempts=3,reserve_seconds=1,max_tasks=10,max_wall_seconds=600,ready=set(json.loads(sys.argv[3]))); print(json.dumps(x),flush=True); s.close()"
    workers = [
        subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-c",
                race_code,
                str(store.root.resolve()),
                campaign_id,
                json.dumps(sorted(eligible)),
                name,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for name in ("worker-one", "worker-two")
    ]
    for worker in workers:
        assert worker.stdin is not None
        worker.stdin.write("claim\n")
        worker.stdin.flush()
    winners: list[Any] = []
    race_exits = []
    for worker in workers:
        output, errors = worker.communicate(timeout=20)
        _require(worker.returncode == 0, "Competing process claim failed: " + errors)
        race_exits.append(worker.returncode)
        winners.append(json.loads(output))
    _require(
        len(winners) == 2 and sum(w is not None for w in winners) == 1, "Two-worker lease race"
    )
    winner = next(w for w in winners if w is not None)
    later = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat().replace("+00:00", "Z")
    recovered_race = queue.recover(store, campaign_id, actor="budget-observer", now=later)
    _require(
        winner["task_id"] in recovered_race
        and any(
            t["task_id"] == winner["task_id"] and t["state"] == "QUEUED"
            for t in queue.tasks(store, campaign_id)
        ),
        "No queued task when checking budget exhaustion",
    )
    no_budget = queue.claim(
        store,
        campaign_id,
        owner="budget-observer",
        lease_seconds=1,
        max_attempts=3,
        reserve_seconds=1,
        max_tasks=1,
        max_wall_seconds=600,
        ready=eligible,
    )
    _require(no_budget is None, "Budget exhaustion dispatched work")
    queue.cancel_task(store, winner["task_id"], actor="explicit-test-operator")
    source = out / "cancelled-container-source"
    source.mkdir(exist_ok=True)
    clock = time.monotonic()
    cancelled = run(
        profile["image"],
        source,
        ("/usr/local/bin/python", "-I", "-c", "import time; time.sleep(30)"),
        Limits(seconds=30),
        cancelled=lambda: time.monotonic() - clock >= 1,
    )
    _require(
        cancelled.execution_status == "CANCELLED" and cancelled.returncode is not None,
        "Actual container cancellation did not run",
    )
    oversized = run(
        profile["image"],
        source,
        ("/usr/local/bin/python", "-I", "-c", "print('x'*200000)"),
        Limits(seconds=10, output_bytes=1024),
    )
    _require(
        oversized.execution_status == "ERROR" and len(oversized.stdout.encode()) <= 1024,
        "Actual container output bound",
    )
    return {
        "controller_crash_exit": crashed.returncode,
        "lease": lease,
        "recovered": recovered,
        "late_result_fenced": fenced,
        "race_winners": sum(w is not None for w in winners),
        "race_process_exits": race_exits,
        "budget_queued_task": winner["task_id"],
        "budget_dispatch": no_budget,
        "cancelled_container": {
            "execution_status": cancelled.execution_status,
            "returncode": cancelled.returncode,
            "duration_seconds": cancelled.duration_seconds,
            "image": cancelled.image,
        },
        "output_limit": {
            "execution_status": oversized.execution_status,
            "retained_output_bytes": len(oversized.stdout.encode()),
            "image": oversized.image,
        },
    }


@source_validation_operation
def validate_outcomes(
    value: dict[str, Any], *, require_installed: bool = False, required_profile: str | None = None
) -> None:
    from .models import validate_record

    _require(
        value.get("schema_version") == "1.0" and value.get("profile") in {"offline", "isolated"},
        "Outcome profile",
    )
    if required_profile is not None:
        _require(value["profile"] == required_profile, "Wrong producer profile")
    material = value["material"]
    if require_installed:
        _require(
            material["installed"] is True
            and material["verified_files"] > 0
            and isinstance(material["wheel_sha256"], str)
            and len(material["wheel_sha256"]) == 64,
            "Installed material missing",
        )
        _require(
            isinstance(value.get("candidate_identity"), dict)
            and material["package_version"] == value["candidate_identity"].get("package_version"),
            "Installed distribution version differs from qualifying candidate",
        )
    required = OFFLINE | ISOLATED if value["profile"] == "isolated" else OFFLINE
    _require(
        set(value["checks"]) == {f"OP-{i:02d}" for i in range(1, 11)}, "Outcome scenario inventory"
    )
    _require(
        all(value["checks"][ident]["status"] == "PASS" for ident in required),
        "Mandatory scenario not executed",
    )
    for record in [*value["goals"], value["plan"], value["relation"]]:
        validate_record(record)
    _require(
        len(value["intake"]["manuscripts"]) == 3 and len(value["goals"]) == 5,
        "Source/goal inventory",
    )
    _require(
        value["plan"]["authority"] == "PLANNING_ONLY"
        and value["relation"]["proof_closure"] is False,
        "Planning/relation authority",
    )
    _require(
        value["accepted_under_policy"] == 0 and value["scholarly_novelty"] == "NOT_ASSESSED",
        "Historical snapshot scientific boundary",
    )
    _require(
        value["corruption_rejected"] is True
        and value["restore"]["authority_imported"] is False
        and value["restore"]["tasks_require_fresh_authorization"] is True
        and value["audit"]["integrity"] == "PASS",
        "Restore boundary",
    )
    _require(
        value["recorded_extraction"]["live_model"] is False
        and value["recorded_extraction"]["altered_replay_exit"] != 0
        and value["recorded_extraction"]["events"]
        and value["recorded_extraction"]["malformed_reply_exit"] != 0
        and value["recorded_extraction"]["interrupted_protocol_exit"] != 0
        and value["recorded_extraction"]["interruption_provider"]
        == "LOCAL_HTTP_PROTOCOL_TEST_DOUBLE_ONLY"
        and value["recorded_extraction"]["model_suggestions_dispatched"] is False
        and len(value["recorded_extraction"]["conflicting_candidates"]) == 2
        and all(
            c["status"] == "CONFLICT_REVIEW_REQUIRED"
            for c in value["recorded_extraction"]["conflicting_candidates"]
        ),
        "Replay provenance",
    )
    if value["profile"] == "isolated":
        _require("isolated" in value, "Actual isolated diagnostics missing")
        _require(
            value["isolated"]["campaign_id"] == value["campaign_id"]
            and value["isolated"]["resumed_missing_infrastructure_campaign"],
            "Missing infrastructure campaign not resumed",
        )
        validate_isolated_outcomes(value["isolated"])


@source_validation_operation
def validate_isolated_outcomes(value: dict[str, Any]) -> None:
    """Recheck original subjects, execution authentication and explicit fidelity.

    A trusted producer's actual runtime observation is required separately; a
    claimed scenario PASS alone never supplies the source/evidence chain.
    """
    from ..attempts import FormalObligation
    from ..evidence_adapter import assess_binding, resolve_execution
    from ..evidence_records import (
        ExecutionEvent,
        FormalizationBinding,
        ReviewDecision,
        VerifierProfile,
    )
    from ..paper_store import validate_bundle
    from ..trust import authenticated_record, verify_record

    _require(value["authentication"] == "EPHEMERAL_TEST_AUTHORITY_ONLY", "Test authority label")
    profile = VerifierProfile.from_dict(value["profile"])
    subjects: list[dict[str, Any]] = []
    for source in value["source_bundles"].values():
        artifacts = {
            name: base64.b64decode(raw, validate=True) for name, raw in source["artifacts"].items()
        }
        validate_bundle(source["bundle"], artifacts)
        subjects.extend(r for r in source["bundle"]["formalizations"] if r["status"] == "SUPPORTED")
    _require(len(subjects) == 3, "Three independent encoded subjects")
    rejection_subjects = [
        formal
        for formal in subjects
        if formal["assertion_id"] == value["goals"][0]["target"]["assertion_id"]
    ]
    _require(len(rejection_subjects) == 1, "Signed rejection subject scope")
    rejection_binding = FormalizationBinding.from_dict(rejection_subjects[0]["binding"])
    # An invalid review safely blocks acceptance, but that result does not
    # establish the separately claimed authenticated, scoped REJECT observation.
    verify_record(
        value["signed_rejection"],
        value["trust_store"],
        role="source-fidelity-review",
        subject=rejection_binding.assertion_id,
        profile_digest=profile.digest,
        evaluation_time=value["evaluation_time"],
    )
    rejection = ReviewDecision.from_dict(authenticated_record(value["signed_rejection"]))
    _require(
        rejection.decision == "REJECT"
        and rejection.binding_digest == rejection_binding.digest
        and rejection.revision_id == rejection_binding.revision_id
        and rejection.obligation_digest == rejection_binding.obligation_digest,
        "Signed rejection decision/material scope",
    )
    verified = accepted = 0
    for formal in subjects:
        binding = FormalizationBinding.from_dict(formal["binding"])
        obligation = FormalObligation.from_dict(formal["obligation"])
        matches = [
            row for row in value["events"] if row["record"]["binding_digest"] == binding.digest
        ]
        _require(len(matches) == 1, "Execution subject multiplicity")
        row = matches[0]
        event = ExecutionEvent.from_dict(row["record"])
        _require(
            event.environment["complete"]
            and event.profile_digest == profile.digest
            and authenticated_record(row["envelope"]) == event.to_dict(),
            "Execution environment/payload material",
        )
        resolution = resolve_execution(
            row["envelope"],
            value["trust_store"],
            binding,
            obligation,
            profile,
            evaluation_time=value["evaluation_time"],
        )
        verified += int(resolution["accepted"])
        before = assess_binding(
            binding,
            obligation,
            profile,
            row["envelope"],
            [],
            value["trust_store"],
            evaluation_time=value["evaluation_time"],
        )
        _require(
            before.assessment != "ACCEPTED_UNDER_POLICY",
            "Execution automatically approved fidelity",
        )
        after = assess_binding(
            binding,
            obligation,
            profile,
            row["envelope"],
            value["review_decisions"],
            value["trust_store"],
            evaluation_time=value["evaluation_time"],
        )
        accepted += int(after.assessment == "ACCEPTED_UNDER_POLICY")
        conflicting = assess_binding(
            binding,
            obligation,
            profile,
            row["envelope"],
            [*value["review_decisions"], value["signed_rejection"]],
            value["trust_store"],
            evaluation_time=value["evaluation_time"],
        )
        _require(
            conflicting.assessment != "ACCEPTED_UNDER_POLICY", "Signed rejection/conflict accepted"
        )
    _require(
        verified == 2
        and accepted == 1
        and any(row["record"]["outcome"] == "COMPILER_REJECTED" for row in value["events"]),
        "Fresh encoded verifier/review results",
    )
    _require(
        value["before_review"]["counts"]["accepted"] == 0
        and value["after_review"]["counts"]["accepted"] == 1
        and value["after_revision"]["counts"]["accepted"] == 0
        and value["after_revision"]["counts"]["verified"] == 1
        and value["conflicting_review_assessment"]["counts"]["accepted"] == 0,
        "Assessment count boundary",
    )
    _require(
        value["revision_impact"]["acceptance_carried"] is False
        and value["revision_impact"]["required_new_reviews"],
        "Revision review boundary",
    )
    _require(
        value["tampered_review_rejected"]
        and value["altered_target_rejected"]
        and all(v["counts"]["accepted"] == 0 for v in value["invalid_authority"].values()),
        "Invalid authority accepted",
    )
    _require(
        value["authenticated_restore"]["authority_imported"] is False
        and value["authenticated_restore"]["tasks_require_fresh_authorization"] is True
        and not any(
            state in {"AUTHORIZED", "QUEUED", "RUNNING"}
            for state in value["authenticated_restore_task_states"]
        )
        and value["restored_without_authority"]["counts"]["verified"] == 0
        and value["restored_without_authority"]["counts"]["accepted"] == 0
        and value["restored_with_authority"]["counts"]["verified"] == 2
        and value["restored_with_authority"]["counts"]["accepted"] == 1
        and value["authenticated_restore_audit"]["integrity"] == "PASS",
        "Authenticated dossier fresh-authority/dispatch boundary",
    )
    _require(
        value["revision_tasks"]["affected"]["state"] == "STALE"
        and value["revision_tasks"]["independent"]["state"] == "SUCCEEDED"
        and value["independent_evidence_reused"],
        "Selective revision/reuse observation",
    )
    queue = value["queue"]
    _require(
        queue["controller_crash_exit"] == 17
        and queue["late_result_fenced"]
        and queue["race_winners"] == 1
        and queue["race_process_exits"] == [0, 0]
        and queue["budget_queued_task"]
        and queue["budget_dispatch"] is None,
        "Queue recovery/fencing/budget observations",
    )
    _require(
        queue["cancelled_container"]["execution_status"] == "CANCELLED"
        and queue["cancelled_container"]["returncode"] is not None
        and queue["output_limit"]["execution_status"] == "ERROR"
        and queue["output_limit"]["retained_output_bytes"] <= 1024,
        "Actual cancellation/output observations",
    )
