"""C09 artifacts retain imperfect measured analysis and reject false coverage."""

from copy import deepcopy

import pytest

from proofmap.integrity import write_json
from scripts.check_alpha_acceptance import _artifact


@pytest.fixture
def measured_corpus(baseline_paper_corpus):
    return baseline_paper_corpus


def _check(tmp_path, value):
    path = tmp_path / "benchmark.json"
    write_json(path, value)
    _artifact("benchmark", path, {})


def test_complete_measured_corpus_preserves_imperfect_advisory_metrics(tmp_path, measured_corpus):
    value = deepcopy(measured_corpus)
    semantic = next(
        r
        for r in value["results"]
        if "recorded" in r["measurement_provenance"].get("execution", "").lower()
    )
    assert semantic["candidate_dependencies"]["precision"] == 0.5
    assert semantic["fidelity_agreement"]["sample_size"] == 2
    assert semantic["replay_results"]["sample_size"] == 2
    _check(tmp_path, value)
    assert value == measured_corpus
    assert value["totals"]["verification_execution"] == "NOT_RUN"
    assert value["totals"]["authenticated_fidelity_reviews"] == 0


@pytest.mark.parametrize("dimension", ["assertions", "roles", "explicit_dependencies"])
@pytest.mark.parametrize("mutation", ["false_positive", "false_negative", "invalid_count", "ratio"])
def test_measured_benchmark_mismatches_remain_invalid(
    tmp_path, measured_corpus, dimension, mutation
):
    value = deepcopy(measured_corpus)
    score = value["results"][0][dimension]
    if mutation == "false_positive":
        score["predicted"] += 1
    elif mutation == "false_negative":
        score["labelled"] += 1
    elif mutation == "invalid_count":
        score["true_positive"] = True
    else:
        score["precision"] = None
    with pytest.raises(ValueError, match="BENCHMARK_LABEL"):
        _check(tmp_path, value)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_fixture",
        "duplicate_fixture",
        "stale_revision",
        "category_deleted",
        "category_description",
        "stratum_ratio",
        "zero_denominator",
        "advisory_as_proof",
        "review_authority",
        "unknown_population",
        "reuse_without_execution",
        "historical_mutation",
        "unresolved_overcount",
        "resource_memory_claim",
        "false_hard_block",
        "missing_semantic_observation",
        "semantic_ratio",
    ],
)
def test_incomplete_or_fabricated_c09_evidence_is_rejected(tmp_path, measured_corpus, mutation):
    value = deepcopy(measured_corpus)
    semantic = next(
        r for r in value["results"] if r["fixture"] == "heldout/semantic_interpretations.tex"
    )
    revised = next(r for r in value["results"] if r["fixture"] == "revision_after")
    first = value["results"][0]
    if mutation == "missing_fixture":
        value["results"].pop()
    elif mutation == "duplicate_fixture":
        value["results"][1] = deepcopy(first)
    elif mutation == "stale_revision":
        first["revision"] = "0" * 64
    elif mutation == "category_deleted":
        value["categories"].pop()
    elif mutation == "category_description":
        value["categories"][0]["description"] = "Narrower category"
    elif mutation == "stratum_ratio":
        value["strata"]["split"][0]["assertions"]["macro_recall"] = 0
    elif mutation == "zero_denominator":
        semantic["candidate_dependencies"]["sample_size"] = 0
    elif mutation == "advisory_as_proof":
        semantic["verification"]["execution"] = "VERIFIED"
    elif mutation == "review_authority":
        semantic["measurement_provenance"]["authenticated_human_reviews"] = 2
    elif mutation == "unknown_population":
        value["population_accuracy"]["value"] = 1
    elif mutation == "reuse_without_execution":
        revised["measurement_provenance"]["completed_stages"] = []
    elif mutation == "historical_mutation":
        revised["measurement_provenance"]["historical_run_immutable_after_rebuild"] = False
    elif mutation == "unresolved_overcount":
        source = first["unresolved_region_coverage"]["sources"][0]
        source["unresolved"] = source["indexed"] + 1
    elif mutation == "resource_memory_claim":
        first["resources"]["peak_memory_bytes"] = 1
    elif mutation == "false_hard_block":
        first["false_hard_blocks"]["predicted"] = 1
    elif mutation == "missing_semantic_observation":
        semantic["analysis_observations"] = None
    elif mutation == "semantic_ratio":
        semantic["candidate_dependencies"]["precision"] = 1
    with pytest.raises(ValueError, match="BENCHMARK_"):
        _check(tmp_path, value)
