"""Independent regression labels and failure-sensitive analytical measurements."""

from pathlib import Path

import pytest

from proofmap.benchmark import (
    CATEGORY_IDS,
    benchmark,
    evaluate_observations,
    score,
    unresolved_coverage,
)
from proofmap.integrity import load_json, write_json

CORPUS = Path("tests/fixtures/papers")


def test_unlabelled_and_labelled_empty_truth_are_distinct():
    unknown = score({"unexpected"}, None)
    assert unknown["precision"] is None
    assert unknown["precision_denominator"] == 0
    assert unknown["precision_reason"] == "NO_INDEPENDENT_LABELS"
    labelled_empty = score({"unexpected"}, set())
    assert labelled_empty["precision"] == 0
    assert labelled_empty["false_positive"] == 1
    assert labelled_empty["recall"] is None
    assert labelled_empty["recall_reason"] == "NO_POSITIVE_LABELS"


def test_corpus_has_independent_labels_provenance_and_category_strata(baseline_paper_corpus):
    golden = load_json(CORPUS / "golden.json")
    result = baseline_paper_corpus
    assert result["sample_size"] == len(golden["fixtures"])
    assert {row["id"] for row in result["categories"]} == set(CATEGORY_IDS)
    assert {row["value"] for row in result["strata"]["split"]} == {"train", "heldout"}
    for row in result["results"]:
        assert row["provenance"]["evaluation_only"] is True
        assert row["provenance"]["permission"]
        assert row["assertions"]["true_positive"] == row["assertions"]["labelled"]
        assert row["roles"]["true_positive"] == row["roles"]["labelled"]
        assert (
            row["explicit_dependencies"]["true_positive"]
            == row["explicit_dependencies"]["labelled"]
        )
        assert (
            row["proof_associations"]["true_positive"] == row["proof_associations"]["total_proofs"]
        )
        assert row["anchors"]["valid"] == row["anchors"]["total"]
        assert row["verification"]["execution"] == "NOT_RUN"
        if row["fidelity_agreement"]["execution"] == "NOT_RUN":
            assert row["fidelity_agreement"]["accuracy"] is None
            assert row["fidelity_agreement"]["accuracy_reason"] == "NOT_RUN"
        assert row["resources"]["source_bytes"] > 0
        assert row["false_hard_blocks"]["false_hard_block_count"] == 0
        if "accuracy" in row["finding_precision"]:
            assert row["finding_precision"]["accuracy"] == 1
        formal_labels = row["formalization"]["labels"]
        if formal_labels["labels_available"]:
            assert formal_labels["true_positive"] == formal_labels["labelled"], row["fixture"]
        assert row["formalization"]["supported"] == row["formalization"]["labelled_supported"]
        exact = row["exact_identities"]
        if exact["labels_available"]:
            assert exact["true_positive"] == exact["labelled"], row["fixture"]
        alternatives = row["inference_alternatives"]
        if alternatives["labels_available"]:
            assert alternatives["true_positive"] == alternatives["labelled"], row["fixture"]
    scope = next(row for row in result["results"] if row["fixture"] == "train/scope_bindings.tex")
    assert scope["symbol_bindings"]["labelled"] == 4
    assert scope["symbol_bindings"]["accuracy"] == 1
    assert next(row for row in result["results"] if row["fixture"] == "train/long_context.tex")[
        "resource_stress"
    ]
    adapted = next(
        row for row in result["results"] if row["fixture"] == "heldout/agoh_synthetic.tex"
    )
    assert adapted["provenance"]["origin"] == "synthetic_adaptation"
    assert "not Agoh's original source" in adapted["provenance"]["scope"]
    semantic = next(
        row for row in result["results"] if row["fixture"] == "heldout/semantic_interpretations.tex"
    )
    assert semantic["candidate_dependencies"]["precision"] == 0.5
    assert semantic["candidate_dependencies"]["recall"] == 1
    assert semantic["fidelity_agreement"]["sample_size"] == 2
    assert semantic["fidelity_agreement"]["accuracy"] == 1
    assert semantic["replay_results"]["accuracy"] == 1
    assert semantic["measurement_provenance"]["replayed"] is True
    assert semantic["measurement_provenance"]["authenticated_human_reviews"] == 0
    revised = next(row for row in result["results"] if row["fixture"] == "revision_after")
    assert revised["invalidation_correctness"]["accuracy"] == 1
    assert revised["reuse_correctness"]["accuracy"] == 1
    assert revised["measurement_provenance"]["executed_pure_stages"] == 1
    assert revised["measurement_provenance"]["reused_pure_stages"] == 1
    assert revised["measurement_provenance"]["historical_run_immutable_after_rebuild"] is True


def test_strata_expose_a_small_failure_hidden_by_stress_counts(tmp_path):
    fixtures = []
    for filename, size, stress in (("stress.tex", 20, True), ("small.tex", 1, False)):
        labels = [f"item:{i}" for i in range(size)]
        (tmp_path / filename).write_text(
            "\\begin{document}"
            + "".join(
                rf"\begin{{remark}}\label{{{label}}}Original fixture text.\end{{remark}}"
                for label in labels
            )
            + "\\end{document}",
            encoding="utf-8",
        )
        truth = labels if stress else ["deliberately-missing-label"]
        fixtures.append(
            {
                "path": filename,
                "split": "train",
                "assertion_labels": truth,
                "roles": {label: "REMARK" for label in truth},
                "proof_count": 0,
                "dependencies": [],
                "resource_stress": stress,
                "categories": ["F07"],
            }
        )
    write_json(tmp_path / "golden.json", {"fixtures": fixtures})
    result = benchmark(tmp_path)
    summary = next(row for row in result["categories"] if row["id"] == "F07")
    assert summary["assertions"]["micro_recall"] == pytest.approx(20 / 21)
    assert summary["assertions"]["macro_recall"] == 0.5
    assert summary["assertions"]["macro_recall_denominator"] == 2
    assert summary["resource_stress_papers"] == 1


def test_measured_events_compare_to_labels_without_promoting_proof():
    labels = {
        "evaluation_labels": {
            "candidate_dependencies": [["a", "b"], ["c", "b"]],
            "fidelity_decisions": {"candidate": "AGREE"},
            "invalidation": {"a": True, "b": False},
            "reuse": {"a": False, "b": True},
            "replay": {"formal-subject": "VERIFIED"},
        }
    }
    observations = {
        "revision": "r1",
        "candidate_dependencies": [["a", "b"], ["x", "b"]],
        "fidelity_decisions": {"candidate": "DISAGREE"},
        "invalidation": {"a": True, "b": False},
        "reuse": {"a": False, "b": False},
        "replay": {"formal-subject": "UNAVAILABLE"},
    }
    result = evaluate_observations(labels, observations, "r1")
    assert result["candidate_dependencies"]["precision"] == 0.5
    assert result["candidate_dependencies"]["recall"] == 0.5
    assert result["fidelity_decisions"]["accuracy"] == 0
    assert result["invalidation"]["accuracy"] == 1
    assert result["reuse"]["accuracy"] == 0.5
    assert result["replay"]["accuracy"] == 0
    assert all(row["execution"] == "OBSERVED_ANALYSIS_NOT_PROOF" for row in result.values())


def test_recorded_fidelity_mistake_is_measured_without_network_or_acceptance(monkeypatch):
    from copy import deepcopy

    from proofmap.benchmark_scenarios import semantic_replay
    from proofmap.paper_sources import acquire, parse

    def no_network(*args, **kwargs):
        raise AssertionError("The recorded benchmark must never call a model endpoint")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    expected = next(
        row
        for row in load_json(CORPUS / "golden.json")["fixtures"]
        if row["path"] == "heldout/semantic_interpretations.tex"
    )
    manifest, files = acquire(CORPUS / expected["path"])
    ir = parse(manifest, files)
    specification = deepcopy(expected["recorded_semantics"])
    specification["fidelity_verdicts"]["missing-hypothesis"] = "AGREE"
    actual = semantic_replay(ir, specification)
    measured = evaluate_observations(expected, actual["observations"], ir["revision"])
    assert measured["fidelity_decisions"]["accuracy"] == 0.5
    assert measured["fidelity_decisions"]["false_positive"] == 1
    assert actual["provenance"]["authority"] == "MODEL_SUGGESTION"
    assert actual["provenance"]["formal_execution"] == "NOT_RUN"


@pytest.mark.parametrize("change", ["revision", "authority", "boolean", "duplicate"])
def test_stale_or_forged_measurement_records_are_rejected(change):
    record = {"revision": "r1", "reuse": {"independent": True}}
    if change == "revision":
        record["revision"] = "different-source"
    elif change == "authority":
        record["accepted"] = True
    elif change == "boolean":
        record["reuse"] = {"independent": 1}
    else:
        record["candidate_dependencies"] = [["a", "b"], ["a", "b"]]
    with pytest.raises(ValueError, match="BENCHMARK_"):
        evaluate_observations({}, record, "r1")


def test_unresolved_region_intervals_do_not_double_count_nested_source():
    def element(kind, start, end):
        return {
            "kind": kind,
            "locator": {"artifact": "paper.tex", "format": "tex", "start": start, "end": end},
        }

    measured = unresolved_coverage(
        {
            "elements": [
                element("ASSERTION", 0, 100),
                element("PROSE", 10, 30),
                element("UNSUPPORTED_MACRO", 25, 35),
            ]
        }
    )
    source = measured["sources"][0]
    assert source["indexed"] == 100
    assert source["unresolved"] == 25
    assert source["fraction"] == 0.25
    assert source["unit"] == "bytes"


def test_duplicate_or_escaped_fixture_inventory_is_rejected(tmp_path):
    fixture = {
        "path": "paper.tex",
        "split": "train",
        "assertion_labels": [],
        "proof_count": 0,
        "dependencies": [],
    }
    write_json(tmp_path / "golden.json", {"fixtures": [fixture, fixture]})
    with pytest.raises(ValueError, match="DUPLICATE_FIXTURE"):
        benchmark(tmp_path)
    write_json(tmp_path / "golden.json", {"fixtures": [{**fixture, "path": "../outside.tex"}]})
    with pytest.raises(ValueError):
        benchmark(tmp_path)
