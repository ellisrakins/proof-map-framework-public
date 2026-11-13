from copy import deepcopy
from pathlib import Path

import pytest

from proofmap.integrity import canonical_bytes, digest, load_json, write_json
from proofmap.paper import ci, diff, load_bundle, review_apply, review_export
from proofmap.paper_store import PaperStore

FIXTURE = Path("tests/fixtures/papers/train/basic.tex")


def test_repeat_run_has_identical_scientific_subjects(tmp_path):
    first, _ = ci(FIXTURE, tmp_path / "first", tmp_path / "store")
    second, _ = ci(FIXTURE, tmp_path / "second", tmp_path / "store")
    assert first["run_manifest"]["run_id"] != second["run_manifest"]["run_id"]
    assert first["run_manifest"]["analysis_digest"] == second["run_manifest"]["analysis_digest"]
    scientific = first.keys() - {"run_manifest", "revision_plan"}
    assert {key: first["run_manifest"]["bundle_digests"][key] for key in scientific} == {
        key: second["run_manifest"]["bundle_digests"][key] for key in scientific
    }
    for key in scientific:
        assert first[key] == second[key]
    assert first["revision_plan"]["parent_run"] is None
    assert second["revision_plan"]["parent_run"] == first["run_manifest"]["run_id"]
    assert [row["fingerprint"] for row in first["revision_plan"]["rows"]] == [
        row["fingerprint"] for row in second["revision_plan"]["rows"]
    ]
    assert canonical_bytes(load_bundle(tmp_path / "first")) == canonical_bytes(first)


def test_mixed_bundle_and_self_consistent_forged_review_rejected(tmp_path):
    bundle, _ = ci(FIXTURE, tmp_path / "out", tmp_path / "store")
    assessment_path = tmp_path / "out" / "assessment.json"
    assessment = load_json(assessment_path)
    assessment["outcomes"]["kernel_verification"] = "PASS"
    write_json(assessment_path, assessment)
    with pytest.raises(ValueError, match="STALE_OR_MIXED"):
        load_bundle(tmp_path / "out")
    forged = deepcopy(bundle)
    forged["assertions"][0]["statement"] = "Forged assertion"
    store = PaperStore(tmp_path / "store")
    try:
        with pytest.raises(ValueError, match="immutable"):
            review_apply(forged, review_export(forged, "Attacker"), store)
        review = review_export(bundle, "Reviewer")
        review["decisions"].append(review["decisions"][0])
        with pytest.raises(ValueError, match="REVIEW_TARGET"):
            review_apply(bundle, review, store)
    finally:
        store.close()


def test_index_config_isolation_rebuild_and_run_collision(tmp_path):
    bundle, _ = ci(FIXTURE, tmp_path / "one", tmp_path / "store")
    ci(
        FIXTURE,
        tmp_path / "two",
        tmp_path / "store",
        config={"exact_checks": [{"label": "eq:one", "left": "1+1", "right": "3"}]},
    )
    store = PaperStore(tmp_path / "store")
    try:
        # Same configuration can produce different model findings on another run.
        variant = deepcopy(bundle)
        variant["run_manifest"]["run_id"] = "independent-run"
        variant["findings"].append({"code": "INDEPENDENT_RUN_FINDING"})
        variant["run_manifest"]["bundle_digests"]["findings"] = digest(
            "paper-bundle-component.v1", variant["findings"]
        )
        store.ingest(FIXTURE.name, variant, {})
        before = list(store.db.execute("SELECT * FROM entities ORDER BY revision,id,kind"))
        assert len(store.list()) == 3
        store.rebuild()
        assert list(store.db.execute("SELECT * FROM entities ORDER BY revision,id,kind")) == before
        changed = deepcopy(bundle)
        changed["findings"].append({"code": "FAKE"})
        with pytest.raises(ValueError, match="Run ID collision"):
            store.ingest(FIXTURE.name, changed, {})
    finally:
        store.close()


def test_bad_model_schema_preserves_partial_bundle(tmp_path, monkeypatch):
    def bad_model(*args, **kwargs):
        from proofmap.extractor import validate_response

        return validate_response({"command": "FORGE_PROOF"}, {})

    monkeypatch.setattr("proofmap.paper.extract", bad_model)
    bundle, code = ci(
        FIXTURE,
        tmp_path / "out",
        tmp_path / "store",
        extractor="configured",
        config={"extractor": {}},
    )
    assert code == 3
    assert bundle["assertions"]
    assert any(f["code"] == "EXTRACTOR_ERROR" for f in bundle["findings"])
    assert canonical_bytes(load_bundle(tmp_path / "out")) == canonical_bytes(bundle)


def test_triplicate_labels_never_become_a_unique_revision_match(tmp_path):
    source = tmp_path / "ambiguous.tex"
    source.write_text(
        r"\documentclass{article}\begin{document}"
        + r"\begin{theorem}\label{duplicate}One.\end{theorem}" * 3
        + r"\end{document}"
    )
    bundle, _ = ci(source, tmp_path / "out", tmp_path / "store")
    assert all(row["label"] != "duplicate" for row in diff(bundle, bundle)["changes"])


def test_handwritten_benchmark_has_real_counts_and_unknowns(baseline_paper_corpus):
    result = baseline_paper_corpus
    assert result["sample_size"] == len(
        load_json(Path("tests/fixtures/papers/golden.json"))["fixtures"]
    )
    assert len({r["feature_family"] for r in result["results"] if r["split"] == "heldout"}) >= 4
    assert result["totals"]["supported_formalizations"] >= 8
    assert result["totals"]["verification_execution"] == "NOT_RUN"
    assert {row["split"] for row in result["results"]} == {"train", "heldout"}
    for row in result["results"]:
        assert row["assertions"]["true_positive"] == row["assertions"]["labelled"]
        assert row["anchors"]["valid"] == row["anchors"]["total"] > 0
        if row["fidelity_agreement"]["execution"] == "NOT_RUN":
            assert row["fidelity_agreement"]["accuracy"] is None
        else:
            assert row["measurement_provenance"]["authority"] == "MODEL_SUGGESTION"
