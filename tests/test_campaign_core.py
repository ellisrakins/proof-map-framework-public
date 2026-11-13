from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from proofmap.campaign.models import CampaignRecord, operation_policy, qualified_ref, record
from proofmap.campaign.service import (
    _reject_source_links,
    add_goal,
    capabilities,
    ingest,
    initialize,
    select_run,
    snapshot_update,
)
from proofmap.campaign.store import CampaignStore
from proofmap.integrity import artifact_digest, canonical_bytes, strict_loads
from proofmap.paper_store import PaperStore


def _fresh_populated(tmp_path: Path):
    root = tmp_path / "papers"
    root.mkdir()
    (root / "valid.tex").write_text(
        r"\begin{theorem}\label{square}For every $x\in\mathbb{Z}$, \[(x+1)^2=x^2+2x+1\].\end{theorem}\begin{proof}Expand.\end{proof}",
        encoding="utf-8",
    )
    (root / "false.tex").write_text(
        r"\begin{theorem}\label{false}For every $x\in\mathbb{Z}$, \[x+1=x\].\end{theorem}\begin{proof}Assertion.\end{proof}",
        encoding="utf-8",
    )
    (root / "open.tex").write_text(
        r"\begin{conjecture}\label{open}Every even integer greater than two is a sum of two primes.\end{conjecture}",
        encoding="utf-8",
    )
    store = CampaignStore(tmp_path / "store")
    campaign = initialize(store, "pilot", "Audit identities and open questions")["campaign_id"]
    intake = ingest(store, campaign, root)
    return store, campaign, intake, root


@pytest.fixture
def populated(tmp_path: Path):
    value = _fresh_populated(tmp_path)
    try:
        yield value
    finally:
        value[0].close()


def _core_tree_material(root: Path):
    return {
        path.relative_to(root).as_posix(): artifact_digest(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@dataclass(frozen=True)
class CoreCampaignBaseline:
    root: Path
    subjects: bytes
    material: bytes
    audit: Path

    def verify(self):
        assert canonical_bytes(_core_tree_material(self.root)) == self.material


@pytest.fixture(scope="module")
def _core_campaign_baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp("core-campaign")
    audit = tmp_path_factory.mktemp("core-campaign-audit")
    store, campaign, intake, _ = _fresh_populated(root)
    try:
        assert store.db.execute("SELECT count(*) FROM campaign_tasks").fetchone() == (0,)
        for kind in (
            "Task",
            "TaskAttempt",
            "TaskResult",
            "OperationAuthorization",
            "ReviewDecision",
        ):
            assert not store.records(campaign, kind)
        assert store.db.execute("SELECT count(*) FROM reviews").fetchone() == (0,)
        assert store.db.execute("SELECT count(*) FROM audit_records").fetchone() == (0,)
        for manuscript in intake["manuscripts"]:
            bundle = store.inspect(manuscript["run_id"])["bundle"]
            assert not bundle["execution_events"] and not bundle["acceptance_records"]
        subjects = canonical_bytes({"campaign": campaign, "intake": intake})
    finally:
        store.close()
    assert not any(
        path.suffix in {".keys", ".key", ".pem"} for path in root.rglob("*") if path.is_file()
    )
    before = _core_tree_material(root)
    baseline = CoreCampaignBaseline(root, subjects, canonical_bytes(before), audit)
    try:
        yield baseline
    finally:
        after = _core_tree_material(root)
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


def _clone_core_campaign(tmp_path: Path, baseline: CoreCampaignBaseline):
    baseline.verify()
    assert not tmp_path.resolve().is_relative_to(baseline.root.resolve())
    assert not (tmp_path / "store").exists() and not (tmp_path / "papers").exists()
    shutil.copytree(baseline.root / "store", tmp_path / "store")
    shutil.copytree(baseline.root / "papers", tmp_path / "papers")
    assert canonical_bytes(_core_tree_material(tmp_path)) == baseline.material
    subjects = strict_loads(baseline.subjects)
    return (
        CampaignStore(tmp_path / "store"),
        subjects["campaign"],
        subjects["intake"],
        tmp_path / "papers",
    )


@pytest.fixture
def cloned_populated(tmp_path: Path, _core_campaign_baseline):
    value = _clone_core_campaign(tmp_path, _core_campaign_baseline)
    before = _core_tree_material(value[3])
    try:
        yield value
    finally:
        value[0].close()
        after = _core_tree_material(value[3])
        (_core_campaign_baseline.audit / ("consumer-" + tmp_path.name + ".json")).write_bytes(
            canonical_bytes(
                {
                    "kind": "TEST_CONSUMER_SOURCE_INTEGRITY",
                    "qualification": False,
                    "before": before,
                    "after": after,
                    "unchanged": before == after,
                }
            )
        )
        assert before == after
        _core_campaign_baseline.verify()


def test_core_campaign_clones_isolate_sources_snapshots_and_intake_refs(
    tmp_path, _core_campaign_baseline
):
    left_root, right_root = tmp_path / "left", tmp_path / "right"
    left_root.mkdir()
    right_root.mkdir()
    left, campaign, left_intake, left_papers = _clone_core_campaign(
        left_root, _core_campaign_baseline
    )
    right, right_campaign, right_intake, right_papers = _clone_core_campaign(
        right_root, _core_campaign_baseline
    )
    try:
        assert campaign == right_campaign and left_intake == right_intake
        right_head = right.current_snapshot(campaign)["id"]
        original = (right_papers / "valid.tex").read_bytes()
        left_intake["coverage"]["inventory"][0]["ref"]["assertion_digest"] = "0" * 64
        assert left_intake != right_intake
        (left_papers / "valid.tex").write_bytes(b"this copied store only")
        add_goal(left, campaign, question="Independent core clone follow-up")
        assert left.current_snapshot(campaign)["id"] != right_head
        assert right.current_snapshot(campaign)["id"] == right_head
        assert (right_papers / "valid.tex").read_bytes() == original
        _core_campaign_baseline.verify()
    finally:
        left.close()
        right.close()


def test_campaign_intake_exact_snapshot_and_coverage(populated):
    store, campaign, intake, _ = populated
    assert intake["dispatch_authorized"] is False
    assert len(intake["manuscripts"]) == 3
    snapshot = store.current_snapshot(campaign)
    assert len(snapshot["selections"]) == 3
    counts = intake["coverage"]
    assert counts["discovered"] == 3 and counts["supported"] == 2
    assert counts["verified"] == counts["accepted"] == 0
    assert counts["full_verification"] is False
    supported = [r for r in counts["inventory"] if r["status"] == "SUPPORTED"]
    assert all(r["ref"]["binding_digest"] for r in supported)
    assert store.db.execute("SELECT COUNT(*) FROM campaign_tasks").fetchone()[0] == 0


def test_goal_labels_duplicate_and_unanchored_question(cloned_populated):
    store, campaign, intake, _ = cloned_populated
    selected = next(r for r in intake["manuscripts"] if r["paper_id"] == "valid.tex")
    goal = add_goal(store, campaign, run_id=selected["run_id"], label="square")
    assert goal["origin"] == "SOURCE_BOUND_CLAIM"
    ref = qualified_ref(store, selected["run_id"], goal["target"]["assertion_id"])
    assert ref == goal["target"]
    with pytest.raises(ValueError, match="DUPLICATE"):
        add_goal(store, campaign, run_id=selected["run_id"], label="square")
    with pytest.raises(ValueError, match="MISSING_OR_AMBIGUOUS"):
        add_goal(store, campaign, run_id=selected["run_id"], label="absent")
    question = add_goal(
        store, campaign, question="Can the profile represent rational quantification?"
    )
    assert question["target"] is None and question["origin"] == "RESEARCHER_QUESTION"
    with pytest.raises(ValueError, match="CANNOT_HAVE"):
        add_goal(store, campaign, run_id=selected["run_id"], question="unanchored")


def test_second_campaign_membership_does_not_copy_sources(cloned_populated):
    store, first, intake, _ = cloned_populated
    selected = intake["manuscripts"][0]
    second = initialize(store, "another", "Independent policy")["campaign_id"]
    before = {p for p in (store.root / "objects").rglob("*") if p.is_file()}
    select_run(store, second, selected["run_id"])
    assert len(store.list()) == 3
    assert (
        store.current_snapshot(first)["selections"] != store.current_snapshot(second)["selections"]
    )
    added = {p for p in (store.root / "objects").rglob("*") if p.is_file()} - before
    assert len(added) == 2  # snapshot + membership event, no manuscript copies


def test_same_intake_reuses_pinned_run_without_duplicate_store(populated):
    store, campaign, intake, root = populated
    again = ingest(store, campaign, root)
    assert again["snapshot_id"] == intake["snapshot_id"]
    assert all(r["intake"] == "EXACT_PINNED_RUN_REUSED" for r in again["manuscripts"])
    assert len(store.list()) == 3


@pytest.mark.parametrize("previous_version", [0, 1, 2])
def test_migration_keeps_old_digests_and_backup(cloned_populated, previous_version):
    store, _, _, _ = cloned_populated
    root = store.root
    original = store.db.execute("SELECT id,bundle FROM runs ORDER BY id").fetchall()
    store.db.execute("PRAGMA user_version=" + str(previous_version))
    store.db.commit()
    other = PaperStore(root)
    try:
        assert other.db.execute("PRAGMA user_version").fetchone() == (3,)
        assert other.db.execute("SELECT id,bundle FROM runs ORDER BY id").fetchall() == original
        backups = list((root / "backups").glob(f"pre-campaign-v{previous_version}-*.sqlite3"))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as db:
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert db.execute("PRAGMA user_version").fetchone() == (previous_version,)
            assert db.execute("SELECT id,bundle FROM runs ORDER BY id").fetchall() == original
    finally:
        other.close()


def test_snapshot_cas_rejects_concurrent_update(cloned_populated):
    store, campaign, _, _ = cloned_populated
    old = store.current_snapshot(campaign)
    newer = snapshot_update(store, campaign, reason="operator update")
    competing = record(
        "CampaignSnapshot",
        **{
            k: v
            for k, v in old.items()
            if k not in {"id", "kind", "schema_version", "parent_snapshot"}
        },
        parent_snapshot=old["id"],
    )
    with pytest.raises(ValueError, match="CONCURRENT_UPDATE"):
        store.set_current_snapshot(competing)
    assert store.current_snapshot(campaign) == newer


def test_tampered_reference_cannot_enter_snapshot(cloned_populated):
    store, campaign, intake, _ = cloned_populated
    selected = next(r for r in intake["manuscripts"] if r["paper_id"] == "valid.tex")
    goal = add_goal(store, campaign, run_id=selected["run_id"], label="square")
    bad_ref = {**goal["target"], "assertion_digest": "0" * 64}
    bad_goal = record(
        "Goal", target=bad_ref, question=None, origin="SOURCE_BOUND_CLAIM", actor="operator"
    )
    with pytest.raises(ValueError, match="STALE_QUALIFIED"):
        snapshot_update(store, campaign, goals=[bad_goal])


def test_policy_limits_and_immutable_record_copies():
    for kwargs in (
        {"max_tasks": 1001},
        {"concurrency": 2},
        {"allowed_kinds": ["SHELL"]},
        {"allow_model": True},
        {"profile_digest": "trusted"},
    ):
        with pytest.raises(ValueError):
            operation_policy(**kwargs)
    value = operation_policy()
    typed = CampaignRecord.from_dict(value)
    value["allowed_kinds"].append("SHELL")
    assert "SHELL" not in typed.to_dict()["allowed_kinds"]


def test_empty_and_ambiguous_corpus_fail_closed(tmp_path):
    store = CampaignStore(tmp_path / "store")
    campaign = initialize(store, "empty", "do work")["campaign_id"]
    source = tmp_path / "papers"
    source.mkdir()
    try:
        with pytest.raises(ValueError, match="EMPTY_CORPUS"):
            ingest(store, campaign, source)
        child = source / "ambiguous"
        child.mkdir()
        (child / "one.tex").write_text("one", encoding="utf-8")
        (child / "two.tex").write_text("two", encoding="utf-8")
        with pytest.raises(ValueError, match="AMBIGUOUS_ENTRYPOINT"):
            ingest(store, campaign, source)
    finally:
        store.close()


def test_snapshots_and_goals_cannot_cross_campaign_namespaces(cloned_populated):
    store, campaign, _, _ = cloned_populated
    original = store.current_snapshot(campaign)
    second = initialize(store, "another namespace", "Independent campaign")["campaign_id"]
    other = store.current_snapshot(second)
    foreign_goal = add_goal(store, second, question="Separate goal")
    with pytest.raises(ValueError, match="GOAL_NAMESPACE"):
        snapshot_update(store, campaign, goals=[foreign_goal])
    foreign_parent = record(
        "CampaignSnapshot",
        **{
            k: v
            for k, v in original.items()
            if k not in {"id", "kind", "schema_version", "parent_snapshot"}
        },
        parent_snapshot=other["id"],
    )
    with pytest.raises(ValueError, match="PARENT_NAMESPACE"):
        store.set_current_snapshot(foreign_parent)
    store.db.execute(
        "UPDATE campaign_heads SET snapshot_id=? WHERE campaign_id=?", (other["id"], campaign)
    )
    store.db.commit()
    with pytest.raises(ValueError, match="SNAPSHOT_NAMESPACE"):
        store.current_snapshot(campaign)


def test_windows_reparse_point_rejected_before_resolve(tmp_path, monkeypatch):
    from types import SimpleNamespace

    source = tmp_path / "junction"
    source.mkdir()
    original = Path.lstat

    def junction_stat(path):
        if path == source:
            return SimpleNamespace(st_file_attributes=1024, st_mode=original(path).st_mode)
        return original(path)

    monkeypatch.setattr(Path, "lstat", junction_stat)
    with pytest.raises(ValueError, match="SOURCE_LINK_FORBIDDEN"):
        _reject_source_links(source)


def test_capability_does_not_infer_signing_authority_from_path(cloned_populated, tmp_path):
    store, campaign, _, _ = cloned_populated
    result = capabilities(
        store, campaign, controller_config={"private_key_path": str(tmp_path / "absent")}
    )
    assert result["execution_signing"] == "UNAVAILABLE_OR_INVALID_KEY"
    assert result["execution_authority"] == "NOT_EVALUATED"
    key = tmp_path / "external-key"
    key.write_bytes(bytes(range(32)))
    result = capabilities(store, campaign, controller_config={"private_key_path": str(key)})
    assert result["execution_signing"] == "AVAILABLE_EXTERNAL_KEY"
    assert result["execution_authority"] == "NOT_EVALUATED"


@pytest.mark.parametrize(
    "configuration",
    [[], {"extractor": []}, {"extractor": {"provider": "shell"}}],
)
def test_capability_rejects_invalid_model_configuration_without_probe(
    cloned_populated, configuration
):
    store, campaign, _, _ = cloned_populated
    report = capabilities(store, campaign, controller_config={"extractor_config": configuration})
    # An empty setting is absent; malformed configured settings remain visible.
    assert report["configured_extraction"] == (
        "INVALID_CONFIGURATION" if configuration else "NOT_CONFIGURED"
    )
    assert report["execution_authority"] == "NOT_EVALUATED"
    assert store.db.execute("SELECT COUNT(*) FROM campaign_tasks").fetchone() == (0,)


def test_capabilities_report_missing_optional_packages_without_claiming_execution(
    cloned_populated, monkeypatch
):
    import proofmap.campaign.service as service

    store, campaign, _, _ = cloned_populated

    def unavailable(name):
        raise service.PackageNotFoundError(name)

    monkeypatch.setattr(service, "version", unavailable)
    report = capabilities(store, campaign, controller_config={"private_key_path": "external-key"})
    assert (
        report["ingestion"]
        == report["execution_signing"]
        == report["review_verification"]
        == "UNAVAILABLE"
    )
    assert report["archive_export"] == report["report_generation"] == "SUPPORTED"
    assert not report["host_fallback"] and not report["coverage"]["authority_evaluated"]


@pytest.mark.parametrize(
    "changes",
    [
        {"max_tasks": -1},
        {"max_wall_seconds": -1},
        {"max_attempts": 0},
        {"lease_seconds": 0},
        {"model_max_requests": 101},
        {"model_max_tokens": 1_000_001},
        {"max_tasks": True},
        {"allow_model": "yes"},
        {"source_roots": [""]},
        {"source_roots": ["unsafe\x00root"]},
        {"allowed_kinds": ["ANALYZE_SOURCE", "ANALYZE_SOURCE"]},
    ],
)
def test_operation_policy_rejects_invalid_authorization_values(changes):
    with pytest.raises(ValueError):
        operation_policy(**changes)


def test_collection_uses_explicit_entrypoint_and_ignores_unrelated_files(tmp_path):
    from proofmap.campaign.service import _manuscripts

    root = tmp_path / "collection"
    root.mkdir()
    (root / "notes.txt").write_text("Not a manuscript.", encoding="utf-8")
    (root / ".cache").mkdir()
    project = root / "project"
    project.mkdir()
    (project / "only.tex").write_text("Original mathematical source.", encoding="utf-8")
    assert _manuscripts(root, None) == [(project, "only.tex", "project")]
    assert _manuscripts(project, "only.tex") == [(project, "only.tex", "project")]
    with pytest.raises(ValueError, match="UNSUPPORTED_SOURCE"):
        _manuscripts(root / "notes.txt", None)


def test_intake_policy_rejections_have_no_source_or_task_side_effects(cloned_populated, tmp_path):
    store, _, _, root = cloned_populated
    cid = initialize(
        store,
        "Restricted",
        "Retain source boundaries",
        policy=operation_policy(source_roots=[str(tmp_path / "another")]),
    )["campaign_id"]
    before = store.db.total_changes
    with pytest.raises(ValueError, match="OUTSIDE_OPERATION_POLICY"):
        ingest(store, cid, root)
    assert store.db.total_changes == before
    permitted = initialize(store, "No disclosure", "Offline intake")["campaign_id"]
    for arguments, reason in (
        ({"config": []}, "EXTRACTOR_CONFIGURATION"),
        ({"extractor": "configured"}, "MODEL_DISCLOSURE_NOT_AUTHORIZED"),
        ({"paper_id": "one"}, "PAPER_ID_REQUIRES_SINGLE_MANUSCRIPT"),
    ):
        before = store.db.total_changes
        with pytest.raises(ValueError, match=reason):
            ingest(store, permitted, root, **arguments)
        assert store.db.total_changes == before


def test_goals_cannot_target_unselected_or_wrongly_identified_runs(cloned_populated):
    store, _, intake, _ = cloned_populated
    cid = initialize(store, "Independent", "Explicit membership")["campaign_id"]
    run = intake["manuscripts"][0]["run_id"]
    with pytest.raises(ValueError, match="GOAL_RUN_NOT_SELECTED"):
        add_goal(store, cid, run_id=run, label="identity")
    with pytest.raises(ValueError, match="RUN_AND_EXACT"):
        add_goal(store, cid, run_id=run)
    assert store.current_snapshot(cid)["goals"] == []
