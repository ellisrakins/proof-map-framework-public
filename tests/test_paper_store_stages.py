from copy import deepcopy
from pathlib import Path

import pytest

from proofmap.integrity import canonical_bytes, digest
from proofmap.paper import ci
from proofmap.paper_store import PaperStore


def stage_args():
    return {
        "revision": "a" * 64,
        "analysis": "b" * 64,
        "stage": "parsing",
        "inputs": {"source": "c" * 64},
        "implementation": "parser-test-v1",
    }


def stage_output():
    return {
        "$schema": "urn:proofmap:document-ir:1",
        "schema_version": "1.0",
        "revision": "a" * 64,
        "parser": {},
        "elements": [],
        "scopes": [],
        "references": [],
        "findings": [],
        "fidelity": "NOT_REVIEWED",
        "status": "PASS",
    }


def test_stage_interruption_resume_and_no_duplicate_events(tmp_path):
    store = PaperStore(tmp_path)
    output = stage_output()
    manifest = store.commit_stage(**stage_args(), output=output)
    assert store.commit_stage(**stage_args(), output=output) == manifest
    assert store.load_stage(**stage_args()) == {"manifest": manifest, "output": output}
    assert store.db.execute("SELECT count(*) FROM stages").fetchone()[0] == 1
    store.close()
    store = PaperStore(tmp_path)
    assert store.load_stage(**stage_args())["output"] == output
    store.close()


@pytest.mark.parametrize("field", ["revision", "analysis", "implementation", "inputs", "namespace"])
def test_stage_config_and_revision_isolation(tmp_path, field):
    store = PaperStore(tmp_path)
    store.commit_stage(**stage_args(), output=stage_output())
    changed = stage_args()
    changed[field] = {"source": "d" * 64} if field == "inputs" else "d" * 64
    assert store.load_stage(**changed) is None
    store.close()


def test_corrupt_output_and_partial_write_cannot_resume(tmp_path):
    store = PaperStore(tmp_path)
    orphan = store.put(canonical_bytes({"unfinished": True}))
    assert store.load_stage(**stage_args()) is None
    record = store.commit_stage(**stage_args(), output=stage_output())
    sha = record["output_digest"]
    (tmp_path / "objects" / sha[:2] / sha[2:]).write_bytes(b"{}")
    with pytest.raises(ValueError, match="CORRUPT_CAS"):
        store.load_stage(**stage_args())
    assert store.get(orphan)
    store.close()


def test_parent_corruption_checked_and_verdicts_never_cache_hits(tmp_path):
    store = PaperStore(tmp_path)
    parent = store.commit_stage(**stage_args(), output=stage_output())
    args = {**stage_args(), "implementation": "child", "parents": {"parsing": parent["id"]}}
    store.commit_stage(**args, output=stage_output())
    assert store.load_stage(**args)
    store.db.execute("DELETE FROM stages WHERE id=?", (parent["id"],))
    with pytest.raises(ValueError, match="STAGE_PARENT"):
        store.load_stage(**args)
    for outcome in ("ERROR", "UNAVAILABLE", "FAIL"):
        args = {**stage_args(), "implementation": outcome}
        store.commit_stage(**args, output=stage_output(), outcome=outcome)
        assert store.load_stage(**args) is None
    args = {**stage_args(), "stage": "verification"}
    store.commit_stage(**args, output={"verified": True})
    assert store.load_stage(**args) is None
    store.close()


def test_immutable_stage_collision_and_invalid_record(tmp_path):
    store = PaperStore(tmp_path)
    store.commit_stage(**stage_args(), output=stage_output())
    with pytest.raises(ValueError, match="STAGE_IMMUTABLE"):
        store.commit_stage(**stage_args(), output={**stage_output(), "fidelity": "changed"})
    with pytest.raises(ValueError):
        store.commit_stage(**{**stage_args(), "revision": True}, output={})
    with pytest.raises(ValueError):
        store.commit_stage(**stage_args(), output={}, resource_use={"seconds": float("nan")})
    store.close()


def test_bundle_ingestion_checks_schema_sources_and_components(tmp_path):
    fixture = Path("tests/fixtures/papers/train/basic.tex")
    bundle, _ = ci(fixture, tmp_path / "out", tmp_path / "store")
    store = PaperStore(tmp_path / "store")
    changed = deepcopy(bundle)
    changed["run_manifest"]["run_id"] = "new-import"
    changed["assertions"][0]["statement"] = "Forged source assertion"
    with pytest.raises(ValueError, match="STALE_OR_MIXED"):
        store.ingest(fixture.name, changed, {})
    changed["run_manifest"]["bundle_digests"]["assertions"] = digest(
        "paper-bundle-component.v1", changed["assertions"]
    )
    with pytest.raises(ValueError, match="ASSERTION_SOURCE"):
        store.ingest(fixture.name, changed, {})
    with pytest.raises(ValueError, match="SOURCE_ARTIFACT"):
        store.ingest(fixture.name, bundle, {fixture.name: b"forged"})
    store.close()


@pytest.mark.parametrize(
    "changed_field",
    [
        "assertion_id",
        "revision",
        "status",
        "source_locators",
        "binding_locator",
        "context_digest",
        "definition_digest",
        "candidate",
        "binding_candidate",
        "obligation_target",
        "missing_binding",
    ],
)
def test_self_consistently_rehashed_formalization_cross_bindings_rejected(tmp_path, changed_field):
    from proofmap.attempts import FormalObligation
    from proofmap.evidence_records import obligation_identity

    source = tmp_path / "identity.tex"
    source.write_text(
        r"\documentclass{article}\begin{document}\begin{theorem}"
        r"For every $q\in\mathbb{Z}$, \[(q+2)^2=q^2+4q+4\]."
        r"\end{theorem}\end{document}",
        encoding="utf-8",
    )
    bundle, _ = ci(source, tmp_path / "out", tmp_path / "store")
    forged = deepcopy(bundle)
    forged["run_manifest"]["run_id"] = "independent-import"
    row = forged["formalizations"][0]
    binding = row["binding"]
    if changed_field in {"assertion_id", "revision", "context_digest", "definition_digest"}:
        row[changed_field] = "f" * 64
    elif changed_field == "status":
        row["status"] = "UNSUPPORTED"
    elif changed_field == "source_locators":
        row["source_locators"] = []
    elif changed_field == "binding_locator":
        binding["source_locators"][0]["start"] += 1
    elif changed_field == "candidate":
        row["candidate"] = "by rfl"
    elif changed_field == "binding_candidate":
        binding["candidate_digest"] = "f" * 64
    elif changed_field == "obligation_target":
        row["obligation"]["target_node_id"] = "other-claim"
        binding["obligation_digest"] = obligation_identity(
            FormalObligation.from_dict(row["obligation"])
        )
    else:
        row.pop("binding")
    binding["id"] = digest(
        "formalization-binding.v1", {k: v for k, v in binding.items() if k != "id"}
    )
    forged["run_manifest"]["bundle_digests"]["formalizations"] = digest(
        "paper-bundle-component.v1", forged["formalizations"]
    )
    store = PaperStore(tmp_path / "store")
    try:
        with pytest.raises(ValueError, match="FORMALIZATION_|PIPELINE_ASSESSMENT_COUNTS"):
            store.ingest(source.name, forged, {})
        assert len(store.list()) == 1
    finally:
        store.close()


@pytest.mark.parametrize("boundary", ["insert", "load"])
@pytest.mark.parametrize(
    "mutation", ["decision", "payload_type", "invalid_base64", "wrapper_fields"]
)
def test_audit_envelope_must_encode_the_persisted_record(tmp_path, boundary, mutation):
    import os

    from proofmap.evidence_records import FormalizationBinding, ReviewDecision, VerifierProfile
    from proofmap.execution import CHECKER_DIGEST
    from proofmap.trust import sign_record

    source = tmp_path / "identity.tex"
    source.write_text(
        r"\documentclass{article}\begin{document}\begin{theorem}"
        r"For every $q\in\mathbb{Z}$, \[(q+2)^2=q^2+4q+4\]."
        r"\end{theorem}\end{document}",
        encoding="utf-8",
    )
    bundle, _ = ci(source, tmp_path / "out", tmp_path / "store")
    binding = FormalizationBinding.from_dict(bundle["formalizations"][0]["binding"])
    profile = VerifierProfile.create(
        image="sha256:" + "a" * 64,
        platform="linux/amd64",
        lean_sha256="b" * 64,
        library_digest="c" * 64,
        checker_digest=CHECKER_DIGEST,
        acquisition_digest="d" * 64,
    )
    approved = ReviewDecision.create(
        binding=binding,
        profile=profile,
        dimension="formal-fidelity",
        decision="APPROVE",
        reviewer_id="test-reviewer",
    ).to_dict()
    envelope = sign_record(approved, os.urandom(32), "test-reviewer")
    valid = {"record": approved, "envelope": envelope}
    forged = deepcopy(valid)
    if mutation == "decision":
        forged["record"] = ReviewDecision.create(
            binding=binding,
            profile=profile,
            dimension="formal-fidelity",
            decision="REJECT",
            reviewer_id="test-reviewer",
        ).to_dict()
    elif mutation == "payload_type":
        forged["envelope"]["payloadType"] = "application/vnd.proofmap.attempt-receipt.v1+json"
    elif mutation == "invalid_base64":
        forged["envelope"]["payload"] = "!invalid!"
    else:
        forged["unvalidated_decision"] = "APPROVE"
    store = PaperStore(tmp_path / "store")
    run_id = bundle["run_manifest"]["run_id"]
    try:
        ident = store.add_audit(run_id, valid)
        assert store.list_audit(run_id, "ReviewDecision") == [valid]
        if boundary == "insert":
            with pytest.raises(ValueError, match="AUDIT_"):
                store.add_audit(run_id, forged)
            assert store.list_audit(run_id, "ReviewDecision") == [valid]
        else:
            # Even self-consistently rehashed stored data must preserve envelope semantics.
            body = store.put(canonical_bytes(forged))
            new_ident = digest("paper-audit.v1", {"run_id": run_id, "record": forged})
            store.db.execute(
                "UPDATE audit_records SET id=?,body=? WHERE id=?", (new_ident, body, ident)
            )
            with pytest.raises(ValueError, match="AUDIT_"):
                store.list_audit(run_id, "ReviewDecision")
    finally:
        store.close()
