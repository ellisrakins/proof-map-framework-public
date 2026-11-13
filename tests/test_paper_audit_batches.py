"""Audit batching shares a fresh source inspection, never an authority decision."""

import shutil
import sqlite3
from copy import deepcopy

import pytest
from test_execution import profile

from proofmap.evidence_records import FormalizationBinding, ReviewDecision
from proofmap.integrity import canonical_bytes, digest
from proofmap.paper import ci
from proofmap.paper_evidence import reassess
from proofmap.paper_store import PaperStore
from proofmap.trust import sign_record
from scripts.paper_e2e_isolated import BRANCH_MANUSCRIPT

KEY = b"b" * 32
TIME = "2026-10-02T00:00:00Z"


@pytest.fixture(scope="module")
def batch_source(tmp_path_factory):
    root = tmp_path_factory.mktemp("audit-source")
    source = root / "paper.tex"
    source.write_text(BRANCH_MANUSCRIPT, encoding="utf-8")
    bundle, code = ci(source, root / "out", root / "store")
    assert code == 0
    records = []
    for row in bundle["formalizations"]:
        assert row["status"] == "SUPPORTED"
        binding = FormalizationBinding.from_dict(row["binding"])
        for dimension in ("source-fidelity", "formal-fidelity"):
            record = ReviewDecision.create(
                binding=binding,
                profile=profile(),
                dimension=dimension,
                decision="APPROVE",
                reviewer_id="batch-test",
            ).to_dict()
            records.append({"record": record, "envelope": sign_record(record, KEY, "batch-test")})
    return root / "store", bundle, records


@pytest.fixture
def batch_store(batch_source, tmp_path):
    root, bundle, records = batch_source
    shutil.copytree(root, tmp_path / "store")
    store = PaperStore(tmp_path / "store")
    try:
        yield store, deepcopy(bundle), deepcopy(records)
    finally:
        store.close()


def audit_rows(store):
    return store.db.execute("SELECT * FROM audit_records ORDER BY rowid").fetchall()


def test_batch_matches_singletons_and_duplicate_order_without_rewriting_source(
    batch_source, batch_store, tmp_path, monkeypatch
):
    store, bundle, records = batch_store
    run = bundle["run_manifest"]["run_id"]
    root, _, _ = batch_source
    shutil.copytree(root, tmp_path / "singletons")
    singletons = PaperStore(tmp_path / "singletons")
    repeated = [records[0], *records, records[-1]]
    try:
        expected = [singletons.add_audit(run, record) for record in repeated]
        before = canonical_bytes(store.inspect(run))
        calls = []
        inspect = store.inspect

        def counted(run_id):
            calls.append(run_id)
            return inspect(run_id)

        monkeypatch.setattr(store, "inspect", counted)
        assert store.add_audits(run, repeated) == expected
        assert calls == [run]
        assert store.add_audits(run, repeated) == expected
        assert store.list_audit(run) == singletons.list_audit(run) == records
        assert len(audit_rows(store)) == len(records)
        assert canonical_bytes(store.inspect(run)) == before
    finally:
        singletons.close()


@pytest.mark.parametrize("mutation", ["envelope", "identity", "revision", "analysis", "binding"])
def test_invalid_later_record_rejects_entire_batch(batch_store, mutation):
    store, bundle, records = batch_store
    run = bundle["run_manifest"]["run_id"]
    forged = deepcopy(records[-1])
    if mutation == "envelope":
        forged["envelope"]["payload"] = records[0]["envelope"]["payload"]
    elif mutation == "identity":
        forged["record"]["decision"] = "REJECT"
    elif mutation == "analysis":
        stage = deepcopy(bundle["stage_manifests"][0])
        stage["analysis"] = "f" * 64
        stage["id"] = digest("stage-result.v1", {k: v for k, v in stage.items() if k != "id"})
        forged = {"record": stage, "envelope": None}
    else:
        field = "revision_id" if mutation == "revision" else "binding_digest"
        forged["record"][field] = "f" * 64
        forged["record"]["id"] = digest(
            "review-decision.v1", {k: v for k, v in forged["record"].items() if k != "id"}
        )
        forged["envelope"] = sign_record(forged["record"], KEY, "batch-test")
    with pytest.raises(ValueError, match="AUDIT_|RECORD_IDENTITY"):
        store.add_audits(run, [records[0], forged])
    assert not audit_rows(store)


def test_later_sql_failure_rolls_back_prior_inserts(batch_store):
    store, bundle, records = batch_store
    run = bundle["run_manifest"]["run_id"]
    blocked = digest("paper-audit.v1", {"run_id": run, "record": records[1]})
    # The identifier is a locally computed hexadecimal digest, not user SQL.
    store.db.execute(
        "CREATE TEMP TRIGGER reject_audit BEFORE INSERT ON audit_records "
        f"WHEN NEW.id = '{blocked}' BEGIN SELECT RAISE(ABORT, 'injected_failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected_failure"):
        store.add_audits(run, records)
    assert not audit_rows(store)
    store.db.execute("DROP TRIGGER reject_audit")
    assert len(store.add_audits(run, records)) == len(records)
    assert store.list_audit(run) == records


def test_later_immutable_collision_rolls_back_new_record(batch_store):
    store, bundle, records = batch_store
    run = bundle["run_manifest"]["run_id"]
    existing = store.add_audit(run, records[1])
    with store.db:
        store.db.execute("UPDATE audit_records SET body=? WHERE id=?", ("f" * 64, existing))
    before = audit_rows(store)
    with pytest.raises(ValueError, match="AUDIT_IMMUTABLE_COLLISION"):
        store.add_audits(run, records[:2])
    assert audit_rows(store) == before


@pytest.mark.parametrize("artifact", ["source", "bundle", "existing_audit"])
def test_batch_rechecks_source_and_existing_object_hashes(batch_store, artifact):
    store, bundle, records = batch_store
    run = bundle["run_manifest"]["run_id"]
    if artifact == "source":
        sha = bundle["input_manifest"]["artifacts"][0]["sha256"]
    elif artifact == "bundle":
        sha = store.db.execute("SELECT bundle FROM runs WHERE id=?", (run,)).fetchone()[0]
    else:
        existing = store.add_audit(run, records[0])
        sha = store.db.execute("SELECT body FROM audit_records WHERE id=?", (existing,)).fetchone()[
            0
        ]
    before = audit_rows(store)
    (store.root / "objects" / sha[:2] / sha[2:]).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="CORRUPT_CAS_OBJECT"):
        store.add_audits(run, records)
    assert audit_rows(store) == before


def test_batch_unknown_run_and_empty_noop(batch_store):
    store, _, records = batch_store
    assert store.add_audits("not-indexed", []) == []
    with pytest.raises(ValueError, match="AUDIT_RUN_MISSING"):
        store.add_audits("not-indexed", records)
    assert not audit_rows(store)


def test_batch_persists_validated_snapshots_despite_caller_mutation(batch_store, monkeypatch):
    store, bundle, records = batch_store
    run = bundle["run_manifest"]["run_id"]
    expected = deepcopy(records)
    inspect = store.inspect

    def mutate_caller_input(run_id):
        for record in records:
            record["record"]["decision"] = "REJECT"
        return inspect(run_id)

    monkeypatch.setattr(store, "inspect", mutate_caller_input)
    actual = store.add_audits(run, records)
    assert actual == [digest("paper-audit.v1", {"run_id": run, "record": row}) for row in expected]
    assert store.list_audit(run) == expected


def test_reassessment_reads_twice_and_checks_each_subject_before_atomic_batch(
    batch_store, monkeypatch
):
    from proofmap import evidence_adapter

    store, bundle, _ = batch_store
    run = bundle["run_manifest"]["run_id"]
    inspected, assessed = [], []
    inspect, assess = store.inspect, evidence_adapter.assess_binding

    def counted(run_id):
        inspected.append(run_id)
        return inspect(run_id)

    def checked(binding, *args, **kwargs):
        assessed.append(binding.digest)
        return assess(binding, *args, **kwargs)

    monkeypatch.setattr(store, "inspect", counted)
    monkeypatch.setattr(evidence_adapter, "assess_binding", checked)
    result = reassess(
        bundle, store, profile().to_dict(), {"schema_version": "2.0", "keys": []}, TIME
    )
    assert inspected == [run, run]
    assert assessed == [row["binding"]["id"] for row in bundle["formalizations"]]
    assert len(result["records"]) == 2 and len(result["assessment_records"]) == 18
    assert result["counts"]["verified"] == result["counts"]["accepted"] == 0
    assert len(store.list_audit(run)) == 20


def test_later_assessment_failure_cannot_publish_partial_reassessment(batch_store, monkeypatch):
    from proofmap import evidence_adapter

    store, bundle, _ = batch_store
    assess = evidence_adapter.assess_binding
    called = []

    def fail_second(binding, *args, **kwargs):
        called.append(binding.digest)
        if len(called) == 2:
            raise ValueError("injected_later_assessment_failure")
        return assess(binding, *args, **kwargs)

    monkeypatch.setattr(evidence_adapter, "assess_binding", fail_second)
    with pytest.raises(ValueError, match="injected_later_assessment_failure"):
        reassess(bundle, store, profile().to_dict(), {"schema_version": "2.0", "keys": []}, TIME)
    assert len(called) == 2
    assert not audit_rows(store)
