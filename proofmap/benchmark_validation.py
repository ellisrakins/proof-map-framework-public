"""Validate finite-corpus analytical artifacts without granting proof authority."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .benchmark import CATEGORY_IDS, _summary, evaluate_observations
from .integrity import canonical_bytes, load_json
from .paper_sources import acquire

OBSERVED = {
    "candidate_dependencies": "candidate_dependencies",
    "fidelity_agreement": "fidelity_decisions",
    "invalidation_correctness": "invalidation",
    "reuse_correctness": "reuse",
    "replay_results": "replay",
}


def _equal(actual: Any, expected: Any, reason: str) -> None:
    # JSON booleans must not compare equal to integer counts.
    if canonical_bytes(actual) != canonical_bytes(expected):
        raise ValueError(reason)


def _integer(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("BENCHMARK_LABEL_COUNTS")
    return value


def _metric(value: dict[str, Any], labels: int | None, exact: bool = False) -> None:
    predicted = _integer(value["predicted"])
    correct = _integer(value["true_positive"])
    labelled = _integer(value["labelled"])
    available = labels is not None
    if labelled != (labels or 0) or correct > min(predicted, labelled):
        raise ValueError("BENCHMARK_LABEL_COUNTS")
    if exact and (predicted != labelled or correct != labelled):
        raise ValueError("BENCHMARK_LABELS")
    expected = {
        "labels_available": available,
        "false_positive": predicted - correct if available else None,
        "false_negative": labelled - correct if available else None,
        "precision": correct / predicted if available and predicted else None,
        "recall": correct / labelled if labelled else None,
        "precision_denominator": predicted if available else 0,
        "recall_denominator": labelled,
        "precision_reason": None
        if available and predicted
        else "NO_PREDICTIONS"
        if available
        else "NO_INDEPENDENT_LABELS",
        "recall_reason": None
        if labelled
        else "NO_POSITIVE_LABELS"
        if available
        else "NO_INDEPENDENT_LABELS",
    }
    _equal({k: value[k] for k in expected}, expected, "BENCHMARK_LABEL_METRICS")


def _observations(row: dict[str, Any], expected: dict[str, Any]) -> None:
    measured = evaluate_observations(expected, row["analysis_observations"], row["revision"])
    for output, dimension in OBSERVED.items():
        _equal(row[output], measured[dimension], "BENCHMARK_OBSERVATION_METRICS")
    provenance = row["measurement_provenance"]
    if "recorded_semantics" in expected:
        if row["analysis_observations"] is None:
            raise ValueError("BENCHMARK_REQUIRED_MEASUREMENT")
        for dimension in ("candidate_dependencies", "fidelity_agreement", "replay_results"):
            if row[dimension]["execution"] == "NOT_RUN" or row[dimension]["sample_size"] <= 0:
                raise ValueError("BENCHMARK_REQUIRED_MEASUREMENT")
        for key, value in {
            "execution": "RECORDED_ORIGINAL_PROVIDER_FIXTURE",
            "authority": "MODEL_SUGGESTION",
            "replayed": True,
            "independent_fidelity_configuration": True,
            "source_unchanged": True,
            "formal_execution": "NOT_RUN",
            "authenticated_human_reviews": 0,
            "population_accuracy": None,
        }.items():
            _equal(provenance[key], value, "BENCHMARK_ADVISORY_BOUNDARY")
    if "revision_before" in expected:
        if row["analysis_observations"] is None:
            raise ValueError("BENCHMARK_REQUIRED_MEASUREMENT")
        for dimension in ("invalidation_correctness", "reuse_correctness"):
            if row[dimension]["execution"] == "NOT_RUN" or row[dimension]["sample_size"] <= 0:
                raise ValueError("BENCHMARK_REQUIRED_MEASUREMENT")
        for key, value in {
            "execution": "ACTUAL_OFFLINE_PIPELINE_PURE_STAGES",
            "formal_execution": "NOT_RUN",
            "authenticated_human_reviews": 0,
            "accepted_claims": 0,
            "historical_run_immutable_after_rebuild": True,
        }.items():
            _equal(provenance[key], value, "BENCHMARK_REVISION_BOUNDARY")
        stages = provenance["completed_stages"]
        reuse = row["analysis_observations"]["reuse"]
        if not isinstance(stages, list) or len(stages) != len(reuse):
            raise ValueError("BENCHMARK_REVISION_STAGES")
        _equal(
            {stage["label"]: stage["pure_execution"] == "REUSED" for stage in stages},
            reuse,
            "BENCHMARK_REVISION_STAGES",
        )
        for field, execution in (
            ("executed_pure_stages", "EXECUTED"),
            ("reused_pure_stages", "REUSED"),
        ):
            _equal(
                provenance[field],
                sum(s["pure_execution"] == execution for s in stages),
                "BENCHMARK_REVISION_STAGES",
            )
        if provenance["source_revisions"][-1] != row["revision"]:
            raise ValueError("BENCHMARK_STALE_OBSERVATION")


def validate_benchmark(value: dict[str, Any], corpus: Path) -> None:
    """Check source membership, labels, arithmetic, strata, and measured boundaries."""
    golden = load_json(corpus / "golden.json")
    fixtures = golden["fixtures"]
    rows = value["results"]
    if value["schema_version"] != "1.1" or not isinstance(rows, list) or not rows:
        raise ValueError("BENCHMARK_SCHEMA")
    _equal(value["sample_size"], len(fixtures), "BENCHMARK_FIXTURE_INVENTORY")
    _equal(
        [row["fixture"] for row in rows],
        [f["path"] for f in fixtures],
        "BENCHMARK_FIXTURE_INVENTORY",
    )
    for row, expected in zip(rows, fixtures, strict=True):
        manifest, _ = acquire(corpus / expected["path"], expected.get("entrypoint"))
        _equal(row["revision"], manifest.revision, "BENCHMARK_SOURCE_REVISION")
        for field in ("split", "categories", "feature_family", "provenance"):
            _equal(row[field], expected[field], "BENCHMARK_CORPUS_METADATA")
        _equal(
            row["resource_stress"],
            expected.get("resource_stress", False),
            "BENCHMARK_CORPUS_METADATA",
        )
        anchors = row["anchors"]
        if _integer(anchors["valid"]) != _integer(anchors["total"]):
            raise ValueError("BENCHMARK_ANCHORS")
        for dimension, label_field in (
            ("assertions", "assertion_labels"),
            ("roles", "roles"),
            ("explicit_dependencies", "dependencies"),
            ("symbol_bindings", "symbol_bindings"),
            ("inference_alternatives", "inference_alternatives"),
            ("exact_identities", "exact_identities"),
        ):
            count = len(expected[label_field]) if label_field in expected else None
            _metric(row[dimension], count, exact=count is not None)
        _metric(row["formalization"]["labels"], len(expected["formalization_status"]), exact=True)
        _equal(
            row["formalization"]["supported"],
            expected["supported_formalizations"],
            "BENCHMARK_FORMALIZATION",
        )
        _equal(
            row["formalization"]["labelled_supported"],
            expected["supported_formalizations"],
            "BENCHMARK_FORMALIZATION",
        )
        selected = _integer(row["formalization"]["selected_claims"])
        _equal(row["formalization"]["coverage_denominator"], selected, "BENCHMARK_FORMALIZATION")
        _equal(
            row["formalization"]["coverage_fraction"],
            row["formalization"]["supported"] / selected if selected else None,
            "BENCHMARK_FORMALIZATION",
        )
        _metric(row["proof_associations"], len(expected["proof_targets"]), exact=True)
        _equal(
            row["proof_associations"]["total_proofs"],
            expected["proof_count"],
            "BENCHMARK_PROOF_TARGETS",
        )
        _equal(row["verification"]["execution"], "NOT_RUN", "BENCHMARK_EXECUTION_BOUNDARY")
        _equal(row["verification"]["verified"], 0, "BENCHMARK_EXECUTION_BOUNDARY")
        _equal(
            row["verification"]["supported_obligations"],
            row["formalization"]["supported"],
            "BENCHMARK_EXECUTION_BOUNDARY",
        )
        finding_labels = expected.get("finding_labels")
        finding_count = (
            sum(finding_labels.values())
            if finding_labels is not None
            else len(expected["finding_codes"])
            if "finding_codes" in expected
            else None
        )
        _metric(row["finding_precision"], finding_count)
        if finding_labels is not None:
            codes = set(row["source_finding_codes"])
            actual = sum((code in codes) == present for code, present in finding_labels.items())
            _equal(
                row["finding_precision"]["accuracy"],
                actual / len(finding_labels) if finding_labels else None,
                "BENCHMARK_FINDING_METRICS",
            )
            _equal(
                row["finding_precision"]["accuracy_denominator"],
                len(finding_labels),
                "BENCHMARK_FINDING_METRICS",
            )
        _metric(row["false_hard_blocks"], len(expected["hard_block_codes"]), exact=True)
        blocks = row["false_hard_blocks"]
        _equal(
            blocks["false_hard_block_count"], blocks["false_positive"], "BENCHMARK_FINDING_METRICS"
        )
        denominator = _integer(blocks["judged_findings"])
        _equal(
            blocks["false_hard_block_fraction"],
            blocks["false_positive"] / denominator if denominator else None,
            "BENCHMARK_FINDING_METRICS",
        )
        _observations(row, expected)
        for source in row["unresolved_region_coverage"]["sources"]:
            total, unresolved = _integer(source["indexed"]), _integer(source["unresolved"])
            if unresolved > total:
                raise ValueError("BENCHMARK_UNRESOLVED_COVERAGE")
            _equal(source["denominator"], total, "BENCHMARK_UNRESOLVED_COVERAGE")
            _equal(
                source["fraction"],
                unresolved / total if total else None,
                "BENCHMARK_UNRESOLVED_COVERAGE",
            )
            if source["unit"] not in {"bytes", "reconstructed_characters"}:
                raise ValueError("BENCHMARK_UNRESOLVED_UNIT")
        elapsed = row["runtime_seconds"]
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("BENCHMARK_RESOURCE_COUNTS")
        for key in ("source_files", "source_bytes", "ir_elements", "findings"):
            _integer(row["resources"][key])
        if (
            row["resources"]["peak_memory_bytes"] is not None
            or not row["resources"]["peak_memory_reason"]
        ):
            raise ValueError("BENCHMARK_RESOURCE_UNKNOWN")

    category_rows = [
        {
            "id": ident,
            "description": golden["categories"][ident],
            **_summary([r for r in rows if ident in r["categories"]]),
        }
        for ident in CATEGORY_IDS
    ]
    if any(row["paper_count"] == 0 for row in category_rows):
        raise ValueError("BENCHMARK_CATEGORY_COVERAGE")
    _equal(value["categories"], category_rows, "BENCHMARK_CATEGORY_METRICS")
    strata = {
        field: [
            {"value": item, **_summary([r for r in rows if r[field] == item])}
            for item in sorted({r[field] for r in rows})
        ]
        for field in ("split", "feature_family")
    }
    _equal(value["strata"], strata, "BENCHMARK_STRATUM_METRICS")
    _equal(
        value["population_accuracy"],
        {
            "value": None,
            "denominator": 0,
            "reason": "FINITE_REGRESSION_CORPUS_NOT_POPULATION_SAMPLE",
        },
        "BENCHMARK_POPULATION_BOUNDARY",
    )
    totals = {
        "authored_assertions": sum(r["authored_assertion_count"] for r in rows),
        "theorem_like_claims": sum(r["theorem_like_claims"] for r in rows),
        "role_labelled": sum(r["roles"]["labelled"] for r in rows),
        "role_correct": sum(r["roles"]["true_positive"] for r in rows),
        "anchors_valid": sum(r["anchors"]["valid"] for r in rows),
        "anchors_total": sum(r["anchors"]["total"] for r in rows),
        "explicit_dependencies": sum(r["explicit_dependencies"]["predicted"] for r in rows),
        "supported_formalizations": sum(r["formalization"]["supported"] for r in rows),
        "verified_obligations": 0,
        "verification_execution": "NOT_RUN",
        "candidate_dependencies": sum(r["candidate_dependencies"]["observed"] for r in rows),
        "fidelity_decisions": sum(r["fidelity_agreement"]["observed"] for r in rows),
        "fidelity_decision_authority": "ADVISORY_RECORDED_PROVIDER_OUTPUT",
        "authenticated_fidelity_reviews": 0,
    }
    _equal(value["totals"], totals, "BENCHMARK_TOTALS")
