"""Durable queue tests. Controller fakes never qualify isolated proof evidence."""

import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path

import pytest

from proofmap.campaign import queue
from proofmap.campaign.models import operation_policy, qualified_ref
from proofmap.campaign.operations import (
    apply_decision,
    assess_campaign,
    authorize_plan,
    cancel_task,
    plan_campaign,
    recover,
    request_stage,
    review_decision,
    review_packets,
    run_campaign,
    tasks,
)
from proofmap.campaign.service import add_goal, ingest, initialize
from proofmap.campaign.store import CampaignStore
from proofmap.integrity import artifact_digest, canonical_bytes, strict_loads


def campaign(tmp_path, policy=None):
    source = tmp_path / "paper.tex"
    source.write_text(
        r"\documentclass{article}\begin{document}\begin{theorem}\label{identity}For every $x\in\mathbb{Z}$, \[(x+1)^2=x^2+2x+1.\]\end{theorem}\begin{proof}Expand.\end{proof}\begin{theorem}\label{unsupported}There are infinitely many primes.\end{theorem}\end{document}",
        encoding="utf-8",
    )
    store = CampaignStore(tmp_path / "store")
    cid = initialize(store, "Audit", "Test proof boundary", policy=policy)["campaign_id"]
    result = ingest(store, cid, source, paper_id="paper")
    run = result["manuscripts"][0]["run_id"]
    add_goal(store, cid, run_id=run, label="identity")
    return store, cid, source, run


def operations_tree_material(root: Path):
    return {
        path.relative_to(root).as_posix(): artifact_digest(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def operations_product_material():
    root = Path(sys.modules["proofmap"].__file__).resolve().parent
    return {
        path.relative_to(root).as_posix(): artifact_digest(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


@dataclass(frozen=True)
class VanillaOperationsBaseline:
    root: Path
    audit: Path
    subjects: bytes
    material: bytes
    product_material: bytes
    test_material: bytes

    def verify(self):
        assert canonical_bytes(operations_tree_material(self.root)) == self.material
        assert canonical_bytes(operations_product_material()) == self.product_material
        assert Path(__file__).read_bytes() == self.test_material


@pytest.fixture(scope="module")
def _vanilla_operations_baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp("vanilla-operations")
    audit = tmp_path_factory.mktemp("vanilla-operations-audit")
    product_material = canonical_bytes(operations_product_material())
    test_material = Path(__file__).read_bytes()
    store, cid, _, run = campaign(root)
    try:
        assert not queue.tasks(store, cid)
        for kind in (
            "Task",
            "TaskEvent",
            "TaskAttempt",
            "TaskResult",
            "OperationAuthorization",
            "ActionRequest",
            "CampaignPlan",
            "ReviewDecision",
            "ReviewHandoff",
        ):
            assert not store.records(cid, kind)
        assert store.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == 0
        assert store.db.execute("SELECT count(*) FROM audit_records").fetchone()[0] == 0
        snapshot = store.current_snapshot(cid)
        assert len(snapshot["goals"]) == 1 and len(snapshot["selections"]) == 1
        assert snapshot["goals"][0]["target"]["run_id"] == run
        policy = store.get_record(snapshot["operation_policy"])
        assert policy == operation_policy() and policy["profile_digest"] is None
        bundle = store.inspect(run)["bundle"]
        assert len(bundle["assertions"]) == 2
        assert not bundle["execution_events"] and not bundle["acceptance_records"]
        ref = qualified_ref(store, run, snapshot["goals"][0]["target"]["assertion_id"])
        subjects = canonical_bytes({"campaign_id": cid, "run_id": run, "ref": ref})
    finally:
        store.close()
    assert not any(
        path.suffix in {".keys", ".key", ".pem"} for path in root.rglob("*") if path.is_file()
    )
    before = operations_tree_material(root)
    baseline = VanillaOperationsBaseline(
        root, audit, subjects, canonical_bytes(before), product_material, test_material
    )
    baseline.verify()
    yield baseline
    after = operations_tree_material(root)
    (audit / "baseline-integrity.json").write_bytes(
        canonical_bytes(
            {
                "kind": "TEST_FIXTURE_INTEGRITY",
                "qualification": False,
                "before": before,
                "after": after,
                "unchanged": before == after,
                "serialized_subjects_sha256": artifact_digest(subjects),
                "product_before": strict_loads(product_material),
                "product_after": operations_product_material(),
                "test_before_sha256": artifact_digest(test_material),
                "test_after_sha256": artifact_digest(Path(__file__).read_bytes()),
            }
        )
    )
    baseline.verify()


def clone_operations_campaign(tmp_path: Path, baseline: VanillaOperationsBaseline):
    baseline.verify()
    assert not tmp_path.resolve().is_relative_to(baseline.root.resolve())
    assert not (tmp_path / "store").exists() and not (tmp_path / "paper.tex").exists()
    shutil.copytree(baseline.root / "store", tmp_path / "store")
    shutil.copy2(baseline.root / "paper.tex", tmp_path / "paper.tex")
    copied = canonical_bytes(operations_tree_material(tmp_path))
    assert copied == baseline.material
    receipt = artifact_digest(str(tmp_path).encode("utf-8"))
    (baseline.audit / (receipt + ".json")).write_bytes(
        canonical_bytes(
            {
                "kind": "PRIVATE_TEST_FIXTURE_COPY",
                "qualification": False,
                "copy_before_open": strict_loads(copied),
                "baseline": strict_loads(baseline.material),
                "byte_exact": True,
            }
        )
    )
    subjects = strict_loads(baseline.subjects)
    return (
        CampaignStore(tmp_path / "store"),
        subjects["campaign_id"],
        tmp_path / "paper.tex",
        subjects["run_id"],
    )


@pytest.fixture
def operations_campaign(_vanilla_operations_baseline):
    roots = []

    def intake(root):
        result = clone_operations_campaign(root, _vanilla_operations_baseline)
        roots.append(root)
        return result

    yield intake
    for root in roots:
        record_operations_clone_source(root, _vanilla_operations_baseline)
    _vanilla_operations_baseline.verify()


def record_operations_clone_source(root, baseline):
    source = root / "paper.tex"
    before = artifact_digest((baseline.root / "paper.tex").read_bytes())
    after = artifact_digest(source.read_bytes()) if source.is_file() else None
    receipt = artifact_digest(str(root).encode("utf-8"))
    (baseline.audit / (receipt + "-source-teardown.json")).write_bytes(
        canonical_bytes(
            {
                "kind": "PRIVATE_TEST_FIXTURE_SOURCE_TEARDOWN",
                "qualification": False,
                "source": "paper.tex",
                "before_sha256": before,
                "after_sha256": after,
                "exists_after": source.is_file(),
                "observed_mutation": before != after,
            }
        )
    )


def test_vanilla_operations_clones_isolate_source_goals_authorization_and_refs(
    tmp_path, _vanilla_operations_baseline
):
    left_root, right_root = tmp_path / "left", tmp_path / "right"
    left_root.mkdir()
    right_root.mkdir()
    left, cid, left_source, run = clone_operations_campaign(left_root, _vanilla_operations_baseline)
    right, right_cid, right_source, right_run = clone_operations_campaign(
        right_root, _vanilla_operations_baseline
    )
    try:
        assert cid == right_cid and run == right_run
        with pytest.raises(FrozenInstanceError):
            _vanilla_operations_baseline.root = left_root
        left_subjects = strict_loads(_vanilla_operations_baseline.subjects)
        right_subjects = strict_loads(_vanilla_operations_baseline.subjects)
        left_subjects["ref"]["assertion_digest"] = "0" * 64
        assert right_subjects["ref"]["assertion_digest"] != left_subjects["ref"]["assertion_digest"]
        right_head = right.current_snapshot(cid)["id"]
        right_material = right_source.read_bytes()
        authorize(left, cid)
        assert tasks(left, cid) and not tasks(right, cid)
        assert left.records(cid, "OperationAuthorization") and not right.records(
            cid, "OperationAuthorization"
        )
        left_source.write_bytes(b"Changed private copied source")
        add_goal(left, cid, question="Private copied-store follow-up")
        assert left.current_snapshot(cid)["id"] != right_head
        assert right.current_snapshot(cid)["id"] == right_head
        assert right_source.read_bytes() == right_material
        assert (
            qualified_ref(right, run, right_subjects["ref"]["assertion_id"])
            == right_subjects["ref"]
        )
        _vanilla_operations_baseline.verify()
    finally:
        left.close()
        right.close()
        record_operations_clone_source(left_root, _vanilla_operations_baseline)
        record_operations_clone_source(right_root, _vanilla_operations_baseline)


def authorize(store, cid, policy=None):
    selected = policy or store.get_record(store.current_snapshot(cid)["operation_policy"])
    plan = plan_campaign(store, cid)
    result = authorize_plan(store, cid, plan, selected, "operator")
    return plan, result


@pytest.fixture
def protocol_provider():
    """Local protocol fixture; it provides no live model-quality evidence."""
    import json
    import select
    import socket
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    state = {
        "requests": [],
        "delay": 0,
        "block": False,
        "entered": threading.Event(),
        "release": threading.Event(),
        "client_closed": threading.Event(),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state["requests"].append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            state["entered"].set()
            if state["block"]:
                deadline = time.monotonic() + 20
                while not state["release"].is_set() and time.monotonic() < deadline:
                    readable, _, _ = select.select([self.connection], [], [], 0.02)
                    if readable:
                        try:
                            closed = not self.connection.recv(1, socket.MSG_PEEK)
                        except ConnectionResetError:
                            closed = True
                        if closed:
                            state["client_closed"].set()
                            return
            time.sleep(state["delay"])
            body = json.dumps(
                {
                    "done": True,
                    "model": "bounded-fixture",
                    "message": {"content": json.dumps({"classifications": [], "dependencies": []})},
                }
            ).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                state["client_closed"].set()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["config"] = {
        "provider": "ollama",
        "endpoint": f"http://127.0.0.1:{server.server_port}",
        "model": "bounded-fixture",
        "timeout_seconds": 30,
        "max_output_tokens": 512,
        "max_requests": 1,
        "max_total_output_tokens": 512,
        "max_total_seconds": 30,
    }
    try:
        yield state
    finally:
        state["release"].set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_campaign_authorization_duplicate_and_human_handoff(tmp_path):
    store, cid, _, _ = campaign(tmp_path)
    try:
        plan, first = authorize(store, cid)
        assert plan["authority"] == "PLANNING_ONLY"
        assert any(b["code"] == "FORMALIZATION_UNSUPPORTED" for b in plan["blockers"])
        assert len(first["tasks"]) == 3
        policy = store.get_record(store.current_snapshot(cid)["operation_policy"])
        second = authorize_plan(store, cid, plan, policy, "operator")
        assert {t["task_id"] for t in first["tasks"]} == {t["task_id"] for t in second["tasks"]}
        assert len(tasks(store, cid)) == 3
        assert sorted(t["state"] for t in tasks(store, cid)) == [
            "AWAITING_REVIEW",
            "AWAITING_REVIEW",
            "QUEUED",
        ]
        packets = review_packets(store, cid, tmp_path / "packets")
        assert len(packets) == 1
        assert packets[0]["decision"] == "PENDING_HUMAN_REVIEW"
        assert packets[0]["source"] and packets[0]["execution"] == []
    finally:
        store.close()


def test_campaign_missing_runtime_bounded_resume(tmp_path, operations_campaign):
    store, cid, _, _ = operations_campaign(tmp_path)
    try:
        authorize(store, cid)
        result = run_campaign(store, cid, max_tasks=1)
        assert result["outcomes"][0]["state"] == "UNAVAILABLE"
        assert result["boundary"] == "AWAITING_REVIEW"
        assert store.records(cid, "TaskAttempt")[-1]["phase"] == "FINISHED"
        assert store.records(cid, "TaskResult")[-1]["mathematical_acceptance"] == "NOT_IMPLIED"
        assert not store.list_audit(
            store.current_snapshot(cid)["selections"][0]["run_id"], "ExecutionEvent"
        )
        assert run_campaign(store, cid)["outcomes"] == []
    finally:
        store.close()


def test_campaign_plan_profile_selection_does_not_evaluate_authority(tmp_path, operations_campaign):
    import test_execution as fixture

    store, cid, _, _ = operations_campaign(tmp_path)
    try:
        profile = fixture.profile().to_dict()
        plan = plan_campaign(store, cid, profile=profile)
        assert plan["profile_digest"] == fixture.profile().digest
        assert not plan["papers"][0]["paper_plan"]["actual"]["authority_evaluated"]
        assert (
            plan["papers"][0]["counts"]["verified"] == plan["papers"][0]["counts"]["accepted"] == 0
        )
        with pytest.raises(ValueError, match="AUTHORITY_INPUTS_INCOMPLETE"):
            plan_campaign(store, cid, profile=profile, evaluation_time="2026-10-02T00:00:00Z")
    finally:
        store.close()


@pytest.mark.parametrize(
    ("options", "error"),
    [
        ({"max_tasks": 0}, "TASK_BUDGET"),
        ({"max_tasks": True}, "TASK_BUDGET"),
        ({"max_wall_seconds": 0}, "TIME_BUDGET"),
        ({"max_wall_seconds": True}, "TIME_BUDGET"),
        ({"until": "forever"}, "RUN_BOUNDARY"),
        ({"task_ids": ["f" * 64]}, "TASK_SELECTION"),
    ],
)
def test_campaign_invalid_dispatch_admission_creates_no_attempt(
    tmp_path, options, error, operations_campaign
):
    store, cid, _, _ = operations_campaign(tmp_path)
    try:
        authorize(store, cid)
        original = tasks(store, cid)
        with pytest.raises(ValueError, match=error):
            run_campaign(store, cid, **options)
        assert tasks(store, cid) == original
        assert not store.records(cid, "TaskAttempt")
        assert not store.records(cid, "TaskResult")
    finally:
        store.close()


@pytest.mark.parametrize(
    "refusal", ["empty-actor", "duplicate-selection", "unknown-selection", "profile", "stale"]
)
def test_campaign_authorization_refusal_has_no_queued_work(tmp_path, refusal, operations_campaign):
    import test_execution as fixture

    store, cid, source, _ = operations_campaign(tmp_path)
    try:
        policy = store.get_record(store.current_snapshot(cid)["operation_policy"])
        plan = plan_campaign(
            store, cid, profile=fixture.profile().to_dict() if refusal == "profile" else None
        )
        actor, selected = "operator", None
        error = "CAMPAIGN_"
        if refusal == "empty-actor":
            actor, error = " ", "AUTHORIZATION_ACTOR"
        elif refusal == "duplicate-selection":
            selected, error = [plan["actions"][0]["id"]] * 2, "AUTHORIZATION_SELECTION"
        elif refusal == "unknown-selection":
            selected, error = ["f" * 64], "AUTHORIZATION_SELECTION"
        elif refusal == "profile":
            error = "POLICY_PROFILE"
        else:
            source.write_text(
                source.read_text(encoding="utf-8").replace("(x+1)^2", "(x+2)^2"), encoding="utf-8"
            )
            ingest(store, cid, source, paper_id="paper")
            error = "STALE_PLAN"
        with pytest.raises(ValueError, match=error):
            authorize_plan(store, cid, plan, policy, actor, action_ids=selected)
        assert not tasks(store, cid)
        assert not store.records(cid, "OperationAuthorization")
        assert not store.records(cid, "ActionRequest")
    finally:
        store.close()


def test_campaign_wrong_execution_profile_stales_dispatch_without_runtime(tmp_path, monkeypatch):
    import test_execution as fixture

    from proofmap.evidence_records import VerifierProfile

    profile = fixture.profile()
    policy = operation_policy(profile_digest=profile.digest)
    store, cid, _, run = campaign(tmp_path, policy)
    try:
        authorize_plan(
            store, cid, plan_campaign(store, cid, profile=profile.to_dict()), policy, "operator"
        )
        monkeypatch.setattr(
            "proofmap.execution.execute",
            lambda *args, **kwargs: pytest.fail("Wrong-profile work must never execute"),
        )
        other = VerifierProfile.create(
            **{
                name: getattr(profile, name)
                for name in ("image", "platform", "lean_sha256", "library_digest", "checker_digest")
            },
            acquisition_digest="f" * 64,
        )
        result = run_campaign(
            store,
            cid,
            controller_config={"profile": other.to_dict()},
        )
        assert result["outcomes"] == []
        assert (
            next(
                t
                for t in tasks(store, cid)
                if t["action"]["paper_action"]["kind"] == "VERIFY_FORMAL_SUBJECT"
            )["state"]
            == "STALE"
        )
        assert not store.records(cid, "TaskAttempt") and not store.list_audit(run, "ExecutionEvent")
    finally:
        store.close()


@pytest.mark.parametrize("source_change", ["edit", "delete"])
def test_campaign_captured_source_change_refuses_stage_dispatch(
    tmp_path, source_change, monkeypatch, operations_campaign
):
    store, cid, source, run = operations_campaign(tmp_path)
    try:
        policy = operation_policy(allowed_kinds=["REPARSE_SOURCE"], source_roots=[str(tmp_path)])
        requested = request_stage(
            store, cid, "REPARSE_SOURCE", {"source_path": str(source)}, policy, "operator"
        )
        material = store.get_record(requested["task_id"])["source_material"]
        original = {name: store.get(sha) for name, sha in material["artifacts"].items()}
        if source_change == "edit":
            source.write_text("Changed source after operator authorization", encoding="utf-8")
        else:
            source.unlink()
        monkeypatch.setattr(
            "proofmap.paper_sources.parse",
            lambda *args, **kwargs: pytest.fail(
                "Changed source must never be parsed for this authorization"
            ),
        )
        assert run_campaign(store, cid)["outcomes"] == []
        assert queue._projection(store, requested["task_id"])["state"] == "STALE"
        assert not store.records(cid, "TaskAttempt")
        assert {name: store.get(sha) for name, sha in material["artifacts"].items()} == original
        assert store.current_snapshot(cid)["selections"][0]["run_id"] == run
    finally:
        store.close()


def test_campaign_explicit_retry_respects_durable_attempt_cap(tmp_path):
    from proofmap.campaign.operations import retry_task

    store, cid, _, _ = campaign(tmp_path, operation_policy(max_attempts=2))
    try:
        authorize(store, cid)
        first = run_campaign(store, cid)["outcomes"][0]
        assert first["state"] == "UNAVAILABLE"
        assert retry_task(store, first["task_id"])["state"] == "QUEUED"
        second = run_campaign(store, cid)["outcomes"][0]
        assert second["state"] == "UNAVAILABLE"
        with pytest.raises(ValueError, match="RETRY_NOT_ELIGIBLE"):
            retry_task(store, first["task_id"])
        queue.rebuild(store)
        assert queue._projection(store, first["task_id"])["attempt_count"] == 2
        assert len(store.records(cid, "TaskAttempt")) == 4
        assert run_campaign(store, cid)["outcomes"] == []
    finally:
        store.close()


def test_campaign_reassessment_requires_authority_and_never_manufactures_execution(tmp_path):
    import test_execution as fixture

    from proofmap.campaign.operations import retry_task

    profile = fixture.profile()
    policy = operation_policy(allowed_kinds=["REASSESS_POLICY"], profile_digest=profile.digest)
    store, cid, _, run = campaign(tmp_path, policy)
    try:
        assertion = next(
            row["assertion_id"]
            for row in store.inspect(run)["bundle"]["formalizations"]
            if row["status"] == "SUPPORTED"
        )
        request_stage(
            store,
            cid,
            "REASSESS_POLICY",
            {"run_id": run, "assertion_id": assertion},
            policy,
            "operator",
        )
        first = run_campaign(store, cid, controller_config={"profile": profile.to_dict()})[
            "outcomes"
        ][0]
        assert first["state"] == "UNAVAILABLE"
        assert (
            "CURRENT_EXTERNAL_AUTHORITY_REQUIRED" in store.get_record(first["result_id"])["error"]
        )
        retry_task(store, first["task_id"])
        trust = {"schema_version": "2.0", "keys": []}
        second = run_campaign(
            store,
            cid,
            controller_config={
                "profile": profile.to_dict(),
                "trust_store": trust,
                "evaluation_time": "2026-10-02T00:00:00Z",
            },
        )["outcomes"][0]
        assert second["state"] == "CHECK_FAILED"
        result = store.get_record(second["result_id"])
        assert result["mathematical_acceptance"] == "NOT_IMPLIED"
        assert all(row["formal_status"] != "VERIFIED" for row in result["evidence"]["records"])
        assert not store.list_audit(run, "ExecutionEvent") and not store.list_audit(
            run, "ReviewDecision"
        )
        assert (
            assess_campaign(store, cid, profile.to_dict(), trust, "2026-10-02T00:00:00Z")["counts"][
                "accepted"
            ]
            == 0
        )
    finally:
        store.close()


def test_campaign_authenticated_dimension_handoffs_do_not_supply_execution(
    tmp_path, operations_campaign
):
    import test_execution as fixture

    store, cid, _, run = operations_campaign(tmp_path)
    try:
        authorize(store, cid)
        assertion = next(
            row["assertion_id"]
            for row in store.inspect(run)["bundle"]["formalizations"]
            if row["status"] == "SUPPORTED"
        )
        profile = fixture.profile().to_dict()
        private, trust = fixture.authority(
            "source-fidelity-review", assertion, fixture.profile().digest
        )
        trust["keys"][0]["roles"].append("formal-fidelity-review")
        for dimension, decision in (("source-fidelity", "APPROVE"), ("formal-fidelity", "REJECT")):
            envelope = review_decision(
                store,
                cid,
                run,
                assertion,
                profile,
                dimension,
                decision,
                "controller",
                "Explicit signed contract test decision",
                key=private,
            )
            assessment = apply_decision(
                store, cid, run, envelope, profile, trust, "2026-10-02T00:00:00Z"
            )
        by_kind = {t["action"]["paper_action"]["kind"]: t for t in tasks(store, cid)}
        assert by_kind["SOURCE_FIDELITY_REVIEW"]["state"] == "DECISION_RECORDED"
        assert by_kind["FORMAL_FIDELITY_REVIEW"]["state"] == "REJECTED"
        assert by_kind["VERIFY_FORMAL_SUBJECT"]["state"] == "QUEUED"
        assert assessment["counts"]["accepted"] == assessment["counts"]["verified"] == 0
        assert not store.list_audit(run, "ExecutionEvent")
        assert review_packets(store, cid, profile=profile) == []
    finally:
        store.close()


def test_queue_wrong_execution_subject_rolls_back_publication_and_can_recover(
    tmp_path, monkeypatch
):
    import test_execution as fixture

    from proofmap.campaign.models import record
    from proofmap.execution import execute

    profile = fixture.profile()
    policy = operation_policy(profile_digest=profile.digest)
    store, cid, _, run = campaign(tmp_path, policy)
    try:
        authorize_plan(
            store, cid, plan_campaign(store, cid, profile=profile.to_dict()), policy, "operator"
        )
        lease = queue.claim(
            store,
            cid,
            owner="worker",
            lease_seconds=60,
            max_attempts=2,
            reserve_seconds=1,
            max_tasks=20,
            max_wall_seconds=600,
        )
        assert lease is not None
        task = store.get_record(lease["task_id"])
        monkeypatch.setattr("proofmap.runner.shutil.which", lambda _: None)
        unrelated = execute(fixture.binding(), fixture.obligation(), b"by grind", profile)
        result = record(
            "TaskResult",
            campaign_id=cid,
            task_id=task["id"],
            attempt_id=lease["attempt_id"],
            generation=lease["generation"],
            target=task["target"],
            state="SUCCEEDED",
            evidence=unrelated,
            error=None,
            duration_seconds=0,
            created_at=queue.utc_now(),
            mathematical_acceptance="NOT_IMPLIED",
            model_effect="NOT_DISPATCHED",
        )
        original = queue._projection(store, task["id"])
        with pytest.raises(ValueError, match="EXECUTION_SUBJECT_BINDING"):
            queue.transition(
                store,
                task["id"],
                "SUCCEEDED",
                actor="worker",
                reason="wrong subject",
                token=lease["lease_token"],
                generation=lease["generation"],
                result=result,
            )
        assert queue._projection(store, task["id"]) == original
        assert not store.records(cid, "TaskResult") and not store.list_audit(run, "ExecutionEvent")
        assert recover(store, cid, now="2099-01-01T00:00:00Z") == [task["id"]]
        queue.rebuild(store)
        current = queue._projection(store, task["id"])
        assert current["state"] == "QUEUED" and current["generation"] > lease["generation"]
        assert current["lease_token"] is None
    finally:
        store.close()


def test_campaign_execution_callback_retains_typed_event_schema(monkeypatch):
    import test_execution as fixture

    import proofmap.execution as execution
    from proofmap.evidence_records import validate_record

    fixture.simulated_execution(monkeypatch)
    mocked_runner = execution.run
    monkeypatch.setattr(
        execution,
        "run",
        lambda image, source, argv, limits, **kwargs: mocked_runner(image, source, argv, limits),
    )
    result = execution.execute(
        fixture.binding(),
        fixture.obligation(),
        b"by grind",
        fixture.profile(),
        cancelled=lambda: False,
    )
    validate_record(result["event"])
    assert result["runner_status"] == "PASS"
    assert "runner_status" not in result["event"]["outputs"]


def test_campaign_fresh_audited_execution_supersedes_eligible_history(tmp_path, monkeypatch):
    """Signed worker simulation checks selection contracts, not actual Lean execution."""
    import test_execution as fixture
    from test_paper_revision_reuse import manuscript

    from proofmap.attempts import FormalObligation
    from proofmap.campaign.operations import _view
    from proofmap.campaign.service import select_run
    from proofmap.evidence_records import FormalizationBinding
    from proofmap.execution import execute
    from proofmap.integrity import canonical_bytes
    from proofmap.paper import ci
    from proofmap.paper_sources import acquire, parse
    from proofmap.runner import RunResult

    source = manuscript(tmp_path / "history.tex")
    profile = fixture.profile()
    private, trust = fixture.authority("verification-execution", "pending", profile.digest)
    subjects = set()
    for offset in (1, 2):
        manuscript(source, offset=offset)
        manifest, files = acquire(source)
        subjects.update(
            e["id"] for e in parse(manifest, files)["elements"] if e["kind"] == "ASSERTION"
        )
    trust["keys"][0]["subjects"] = sorted(subjects)
    trust["keys"][0]["roles"] += ["source-fidelity-review", "formal-fidelity-review"]

    def simulated(image, root, argv, limits):
        actual = {
            name: getattr(profile, name)
            for name in (
                "lean_sha256",
                "library_digest",
                "checker_digest",
                "platform",
                "executable",
                "search_path",
            )
        }
        actual["version"] = "Lean (version 4.30.0, TEST SIMULATION)"
        check = {
            "returncode": 0,
            "stdout": "'proofmap_target' depends on axioms: [propext, Classical.choice, Quot.sound]",
            "stderr": "",
        }
        return RunResult(
            "PASS",
            0,
            canonical_bytes(
                {
                    "outcome": "CHECKED",
                    "actual": actual,
                    "results": {"Candidate": check, "Recheck": check},
                }
            ).decode(),
            "",
            0,
            image,
            limits,
        )

    monkeypatch.setattr("proofmap.execution.run", simulated)
    now = "2026-10-02T00:00:00Z"
    options = {
        "paper_id": "history",
        "execution_profile": profile.to_dict(),
        "controller_key": private,
        "controller_id": "controller",
        "trust_store": trust,
        "evaluation_time": now,
        "require_formal": True,
    }
    manuscript(source)
    first, code = ci(source, tmp_path / "first", tmp_path / "store", **options)
    assert code == 0
    manuscript(source, offset=2)
    second, code = ci(source, tmp_path / "second", tmp_path / "store", **options)
    assert code == 0
    row = second["formalizations"][1]
    assert row["historical_execution"]["execution"] == first["execution_events"][1]
    immutable = canonical_bytes(second)
    store = CampaignStore(tmp_path / "store")
    cid = initialize(store, "History", "Current evidence selection")["campaign_id"]
    try:
        run = second["run_manifest"]["run_id"]
        select_run(store, cid, run)
        assert assess_campaign(store, cid, profile.to_dict(), trust, now)["counts"]["verified"] == 2
        fresh = execute(
            FormalizationBinding.from_dict(row["binding"]),
            FormalObligation.from_dict(row["obligation"]),
            row["candidate"].encode(),
            profile,
            private_key=private,
            controller_id="controller",
        )
        store.add_audit(run, {"record": fresh["event"], "envelope": fresh["envelope"]})
        current = assess_campaign(store, cid, profile.to_dict(), trust, now)
        assert current["counts"]["verified"] == 2 and current["counts"]["accepted"] == 0
        view = _view(store, second)
        assert "historical_execution" not in view["formalizations"][1]
        assert view["formalizations"][1]["execution_event"] == fresh["event"]["id"]
        plan = plan_campaign(
            store, cid, profile=profile.to_dict(), trust_store=trust, evaluation_time=now
        )
        assert plan["papers"][0]["counts"]["verified"] == 2
        for dimension in ("source-fidelity", "formal-fidelity"):
            approval = review_decision(
                store,
                cid,
                run,
                row["assertion_id"],
                profile.to_dict(),
                dimension,
                "APPROVE",
                "controller",
                "Explicit simulated current-binding review",
                key=private,
            )
            assessed = apply_decision(store, cid, run, approval, profile.to_dict(), trust, now)
        assert assessed["counts"]["accepted"] == 1
        assert canonical_bytes(store.inspect(run)["bundle"]) == immutable
    finally:
        store.close()


def test_queue_two_worker_race_and_rebuild(tmp_path, operations_campaign):
    store, cid, _, _ = operations_campaign(tmp_path)
    try:
        authorize(store, cid)
        barrier = threading.Barrier(2)

        def worker(name):
            other = CampaignStore(store.root)
            try:
                barrier.wait(timeout=5)
                return queue.claim(
                    other,
                    cid,
                    owner=name,
                    lease_seconds=60,
                    max_attempts=2,
                    reserve_seconds=1,
                    max_tasks=20,
                    max_wall_seconds=600,
                )
            finally:
                other.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, ("worker-a", "worker-b")))
        assert sum(value is not None for value in results) == 1
        first = next(value for value in results if value is not None)
        assert first is not None
        original = tasks(store, cid)
        store.db.execute("DELETE FROM campaign_tasks")
        store.db.commit()
        queue.rebuild(store)
        assert tasks(store, cid) == original
        cancel_task(store, first["task_id"], "operator")
        with pytest.raises(ValueError, match="LEASE_FENCED"):
            queue.transition(
                store,
                first["task_id"],
                "SUCCEEDED",
                actor="worker-a",
                reason="late",
                token=first["lease_token"],
                generation=first["generation"],
            )
        assert store.records(cid, "TaskEvent")[-1]["reason"] == "FENCED_LATE_RESULT"
        assert queue._projection(store, first["task_id"])["cancel_requested"]
        assert queue._projection(store, first["task_id"])["state"] == "RUNNING"
        queue.transition(
            store,
            first["task_id"],
            "CANCELLED",
            actor="worker-a",
            reason="container cleanup confirmed",
            token=first["lease_token"],
            generation=first["generation"],
        )
    finally:
        store.close()


def test_queue_expired_lease_fences_late_result(tmp_path, operations_campaign):
    store, cid, _, _ = operations_campaign(tmp_path)
    try:
        authorize(store, cid)
        lease = queue.claim(
            store,
            cid,
            owner="crashed-controller",
            lease_seconds=1,
            max_attempts=2,
            reserve_seconds=1,
            max_tasks=20,
            max_wall_seconds=600,
            now="2026-01-01T00:00:00Z",
        )
        assert recover(store, cid, now="2026-01-01T00:00:02Z") == [lease["task_id"]]
        newer = queue.claim(
            store,
            cid,
            owner="replacement",
            lease_seconds=60,
            max_attempts=2,
            reserve_seconds=1,
            max_tasks=20,
            max_wall_seconds=600,
        )
        assert newer["generation"] > lease["generation"]
        with pytest.raises(ValueError, match="LEASE_FENCED"):
            queue.transition(
                store,
                lease["task_id"],
                "SUCCEEDED",
                actor="old-worker",
                reason="late",
                token=lease["lease_token"],
                generation=lease["generation"],
            )
        assert tasks(store, cid)[0]["state"] in {"RUNNING", "AWAITING_REVIEW"}
        queue.transition(
            store,
            newer["task_id"],
            "CHECK_FAILED",
            actor="replacement",
            reason="check",
            token=newer["lease_token"],
            generation=newer["generation"],
        )
        assert sum(t["state"] == "CHECK_FAILED" for t in tasks(store, cid)) == 1
        assert len(store.records(cid, "TaskAttempt")) == 4
    finally:
        store.close()


def test_campaign_revision_stales_affected_members_only(tmp_path, operations_campaign):
    store, cid, source, old_run = operations_campaign(tmp_path)
    try:
        other_source = tmp_path / "independent.tex"
        other_source.write_text(
            source.read_text().replace("(x+1)^2=x^2+2x+1", "x+0=x"), encoding="utf-8"
        )
        independent = ingest(store, cid, other_source, paper_id="independent")["manuscripts"][0][
            "run_id"
        ]
        add_goal(store, cid, run_id=independent, label="identity")
        authorize(store, cid)
        before = tasks(store, cid)
        source.write_text(
            source.read_text().replace("(x+1)^2=x^2+2x+1", "(x+1)^2=x^2+2x+2"), encoding="utf-8"
        )
        revised = ingest(store, cid, source, paper_id="paper")["manuscripts"][0]["run_id"]
        assert revised != old_run
        assert all(
            t["state"] == "STALE" for t in tasks(store, cid) if t["target"]["run_id"] == old_run
        )
        assert {t["id"] for t in tasks(store, cid) if t["state"] != "STALE"} == {
            t["id"] for t in before if t["target"]["run_id"] == independent
        }
    finally:
        store.close()


def test_campaign_review_is_explicit_and_abstention_does_not_sign(tmp_path, operations_campaign):
    import test_execution as fixture

    store, cid, _, run = operations_campaign(tmp_path)
    try:
        assertion = next(
            r["assertion_id"]
            for r in store.inspect(run)["bundle"]["formalizations"]
            if r["status"] == "SUPPORTED"
        )
        with pytest.raises(ValueError, match="EXPLICIT_REVIEW"):
            review_decision(
                store,
                cid,
                run,
                assertion,
                fixture.profile().to_dict(),
                "source-fidelity",
                "APPROVE",
                "reviewer",
                "",
            )
        abstain = review_decision(
            store,
            cid,
            run,
            assertion,
            fixture.profile().to_dict(),
            "source-fidelity",
            "ABSTAIN",
            "reviewer",
            "Need domain clarification",
        )
        assert abstain["kind"] == "ReviewHandoff" and abstain["decision"] == "ABSTAIN"
        assert not store.list_audit(run, "ReviewDecision")
        draft = review_decision(
            store,
            cid,
            run,
            assertion,
            fixture.profile().to_dict(),
            "source-fidelity",
            "REJECT",
            "reviewer",
            "Encoding differs",
        )
        assert draft["decision"] == "REJECT" and "signatures" not in draft
    finally:
        store.close()


def test_queue_budget_reservation_and_attempt_cap(tmp_path, operations_campaign):
    store, cid, _, _ = operations_campaign(tmp_path)
    try:
        authorize(store, cid)
        assert (
            queue.claim(
                store,
                cid,
                owner="worker",
                lease_seconds=60,
                max_attempts=2,
                reserve_seconds=30,
                max_tasks=2,
                max_wall_seconds=29,
            )
            is None
        )
        lease = queue.claim(
            store,
            cid,
            owner="worker",
            lease_seconds=60,
            max_attempts=1,
            reserve_seconds=1,
            max_tasks=1,
            max_wall_seconds=10,
        )
        assert lease
        queue.transition(
            store,
            lease["task_id"],
            "ERROR",
            actor="worker",
            reason="crash",
            token=lease["lease_token"],
            generation=lease["generation"],
        )
        queue.transition(
            store, lease["task_id"], "QUEUED", actor="operator", reason="explicit retry"
        )
        assert (
            queue.claim(
                store,
                cid,
                owner="worker",
                lease_seconds=60,
                max_attempts=1,
                reserve_seconds=1,
                max_tasks=1,
                max_wall_seconds=10,
            )
            is None
        )
    finally:
        store.close()


def test_campaign_source_and_analysis_stage_adapters(tmp_path, operations_campaign):
    store, cid, source, run = operations_campaign(tmp_path)
    try:
        policy = operation_policy(
            allowed_kinds=[
                "REPARSE_SOURCE",
                "EXACT_COMPUTATION",
                "FORMALIZE_SUPPORTED",
                "REFRESH_REPORT",
                "INGEST_SOURCE",
            ]
        )
        request = request_stage(
            store, cid, "REPARSE_SOURCE", {"source_path": str(source)}, policy, "operator"
        )
        result = run_campaign(store, cid)
        assert result["outcomes"][0]["state"] == "SUCCEEDED"
        assert (
            store.get_record(queue._projection(store, request["task_id"])["last_result"])[
                "evidence"
            ]["document_ir"]["revision"]
            == store.inspect(run)["bundle"]["input_manifest"]["revision"]
        )
        assertion = next(
            r["assertion_id"]
            for r in store.inspect(run)["bundle"]["formalizations"]
            if r["status"] == "SUPPORTED"
        )
        for kind in ("EXACT_COMPUTATION", "FORMALIZE_SUPPORTED", "REFRESH_REPORT"):
            request_stage(
                store, cid, kind, {"run_id": run, "assertion_id": assertion}, policy, "operator"
            )
        assert all(r["state"] == "SUCCEEDED" for r in run_campaign(store, cid)["outcomes"])
        request_stage(
            store,
            cid,
            "INGEST_SOURCE",
            {"source_path": str(source), "paper_id": "paper"},
            policy,
            "operator",
        )
        assert run_campaign(store, cid)["outcomes"][0]["state"] == "SUCCEEDED"
        assert len(store.current_snapshot(cid)["selections"]) == 1
    finally:
        store.close()


def test_campaign_authenticated_review_requires_external_authority(
    tmp_path, monkeypatch, operations_campaign
):
    """Ephemeral simulated execution qualifies only trust adapter contracts."""
    import test_execution as fixture

    from proofmap.attempts import FormalObligation
    from proofmap.evidence_records import FormalizationBinding

    store, cid, _, run = operations_campaign(tmp_path)
    try:
        bundle = store.inspect(run)["bundle"]
        row = next(r for r in bundle["formalizations"] if r["status"] == "SUPPORTED")
        binding = FormalizationBinding.from_dict(row["binding"])
        obligation = FormalObligation.from_dict(row["obligation"])
        monkeypatch.setattr(fixture, "binding", lambda: binding)
        monkeypatch.setattr(fixture, "obligation", lambda: obligation)
        from proofmap.execution import execute

        original_authority = fixture.authority
        monkeypatch.setattr(
            fixture,
            "authority",
            lambda role, subject, profile_digest: original_authority(
                role, binding.assertion_id, profile_digest
            ),
        )
        monkeypatch.setattr(
            fixture,
            "execute",
            lambda binding_arg, obligation_arg, candidate_arg, profile_arg, **kwargs: execute(
                binding_arg, obligation_arg, row["candidate"].encode("utf-8"), profile_arg, **kwargs
            ),
        )
        execution, private, trust = fixture.simulated_execution(monkeypatch)
        store.add_audit(run, {"record": execution["event"], "envelope": execution["envelope"]})
        profile = fixture.profile().to_dict()
        now = "2026-10-02T00:00:00Z"
        before = assess_campaign(store, cid, profile, trust, now)
        assert before["counts"]["verified"] == 1 and before["counts"]["accepted"] == 0
        approval = review_decision(
            store,
            cid,
            run,
            binding.assertion_id,
            profile,
            "source-fidelity",
            "APPROVE",
            "controller",
            "Ephemeral contract test",
            key=private,
        )
        with pytest.raises(ValueError):
            apply_decision(store, cid, run, approval, profile, trust, now)
        trust["keys"][0]["roles"] += ["source-fidelity-review", "formal-fidelity-review"]
        for dimension in ("source-fidelity", "formal-fidelity"):
            approval = review_decision(
                store,
                cid,
                run,
                binding.assertion_id,
                profile,
                dimension,
                "APPROVE",
                "controller",
                "Ephemeral contract test",
                key=private,
            )
            assessed = apply_decision(store, cid, run, approval, profile, trust, now)
        assert assessed["counts"]["accepted"] == 1
        for field, value in (
            ("revoked", True),
            ("not_after", "2026-02-01T00:00:00Z"),
            ("subjects", ["different-assertion"]),
        ):
            modified = deepcopy(trust)
            modified["keys"][0][field] = value
            assert assess_campaign(store, cid, profile, modified, now)["counts"]["accepted"] == 0
        rejection = review_decision(
            store,
            cid,
            run,
            binding.assertion_id,
            profile,
            "source-fidelity",
            "REJECT",
            "controller",
            "Conflicting explicit decision",
            key=private,
        )
        assert (
            apply_decision(store, cid, run, rejection, profile, trust, now)["counts"]["accepted"]
            == 0
        )
    finally:
        store.close()


def test_campaign_recorded_and_configured_extraction_stage_adapters(tmp_path, operations_campaign):
    """Fake protocol provider plus exact replay; live quality is NOT_MEASURED."""
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from test_semantic_candidates import replay_for

    store, cid, source, run = operations_campaign(tmp_path)
    document = store.inspect(run)["bundle"]["document_ir"]
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps(
                {
                    "done": True,
                    "model": "fixture-provider",
                    "message": {"content": json.dumps({"classifications": [], "dependencies": []})},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    config = {
        "provider": "ollama",
        "endpoint": f"http://127.0.0.1:{server.server_port}",
        "model": "fixture-provider",
        "timeout_seconds": 3,
        "max_output_tokens": 512,
        "max_requests": 1,
        "max_total_output_tokens": 512,
        "max_total_seconds": 3,
    }
    policy = operation_policy(
        allowed_kinds=["EXTRACT_CONFIGURED", "EXTRACT_RECORDED"],
        allow_model=True,
        model_max_requests=1,
        model_max_tokens=512,
    )
    try:
        request_stage(
            store,
            cid,
            "EXTRACT_CONFIGURED",
            {"source_path": str(source), "paper_id": "paper"},
            policy,
            "operator",
            config=config,
        )
        results = run_campaign(store, cid, controller_config={"extractor_config": config})
        assert results["outcomes"][0]["state"] == "SUCCEEDED", results
        assert len(requests) == 1
        replay = replay_for(document, config, {"classifications": [], "dependencies": []})
        request_stage(
            store,
            cid,
            "EXTRACT_RECORDED",
            {"source_path": str(source), "paper_id": "paper"},
            policy,
            "operator",
            config=config,
            replay=replay,
        )
        results = run_campaign(
            store, cid, controller_config={"extractor_config": config, "extractor_replay": replay}
        )
        assert results["outcomes"][0]["state"] == "SUCCEEDED", results
        assert len(requests) == 1
        assert not store.list_audit(run, "ExecutionEvent")
        source.write_text(source.read_text().replace("2x+1", "2x+2"), encoding="utf-8")
        request_stage(
            store,
            cid,
            "EXTRACT_CONFIGURED",
            {"source_path": str(source), "paper_id": "paper"},
            policy,
            "operator",
            config=config,
        )
        assert (
            run_campaign(store, cid, controller_config={"extractor_config": config})["outcomes"]
            == []
        )
        assert len(requests) == 1  # The campaign budget is not reset per task.
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        store.close()


def test_queue_model_unknown_effect_is_charged_and_not_automatically_retried(
    tmp_path, operations_campaign
):
    store, cid, _, _ = operations_campaign(tmp_path)
    try:
        authorize(store, cid)
        lease = queue.claim(
            store,
            cid,
            owner="model-controller",
            lease_seconds=1,
            max_attempts=2,
            reserve_seconds=1,
            max_tasks=20,
            max_wall_seconds=600,
            model_reserve_requests=1,
            model_reserve_tokens=512,
            model_max_requests=10,
            model_max_tokens=5120,
            now="2026-01-01T00:00:00Z",
        )
        recover(store, cid, now="2026-01-01T00:00:02Z")
        projection = queue._projection(store, lease["task_id"])
        assert projection["state"] == "ERROR" and projection["model_unknown_effect"]
        assert (
            projection["model_consumed_requests"] == 1
            and projection["model_consumed_tokens"] == 512
        )
        queue.transition(
            store, lease["task_id"], "QUEUED", actor="operator", reason="explicit attempt"
        )
        assert (
            queue.claim(
                store,
                cid,
                owner="another-controller",
                lease_seconds=60,
                max_attempts=2,
                reserve_seconds=1,
                max_tasks=20,
                max_wall_seconds=600,
                model_reserve_requests=1,
                model_reserve_tokens=512,
                model_max_requests=10,
                model_max_tokens=5120,
            )
            is None
        )
    finally:
        store.close()


def test_configured_intake_shares_aggregate_queue_budget_across_calls_and_collection(
    tmp_path, protocol_provider, operations_campaign
):
    """Real local protocol adapter with no live model-quality claim."""
    import proofmap.campaign.service as service

    store, cid, source, _ = operations_campaign(tmp_path)
    policy = operation_policy(
        allowed_kinds=["EXTRACT_CONFIGURED"],
        allow_model=True,
        model_max_requests=1,
        model_max_tokens=512,
    )
    service.snapshot_update(store, cid, policy=policy)
    configured_calls = protocol_provider["requests"]
    config = {"extractor": protocol_provider["config"]}
    collection = tmp_path / "collection"
    collection.mkdir()
    (collection / "a.tex").write_bytes(source.read_bytes())
    (collection / "b.tex").write_bytes(source.read_bytes())
    try:
        result = service.ingest(store, cid, collection, extractor="configured", config=config)
        assert len(configured_calls) == 1
        assert len(result["manuscripts"]) == 2
        assert sum(row["exit_code"] == 0 for row in result["manuscripts"]) == 1
        again = service.ingest(store, cid, collection, extractor="configured", config=config)
        assert len(configured_calls) == 1
        assert len(again["manuscripts"]) == 2
        assert sum(task["model_consumed_requests"] for task in tasks(store, cid)) == 1
        assert sum(task["model_consumed_tokens"] for task in tasks(store, cid)) == 512
    finally:
        store.close()


def _queued_model_stage(tmp_path, provider):
    source = tmp_path / "queued.tex"
    source.write_text(
        r"\documentclass{article}\begin{document}A retained manuscript.\end{document}",
        encoding="utf-8",
    )
    policy = operation_policy(
        allowed_kinds=["EXTRACT_CONFIGURED"],
        lease_seconds=1,
        allow_model=True,
        model_max_requests=1,
        model_max_tokens=512,
    )
    store = CampaignStore(tmp_path / "store")
    cid = initialize(store, "Lifecycle", "Bounded retained intake", policy=policy)["campaign_id"]
    task = request_stage(
        store,
        cid,
        "EXTRACT_CONFIGURED",
        {"source_path": str(source), "paper_id": "paper"},
        policy,
        "operator",
        config=provider["config"],
    )
    return store, cid, task["task_id"], source


def _run_separate_controller(root, cid, config):
    store = CampaignStore(root)
    try:
        return run_campaign(store, cid, controller_config={"extractor_config": config})
    finally:
        store.close()


def test_nonlean_short_lease_heartbeat_and_atomic_source_promotion(tmp_path, protocol_provider):
    """Actual HTTP extraction exceeds a valid lease; parent keeps it acquired."""
    protocol_provider["delay"] = 2.5
    store, cid, task_id, _ = _queued_model_stage(tmp_path, protocol_provider)
    try:
        assert not store.current_snapshot(cid)["selections"]
        outcome = run_campaign(
            store, cid, controller_config={"extractor_config": protocol_provider["config"]}
        )
        assert outcome["outcomes"][0]["state"] == "SUCCEEDED", outcome
        projection = queue._projection(store, task_id)
        assert projection["attempt_count"] == 1 and projection["model_consumed_requests"] == 1
        assert not projection["model_unknown_effect"]
        result = store.get_record(projection["last_result"])
        assert result["duration_seconds"] > 2.5
        assert result["evidence"]["worker_cleanup"]["completed"]
        assert len(store.current_snapshot(cid)["selections"]) == 1
        assert len([e for e in store.records(cid, "TaskEvent") if e["reason"] == "HEARTBEAT"]) > 2
        queue.rebuild(store)
        assert queue._projection(store, task_id) == projection
    finally:
        store.close()


def test_nonlean_running_cancel_terminates_adapter_before_cancelled(tmp_path, protocol_provider):
    protocol_provider["block"] = True
    store, cid, task_id, _ = _queued_model_stage(tmp_path, protocol_provider)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                _run_separate_controller, store.root, cid, protocol_provider["config"]
            )
            assert protocol_provider["entered"].wait(10), "The real HTTP adapter never dispatched"
            requested = cancel_task(store, task_id)
            assert requested["state"] == "RUNNING" and requested["cancel_requested"]
            outcome = future.result(timeout=10)
        assert outcome["outcomes"][0]["state"] == "CANCELLED", outcome
        assert protocol_provider["client_closed"].wait(3), "Stopped worker retained its HTTP socket"
        projection = queue._projection(store, task_id)
        result = store.get_record(projection["last_result"])
        assert result["evidence"]["worker_cleanup"]["completed"]
        assert projection["model_unknown_effect"] and projection["model_consumed_requests"] == 1
        assert not store.current_snapshot(cid)["selections"]
        assert store.records(cid, "TaskAttempt")[-1]["phase"] == "FINISHED"
        assert run_campaign(store, cid)["outcomes"] == []
    finally:
        store.close()


def test_nonlean_cleanup_failure_records_error_without_source_promotion(
    tmp_path, protocol_provider, monkeypatch
):
    from proofmap.campaign import lifecycle

    original = lifecycle._stop

    def cleanup_failure(process, job):
        original(process, job)
        raise OSError("Explicit cleanup confirmation failure")

    monkeypatch.setattr(lifecycle, "_stop", cleanup_failure)
    store, cid, task_id, _ = _queued_model_stage(tmp_path, protocol_provider)
    try:
        outcome = run_campaign(
            store, cid, controller_config={"extractor_config": protocol_provider["config"]}
        )
        assert outcome["outcomes"][0]["state"] == "ERROR", outcome
        projection = queue._projection(store, task_id)
        result = store.get_record(projection["last_result"])
        assert not result["evidence"]["worker_cleanup"]["completed"]
        assert projection["model_unknown_effect"]
        assert not store.current_snapshot(cid)["selections"]
    finally:
        store.close()


def test_nonlean_malformed_worker_response_retains_unknown_model_effect(
    tmp_path, protocol_provider, monkeypatch
):
    monkeypatch.setattr("proofmap.campaign.lifecycle.strict_loads", lambda raw: [])
    store, cid, task_id, _ = _queued_model_stage(tmp_path, protocol_provider)
    try:
        outcome = run_campaign(
            store, cid, controller_config={"extractor_config": protocol_provider["config"]}
        )
        assert len(protocol_provider["requests"]) == 1
        assert outcome["outcomes"][0]["state"] == "ERROR", outcome
        projection = queue._projection(store, task_id)
        result = store.get_record(projection["last_result"])
        assert "WORKER_RESPONSE_INVALID" in result["error"]
        assert result["model_effect"] == "POSSIBLE_EXTERNAL_EFFECT"
        assert projection["model_consumed_requests"] == 1 and projection["model_unknown_effect"]
        assert not store.current_snapshot(cid)["selections"]
    finally:
        store.close()


def test_nonlean_changed_source_during_execution_cannot_promote_retained_run(
    tmp_path, protocol_provider
):
    protocol_provider["block"] = True
    store, cid, task_id, source = _queued_model_stage(tmp_path, protocol_provider)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                _run_separate_controller, store.root, cid, protocol_provider["config"]
            )
            assert protocol_provider["entered"].wait(10)
            source.write_text("Changed after captured authorization", encoding="utf-8")
            protocol_provider["release"].set()
            outcome = future.result(timeout=10)
        assert outcome["outcomes"][0]["state"] == "FENCED", outcome
        assert queue._projection(store, task_id)["state"] == "STALE"
        assert not store.records(cid, "TaskResult")
        assert not store.current_snapshot(cid)["selections"]
        assert store.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    finally:
        store.close()


@pytest.mark.parametrize("change", ["revoked", "expired"])
def test_campaign_fresh_evaluation_does_not_reuse_completed_authority(
    tmp_path, monkeypatch, change
):
    """Signed simulation exercises authority contracts, not actual Lean evidence."""
    import test_execution as fixture

    from proofmap.attempts import FormalObligation
    from proofmap.campaign.operations import _satisfied_actions
    from proofmap.evidence_records import FormalizationBinding
    from proofmap.execution import execute

    profile = fixture.profile()
    policy = operation_policy(allowed_kinds=["REASSESS_POLICY"], profile_digest=profile.digest)
    store, cid, _, run = campaign(tmp_path, policy)
    try:
        row = next(
            r for r in store.inspect(run)["bundle"]["formalizations"] if r["status"] == "SUPPORTED"
        )
        binding = FormalizationBinding.from_dict(row["binding"])
        obligation = FormalObligation.from_dict(row["obligation"])
        original_authority = fixture.authority
        monkeypatch.setattr(fixture, "binding", lambda: binding)
        monkeypatch.setattr(fixture, "obligation", lambda: obligation)
        monkeypatch.setattr(
            fixture,
            "authority",
            lambda role, subject, selected: original_authority(
                role, binding.assertion_id, selected
            ),
        )
        monkeypatch.setattr(
            fixture,
            "execute",
            lambda b, o, c, p, **kw: execute(b, o, row["candidate"].encode(), p, **kw),
        )
        execution, _, trust = fixture.simulated_execution(monkeypatch)
        store.add_audit(run, {"record": execution["event"], "envelope": execution["envelope"]})
        inputs = {"run_id": run, "assertion_id": binding.assertion_id}
        first = request_stage(store, cid, "REASSESS_POLICY", inputs, policy, "operator")
        duplicate = request_stage(store, cid, "REASSESS_POLICY", inputs, policy, "operator")
        assert duplicate["task_id"] == first["task_id"]
        config = {
            "profile": profile.to_dict(),
            "trust_store": trust,
            "evaluation_time": "2026-10-02T00:00:00Z",
        }
        outcome = run_campaign(store, cid, controller_config=config)
        assert outcome["outcomes"][0]["state"] == "SUCCEEDED", outcome
        first_result = store.get_record(queue._projection(store, first["task_id"])["last_result"])
        assert first_result["evidence"]["records"][0]["formal_status"] == "VERIFIED"
        second = request_stage(store, cid, "REASSESS_POLICY", inputs, policy, "operator")
        assert second["task_id"] != first["task_id"]
        if change == "revoked":
            trust["keys"][0]["revoked"] = True
        else:
            config["evaluation_time"] = "2028-01-01T00:00:00Z"
        assert first_result["id"] == store.get_record(first_result["id"])["id"]
        outcome = run_campaign(store, cid, controller_config=config)
        assert outcome["outcomes"][0]["state"] == "CHECK_FAILED", outcome
        second_result = store.get_record(queue._projection(store, second["task_id"])["last_result"])
        assert second_result["id"] != first_result["id"]
        assert second_result["evidence"]["records"][0]["formal_status"] != "VERIFIED"
        assert second_result["evidence"]["records"][0]["assessment"] != "ACCEPTED"
        assert store.get_record(second["task_id"])["action_id"] not in _satisfied_actions(
            store, tasks(store, cid)
        )
        assert len(store.list_audit(run, "ExecutionEvent")) == 1
    finally:
        store.close()


def test_configured_intake_task_id_cannot_authorize_unacquired_dispatch(
    tmp_path, monkeypatch, operations_campaign
):
    import proofmap.campaign.service as service

    store, cid, source, _ = operations_campaign(tmp_path)
    policy = operation_policy(
        allowed_kinds=["EXTRACT_CONFIGURED"],
        allow_model=True,
        model_max_requests=1,
        model_max_tokens=512,
    )
    config = {
        "provider": "ollama",
        "endpoint": "http://localhost:11434",
        "model": "never-contacted-contract-test",
        "timeout_seconds": 3,
        "max_output_tokens": 512,
        "max_requests": 1,
        "max_total_output_tokens": 512,
        "max_total_seconds": 3,
    }
    try:
        request = request_stage(
            store,
            cid,
            "EXTRACT_CONFIGURED",
            {"source_path": str(source), "paper_id": "paper"},
            policy,
            "operator",
            config=config,
        )
        monkeypatch.setattr(
            service,
            "ci",
            lambda *args, **kwargs: pytest.fail("Unacquired task caused model intake"),
        )
        with pytest.raises(ValueError, match="ACQUIRED_TASK"):
            service.ingest(
                store,
                cid,
                source,
                extractor="configured",
                config={"extractor": config},
                paper_id="paper",
                _task_id=request["task_id"],
            )
        lease = queue.claim(
            store,
            cid,
            owner="controller",
            lease_seconds=60,
            max_attempts=2,
            reserve_seconds=3,
            max_tasks=20,
            max_wall_seconds=600,
            model_reserve_requests=1,
            model_reserve_tokens=512,
            model_max_requests=1,
            model_max_tokens=512,
        )
        with pytest.raises(ValueError, match="ACQUIRED_TASK"):
            service.ingest(
                store,
                cid,
                source,
                extractor="configured",
                config={"extractor": config},
                paper_id="paper",
                _task_id=request["task_id"],
                _lease_token="wrong-token",
                _lease_generation=lease["generation"],
                actor="controller",
            )
    finally:
        store.close()


def test_queue_controller_process_crash_preserves_attempt(tmp_path, operations_campaign):
    """Kill a controller after committed acquisition, then explicitly recover."""
    store, cid, _, _ = operations_campaign(tmp_path)
    process = None
    try:
        authorize(store, cid)
        code = "from pathlib import Path; import sys,threading; from proofmap.campaign.store import CampaignStore; from proofmap.campaign.queue import claim; s=CampaignStore(Path(sys.argv[1])); p=claim(s,sys.argv[2],owner='crash-driver',lease_seconds=1,max_attempts=2,reserve_seconds=1,max_tasks=20,max_wall_seconds=600); print(p['task_id'],flush=True); threading.Event().wait(30)"
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(store.root), cid],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        task_id = process.stdout.readline().strip()
        assert task_id and queue._projection(store, task_id)["state"] == "RUNNING"
        process.kill()
        process.wait(timeout=5)
        assert process.returncode != 0
        assert recover(store, cid, now="2100-01-01T00:00:00Z") == [task_id]
        attempts = store.records(cid, "TaskAttempt")
        assert attempts[-1]["reason"] == "EXPIRED_LEASE_RECOVERY"
        assert attempts[-1]["parent_attempt"] == attempts[-2]["id"]
        assert queue._projection(store, task_id)["state"] == "QUEUED"
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        store.close()


@pytest.mark.skipif(
    os.environ.get("PROOFMAP_SANDBOX_TEST") != "1",
    reason="Requires acquired pinned Linux container image",
)
def test_real_cancelled_bounded_container(tmp_path):
    from test_runner import IMAGE

    from proofmap.runner import Limits, run

    tmp_path.chmod(0o755)
    # Cancel only after observing a running container: a pre-dispatch cancel is
    # not evidence that the whole container was terminated.
    observed = []

    def cancelled():
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, timeout=5, check=False
        )
        running = any(name.startswith(b"proofmap-") for name in result.stdout.splitlines())
        if running:
            observed.append(True)
        return running

    result = run(
        IMAGE,
        tmp_path,
        ("python", "-c", "while True: pass"),
        Limits(seconds=15),
        cancelled=cancelled,
    )
    assert observed and result.execution_status == "CANCELLED", result
    assert result.duration_seconds < 15


@pytest.mark.skipif(
    os.environ.get("PROOFMAP_SANDBOX_TEST") != "1",
    reason="Requires acquired pinned Linux container image",
)
def test_real_queue_cancel_waits_for_container_cleanup(tmp_path, operations_campaign):
    from test_runner import IMAGE

    from proofmap.runner import Limits, run

    store, cid, _, _ = operations_campaign(tmp_path)
    ready = threading.Event()
    finished = threading.Event()
    results = []
    worker = None
    try:
        authorize(store, cid)
        lease = queue.claim(
            store,
            cid,
            owner="cancel-worker",
            lease_seconds=60,
            max_attempts=2,
            reserve_seconds=15,
            max_tasks=20,
            max_wall_seconds=600,
        )
        initial = subprocess.run(
            ["docker", "ps", "--filter", f"ancestor={IMAGE}", "--format", "{{.Names}}"],
            capture_output=True,
            timeout=5,
            check=False,
        ).stdout.splitlines()

        def controller():
            connection = CampaignStore(store.root)
            try:

                def cancelled():
                    running = subprocess.run(
                        ["docker", "ps", "--filter", f"ancestor={IMAGE}", "--format", "{{.Names}}"],
                        capture_output=True,
                        timeout=5,
                        check=False,
                    ).stdout.splitlines()
                    if any(
                        name.startswith(b"proofmap-") and name not in initial for name in running
                    ):
                        ready.set()
                    return not queue.heartbeat(
                        connection,
                        lease["task_id"],
                        lease["lease_token"],
                        lease["generation"],
                        lease_seconds=60,
                        owner="cancel-worker",
                    )

                result = run(
                    IMAGE,
                    tmp_path,
                    ("python", "-c", "while True: pass"),
                    Limits(seconds=15),
                    cancelled=cancelled,
                )
                results.append(result)
                queue.transition(
                    connection,
                    lease["task_id"],
                    "CANCELLED" if result.execution_status == "CANCELLED" else "ERROR",
                    actor="cancel-worker",
                    reason="OBSERVED_CONTAINER_CLEANUP:" + result.execution_status,
                    token=lease["lease_token"],
                    generation=lease["generation"],
                    usage_seconds=result.duration_seconds,
                )
            finally:
                connection.close()
                finished.set()

        worker = threading.Thread(target=controller)
        worker.start()
        assert ready.wait(timeout=10), "Real bounded container did not start"
        projection = cancel_task(store, lease["task_id"], "operator")
        assert projection["state"] == "RUNNING" and projection["cancel_requested"]
        assert finished.wait(timeout=20), "Container cleanup did not complete"
        assert results[0].execution_status == "CANCELLED"
        assert queue._projection(store, lease["task_id"])["state"] == "CANCELLED"
        assert any(e["reason"] == "CANCEL_REQUESTED" for e in store.records(cid, "TaskEvent"))
    finally:
        if worker is not None:
            worker.join(timeout=20)
        store.close()
