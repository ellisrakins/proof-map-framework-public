"""Stratified, independently labelled regression evaluation, never proof acceptance."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any

from .formalize import THEOREM_ROLES, formalize_document
from .integrity import load_json, relative_path
from .paper import assertion_layer
from .paper_sources import LocatorValidationSession, acquire, parse, validate_locator

CATEGORY_IDS = tuple(f"F{i:02d}" for i in range(1, 13))
OBSERVATION_METRICS = (
    "candidate_dependencies",
    "fidelity_decisions",
    "invalidation",
    "reuse",
    "replay",
)


def score(found: set[Any], truth: set[Any] | None) -> dict[str, Any]:
    """Absent labels and a labelled empty truth set have different meanings."""
    labelled = truth is not None
    correct = len(found & truth) if truth is not None else 0
    count = len(truth) if truth is not None else 0
    return {
        "precision": correct / len(found) if labelled and found else None,
        "recall": correct / count if count else None,
        "predicted": len(found),
        "labelled": count,
        "true_positive": correct,
        "false_positive": len(found) - correct if labelled else None,
        "false_negative": count - correct if labelled else None,
        "labels_available": labelled,
        "precision_denominator": len(found) if labelled else 0,
        "recall_denominator": count,
        "precision_reason": None
        if labelled and found
        else "NO_PREDICTIONS"
        if labelled
        else "NO_INDEPENDENT_LABELS",
        "recall_reason": None
        if count
        else "NO_POSITIVE_LABELS"
        if labelled
        else "NO_INDEPENDENT_LABELS",
    }


def _items(value: Any, name: str) -> set[Any]:
    if name == "candidate_dependencies":
        if not isinstance(value, list) or any(
            not isinstance(pair, list)
            or len(pair) != 2
            or any(not isinstance(part, str) or not part for part in pair)
            for pair in value
        ):
            raise ValueError("BENCHMARK_DEPENDENCY_LABELS")
        result = {tuple(pair) for pair in value}
        if len(result) != len(value):
            raise ValueError("BENCHMARK_DUPLICATE_OBSERVATION")
        return result
    if not isinstance(value, dict) or any(not isinstance(k, str) or not k for k in value):
        raise ValueError("BENCHMARK_OBSERVATION_LABELS")
    allowed: set[Any] = (
        {True, False}
        if name in {"invalidation", "reuse"}
        else {"AGREE", "DISAGREE", "UNCERTAIN"}
        if name == "fidelity_decisions"
        else {
            "VERIFIED",
            "REJECTED",
            "UNAVAILABLE",
            "REPLAY_MATCH",
            "REPLAY_MISMATCH",
            "BINDING_REJECTED",
            "UNEXPECTED_ACCEPTANCE",
        }
    )
    if any(
        not isinstance(v, (str, bool))
        or v not in allowed
        or (name in {"invalidation", "reuse"} and type(v) is not bool)
        for v in value.values()
    ):
        raise ValueError("BENCHMARK_OBSERVATION_OUTCOME")
    return set(value.items())


def evaluate_observations(
    expected: dict[str, Any], observations: dict[str, Any] | None, revision: str
) -> dict[str, Any]:
    """Compare measured advisory events to labels; never import acceptance authority."""
    labels = expected.get("evaluation_labels", {})
    if set(labels) - set(OBSERVATION_METRICS):
        raise ValueError("BENCHMARK_UNKNOWN_LABEL_DIMENSION")
    if observations is not None:
        if set(observations) - {"revision", *OBSERVATION_METRICS}:
            raise ValueError("BENCHMARK_UNKNOWN_OBSERVATION")
        if observations.get("revision") != revision:
            raise ValueError("BENCHMARK_STALE_OBSERVATION")
    result = {}
    for name in OBSERVATION_METRICS:
        truth = _items(labels[name], name) if name in labels else None
        executed = observations is not None and name in observations
        actual = (
            _items(observations[name], name) if executed and observations is not None else set()
        )
        row = score(actual, truth)
        if not executed:
            row.update(
                precision=None,
                recall=None,
                precision_denominator=0,
                recall_denominator=0,
                precision_reason="NOT_RUN",
                recall_reason="NOT_RUN",
            )
        row.update(
            execution="OBSERVED_ANALYSIS_NOT_PROOF" if executed else "NOT_RUN",
            observed=len(actual),
            sample_size=len(truth) if executed and truth is not None else 0,
            accuracy=len(actual & truth) / len(truth) if executed and truth else None,
            accuracy_reason=None
            if executed and truth
            else "NOT_RUN"
            if not executed
            else "NO_INDEPENDENT_LABELS"
            if truth is None
            else "NO_LABELS",
        )
        result[name] = row
    return result


def _span_size(intervals: list[tuple[int, int]]) -> int:
    total, end = 0, -1
    for start, stop in sorted(intervals):
        if stop > end:
            total += stop - max(start, end)
            end = stop
    return total


def unresolved_coverage(ir: dict[str, Any]) -> dict[str, Any]:
    """Measure unique indexed source intervals, not invented semantic accuracy."""
    spans: dict[tuple[str, str, int | None], dict[str, list[tuple[int, int]]]] = {}
    unresolved = 0
    for element in ir["elements"]:
        loc = element["locator"]
        is_unresolved = (
            element["kind"]
            in {"PROSE", "UNPARSED_SOURCE", "UNSUPPORTED_ENVIRONMENT", "UNSUPPORTED_MACRO"}
            or element.get("binding_status") == "UNRESOLVED"
        )
        unresolved += int(is_unresolved)
        is_tex = loc["format"] == "tex"
        start, end = (
            (loc.get("start"), loc.get("end"))
            if is_tex
            else (loc.get("text_start"), loc.get("text_end"))
        )
        if type(start) is not int or type(end) is not int:
            continue
        key = (loc["artifact"], "bytes" if is_tex else "reconstructed_characters", loc.get("page"))
        group = spans.setdefault(key, {"indexed": [], "unresolved": []})
        group["indexed"].append((start, end))
        if is_unresolved:
            group["unresolved"].append((start, end))
    sources = []
    for (artifact, unit, page), intervals in sorted(spans.items(), key=lambda item: str(item[0])):
        total, count = _span_size(intervals["indexed"]), _span_size(intervals["unresolved"])
        sources.append(
            {
                "artifact": artifact,
                "page": page,
                "unit": unit,
                "indexed": total,
                "unresolved": count,
                "fraction": count / total if total else None,
                "denominator": total,
                "reason": None if total else "NO_INDEXED_INTERVALS",
            }
        )
    return {
        "scope": "Syntax limitations and uninterpreted prose; not mathematical accuracy.",
        "unresolved_elements": unresolved,
        "indexed_elements": len(ir["elements"]),
        "sources": sources,
    }


def _symbol_bindings(ir: dict[str, Any], by_id: dict[str, Any]) -> set[tuple[Any, ...]]:
    counters: Counter[tuple[str, str | None]] = Counter()
    result = set()
    for element in ir["elements"]:
        if element["kind"] != "SYMBOL_OCCURRENCE":
            continue
        owner = element.get("owner")
        seen = set()
        label = None
        while owner in by_id and owner not in seen:
            seen.add(owner)
            record = by_id[owner]
            if len(record["labels"]) == 1:
                label = record["labels"][0]
                break
            owner = record.get("owner") or record.get("proof_for")
        key = (element["symbol"], label)
        ordinal = counters[key]
        counters[key] += 1
        definition = by_id.get(element.get("definition"), {})
        result.add(
            (
                element["symbol"],
                label,
                ordinal,
                definition.get("text"),
                element.get("binding_status", "UNRESOLVED"),
            )
        )
    return result


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {
        "paper_count": len(rows),
        "fixtures": [row["fixture"] for row in rows],
        "resource_stress_papers": sum(row["resource_stress"] for row in rows),
        "authored_assertions": sum(row["authored_assertion_count"] for row in rows),
        "anchors_valid": sum(row["anchors"]["valid"] for row in rows),
        "anchors_total": sum(row["anchors"]["total"] for row in rows),
    }
    for metric in (
        "assertions",
        "roles",
        "explicit_dependencies",
        "symbol_bindings",
        "inference_alternatives",
        "exact_identities",
        "candidate_dependencies",
        "fidelity_agreement",
        "finding_precision",
        "false_hard_blocks",
        "invalidation_correctness",
        "reuse_correctness",
        "replay_results",
    ):
        labelled = [
            row[metric]
            for row in rows
            if row[metric]["labels_available"] and row[metric].get("execution") != "NOT_RUN"
        ]
        result: dict[str, Any] = {
            "labelled_papers": len(labelled),
            "predicted": sum(r["predicted"] for r in labelled),
            "labelled": sum(r["labelled"] for r in labelled),
            "true_positive": sum(r["true_positive"] for r in labelled),
        }
        for name, denominator in (("precision", "predicted"), ("recall", "labelled")):
            count = result[denominator]
            samples = [r[name] for r in labelled if r[name] is not None]
            result["micro_" + name] = result["true_positive"] / count if count else None
            result["macro_" + name] = sum(samples) / len(samples) if samples else None
            result[name + "_denominator"] = count
            result["macro_" + name + "_denominator"] = len(samples)
            result[name + "_reason"] = None if count else "NO_LABELLED_DENOMINATOR"
        values[metric] = result
    return values


def benchmark(corpus: Path, observations: dict[str, Any] | None = None) -> dict[str, Any]:
    golden = load_json(corpus / "golden.json")
    fixtures = golden["fixtures"]
    if not isinstance(fixtures, list) or not 1 <= len(fixtures) <= 256:
        raise ValueError("BENCHMARK_FIXTURE_BUDGET")
    paths = [fixture["path"] for fixture in fixtures]
    if len(paths) != len(set(paths)):
        raise ValueError("BENCHMARK_DUPLICATE_FIXTURE")
    observations = observations or {}
    if set(observations) - set(paths):
        raise ValueError("BENCHMARK_UNKNOWN_FIXTURE")
    categories = golden.get("categories", {})
    if categories and set(categories) != set(CATEGORY_IDS):
        raise ValueError("BENCHMARK_CATEGORY_INVENTORY")
    rows = []
    for expected in fixtures:
        relative_path(expected["path"])
        path = (corpus / expected["path"]).resolve()
        if not path.is_relative_to(corpus.resolve()):
            raise ValueError("BENCHMARK_FIXTURE_ESCAPE")
        if expected["split"] not in {"train", "heldout"}:
            raise ValueError("BENCHMARK_SPLIT")
        if set(expected.get("categories", [])) - set(CATEGORY_IDS):
            raise ValueError("BENCHMARK_CATEGORY")
        started = time.monotonic()
        manifest, artifacts = acquire(path, expected.get("entrypoint"))
        ir = parse(manifest, artifacts)
        _, graph = assertion_layer(ir)
        by_id = {e["id"]: e for e in ir["elements"]}
        label_counts = Counter(label for e in ir["elements"] for label in e["labels"])

        def label_for(
            ident: str | None,
            elements: dict[str, Any] = by_id,
            counts: Counter[str] = label_counts,
        ) -> str | None:
            if ident is None:
                return None
            labels: list[str] = elements.get(ident, {}).get("labels", [])
            return labels[0] if len(labels) == 1 and counts[labels[0]] == 1 else None

        predicted = {
            label
            for e in ir["elements"]
            if e["kind"] == "ASSERTION"
            for label in e["labels"]
            if label_counts[label] == 1
        }
        claim_ids = {e["id"] for e in ir["elements"] if e["kind"] == "ASSERTION"}
        predicted_edges = set()
        for reference in ir.get("references", []):
            if reference["kind"] != "REFERENCE" or len(reference["targets"]) != 1:
                continue
            owner = reference.get("owner")
            seen = set()
            while owner in by_id and owner not in claim_ids and owner not in seen:
                seen.add(owner)
                owner = by_id[owner].get("proof_for") or by_id[owner].get("owner")
            target = reference["targets"][0]
            if owner in claim_ids and target in claim_ids and target != owner:
                predicted_edges.add((label_for(target), label_for(owner)))
        roles = {
            (label, e.get("role", "UNRESOLVED"))
            for e in ir["elements"]
            if e["kind"] == "ASSERTION"
            for label in e["labels"]
            if label_counts[label] == 1
        }
        session = LocatorValidationSession()
        for element in ir["elements"]:
            validate_locator(element["locator"], artifacts, element["text"], session=session)
        formalizations = formalize_document(ir)
        supported = sum(row["status"] == "SUPPORTED" for row in formalizations)
        theorem_count = sum(el.get("role") in THEOREM_ROLES for el in ir["elements"])
        proof_targets = [
            label_for(e.get("proof_for")) for e in ir["elements"] if e["kind"] == "PROOF"
        ]
        proof_score = score(
            set(enumerate(proof_targets)),
            set(enumerate(expected["proof_targets"])) if "proof_targets" in expected else None,
        )
        proof_score.update(
            observed=sum(t is not None for t in proof_targets),
            labelled=expected["proof_count"],
            total_proofs=len(proof_targets),
        )
        symbols = score(
            _symbol_bindings(ir, by_id),
            {tuple(item) for item in expected["symbol_bindings"]}
            if "symbol_bindings" in expected
            else None,
        )
        symbols.update(
            accuracy=symbols["recall"],
            accuracy_denominator=symbols["labelled"],
            accuracy_reason=symbols["recall_reason"],
        )
        finding_codes = {f["code"] for f in ir["findings"]}
        findings = score(
            finding_codes, set(expected["finding_codes"]) if "finding_codes" in expected else None
        )
        findings["sample_size"] = findings["labelled"]
        if "finding_labels" in expected:
            judgments = expected["finding_labels"]
            if not isinstance(judgments, dict) or any(
                type(v) is not bool for v in judgments.values()
            ):
                raise ValueError("BENCHMARK_FINDING_LABELS")
            findings = score(
                finding_codes & judgments.keys(),
                {code for code, present in judgments.items() if present},
            )
            findings.update(
                sample_size=len(judgments),
                accuracy=sum(
                    (code in finding_codes) == present for code, present in judgments.items()
                )
                / len(judgments)
                if judgments
                else None,
                accuracy_denominator=len(judgments),
                accuracy_reason=None if judgments else "NO_INDEPENDENT_LABELS",
                scope="Independently judged finding codes only.",
                unjudged_findings=sorted(finding_codes - judgments.keys()),
            )
        hard_blocks = {f["code"] for f in ir["findings"] if f.get("blocking_eligible") is True}
        false_blocks = score(
            hard_blocks,
            set(expected["hard_block_codes"]) if "hard_block_codes" in expected else None,
        )
        judged = len(ir["findings"]) if "hard_block_codes" in expected else 0
        false_blocks.update(
            judged_findings=judged,
            false_hard_block_count=false_blocks["false_positive"],
            false_hard_block_fraction=false_blocks["false_positive"] / judged if judged else None,
            fraction_reason=None
            if judged
            else "NO_FINDINGS"
            if "hard_block_codes" in expected
            else "NO_INDEPENDENT_LABELS",
        )
        formal_labels = {label_for(r["assertion_id"]): r["status"] for r in formalizations}
        formal_score = score(
            set(formal_labels.items()),
            set(expected["formalization_status"].items())
            if "formalization_status" in expected
            else None,
        )
        exact_identities = {
            (label_for(r["assertion_id"]), r["exact_check"]["equal"])
            for r in formalizations
            if type(r.get("exact_check", {}).get("equal")) is bool
        }
        alternatives = {
            (
                label_for(i.conclusion),
                tuple(sorted(label_for(p) or "UNLABELLED" for p in i.premises)),
            )
            for i in graph.inferences
        }
        expected_alternatives = {
            (item["conclusion"], tuple(sorted(item["premises"])))
            for item in expected.get("inference_alternatives", [])
        }
        observed = observations.get(expected["path"])
        provenance: dict[str, Any] = {"execution": "NOT_RUN"}
        if observed is None and "recorded_semantics" in expected:
            from .benchmark_scenarios import semantic_replay

            scenario = semantic_replay(ir, expected["recorded_semantics"])
            observed, provenance = scenario["observations"], scenario["provenance"]
        if observed is None and "revision_before" in expected:
            from .benchmark_scenarios import revision_pair

            relative_path(expected["revision_before"])
            prior = (corpus / expected["revision_before"]).resolve()
            if not prior.is_relative_to(corpus.resolve()):
                raise ValueError("BENCHMARK_FIXTURE_ESCAPE")
            scenario = revision_pair(prior, path, expected["entrypoint"])
            observed, provenance = scenario["observations"], scenario["provenance"]
        measured = evaluate_observations(expected, observed, manifest.revision)
        rows.append(
            {
                "fixture": expected["path"],
                "revision": manifest.revision,
                "split": expected["split"],
                "categories": expected.get("categories", []),
                "feature_family": expected.get("feature_family", "historical-parser-regression"),
                "resource_stress": expected.get("resource_stress", False),
                "provenance": expected.get("provenance", {"status": "NOT_LABELLED"}),
                "measurement_provenance": provenance,
                "analysis_observations": observed,
                "assertions": score(predicted, set(expected["assertion_labels"])),
                "authored_assertion_count": sum(e["kind"] == "ASSERTION" for e in ir["elements"]),
                "unlabelled_assertions": sum(
                    e["kind"] == "ASSERTION" and not e["labels"] for e in ir["elements"]
                ),
                "ambiguous_labels": sorted(
                    label for label, count in label_counts.items() if count > 1
                ),
                "roles": score(
                    roles, set(expected["roles"].items()) if "roles" in expected else None
                ),
                "theorem_like_claims": theorem_count,
                "formalization": {
                    "supported": supported,
                    "selected_claims": theorem_count,
                    "labelled_supported": expected.get("supported_formalizations"),
                    "coverage_fraction": supported / theorem_count if theorem_count else None,
                    "coverage_denominator": theorem_count,
                    "labels": formal_score,
                },
                "verification": {
                    "execution": "NOT_RUN",
                    "verified": 0,
                    "supported_obligations": supported,
                    "reason": "Parsing/translation benchmark does not execute a verifier.",
                },
                "candidate_dependencies": measured["candidate_dependencies"],
                "explicit_dependencies": score(
                    predicted_edges, {tuple(p) for p in expected["dependencies"]}
                ),
                "inference_alternatives": score(
                    alternatives,
                    expected_alternatives if "inference_alternatives" in expected else None,
                ),
                "exact_identities": score(
                    exact_identities,
                    set(expected["exact_identities"].items())
                    if "exact_identities" in expected
                    else None,
                ),
                "proof_associations": proof_score,
                "symbol_bindings": symbols,
                "anchors": {"valid": len(ir["elements"]), "total": len(ir["elements"])},
                "unsupported_construct_findings": sum(
                    f["code"].startswith("UNSUPPORTED") for f in ir["findings"]
                ),
                "unresolved_region_coverage": unresolved_coverage(ir),
                "fidelity_agreement": measured["fidelity_decisions"],
                "finding_precision": findings,
                "source_finding_codes": sorted(finding_codes),
                "source_blocking_codes": sorted(hard_blocks),
                "false_hard_blocks": false_blocks,
                "invalidation_correctness": measured["invalidation"],
                "reuse_correctness": measured["reuse"],
                "replay_results": measured["replay"],
                "resources": {
                    "source_files": len(artifacts),
                    "source_bytes": sum(len(data) for data in artifacts.values()),
                    "ir_elements": len(ir["elements"]),
                    "findings": len(ir["findings"]),
                    "peak_memory_bytes": None,
                    "peak_memory_reason": "NOT_MEASURED; parser worker memory is not inferred.",
                },
                "runtime_seconds": time.monotonic() - started,
            }
        )
    strata = {
        field: [
            {"value": value, **_summary([r for r in rows if r[field] == value])}
            for value in sorted({r[field] for r in rows})
        ]
        for field in ("split", "feature_family")
    }
    category_rows = [
        {
            "id": ident,
            "description": categories.get(ident, "NOT_LABELLED"),
            **_summary([r for r in rows if ident in r["categories"]]),
        }
        for ident in CATEGORY_IDS
    ]
    return {
        "schema_version": "1.1",
        "sample_size": len(rows),
        "results": rows,
        "categories": category_rows,
        "strata": strata,
        "metric_definitions": {
            "labels": "Authored before measurement from fixture intent, not parser output.",
            "micro": "Count-weighted over papers with independent labels.",
            "macro": "Equal paper weight over defined rates; stress papers receive one vote.",
            "unknown": "Null has an explicit denominator and reason; no observations means NOT_RUN.",
            "security": "Category membership is an inventory, not execution or acceptance evidence.",
            "explicit_dependencies": "Resolved non-self assertion references via source/proof ownership; not deductive derivations.",
        },
        "population_accuracy": {
            "value": None,
            "denominator": 0,
            "reason": "FINITE_REGRESSION_CORPUS_NOT_POPULATION_SAMPLE",
        },
        "resource_summary": {
            "source_bytes": sum(row["resources"]["source_bytes"] for row in rows),
            "max_ir_elements": max(row["resources"]["ir_elements"] for row in rows),
            "runtime_seconds": sum(row["runtime_seconds"] for row in rows),
            "resource_stress_assertions": sum(
                row["authored_assertion_count"] for row in rows if row["resource_stress"]
            ),
            "peak_memory_bytes": None,
            "peak_memory_reason": "NOT_MEASURED; no parent-process proxy for worker memory.",
        },
        "totals": {
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
            "candidate_dependencies": sum(r["candidate_dependencies"]["observed"] for r in rows)
            if any(r["candidate_dependencies"]["execution"] != "NOT_RUN" for r in rows)
            else None,
            "fidelity_decisions": sum(r["fidelity_agreement"]["observed"] for r in rows),
            "fidelity_decision_authority": "ADVISORY_RECORDED_PROVIDER_OUTPUT",
            "authenticated_fidelity_reviews": 0,
        },
        "warning": "Finite synthetic regression corpus. Extraction, test-replayed interpretations and "
        "translation are not formal verification, human fidelity review or population accuracy.",
    }
