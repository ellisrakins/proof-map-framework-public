"""Bounded original recorded-provider scenarios for regression measurements.

These execute the public extraction/fidelity/replay APIs without a network call.
The canned provider output and independently authored oracle labels are distinct
fixture inputs. Their agreement is a regression statistic, not model accuracy.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .extractor import chunk_document, extract_document, make_request, semantic_overlay
from .integrity import artifact_digest, canonical_bytes, digest
from .semantic_candidates import (
    check_candidate_fidelity,
    source_anchors,
    validate_fidelity_report,
)


def recorded_response(
    ir: dict[str, Any], config: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    chunks, findings = chunk_document(ir)
    if len(chunks) != 1 or findings:
        raise ValueError("BENCHMARK_REPLAY_REQUIRES_ONE_COMPLETE_CHUNK")
    chunk = chunks[0]
    if config["stage"] == "candidate-fidelity":
        chunk = {**chunk, "candidate_interpretations": ir["candidate_interpretations"]}
    raw = json.dumps(
        {"done": True, "model": config["model"], "message": {"content": json.dumps(result)}}
    )
    config_digest = digest("extractor-config.v1", config)
    event = {
        "request_sha256": artifact_digest(canonical_bytes(make_request(chunk, config))),
        "config_digest": config_digest,
        "raw_response": raw,
        "response_sha256": artifact_digest(raw.encode("utf-8")),
    }
    return {"revision": ir["revision"], "config_digest": config_digest, "events": [event]}


def semantic_replay(ir: dict[str, Any], specification: dict[str, Any]) -> dict[str, Any]:
    before = canonical_bytes(ir)
    by_label: dict[str, list[dict[str, Any]]] = {}
    for source_element in ir["elements"]:
        for label in source_element["labels"]:
            by_label.setdefault(label, []).append(source_element)

    def element(label: str) -> dict[str, Any]:
        if len(by_label.get(label, [])) != 1:
            raise ValueError("BENCHMARK_SEMANTIC_FIXTURE_LABEL")
        return by_label[label][0]

    target = element(specification["element_label"])
    anchors = source_anchors(ir)

    def anchor(text: str) -> str:
        found = [
            key
            for key, row in anchors.items()
            if row["element"] == target["id"] and row["text"] == text
        ]
        if len(found) != 1:
            raise ValueError("BENCHMARK_SEMANTIC_FIXTURE_ANCHOR")
        return found[0]

    full = {
        "element": target["id"],
        "quantifiers": [anchor(specification["quantifier_text"])],
        "hypotheses": [anchor(specification["hypothesis_text"])],
        "conclusion": anchor(target["text"]),
        "references": [],
        "symbol_bindings": [],
    }
    missing = {**full, "hypotheses": []}
    config = {
        "provider": "ollama",
        "endpoint": "http://127.0.0.1:9",
        "model": "original-recorded-extractor",
        "timeout_seconds": 3,
        "max_output_tokens": 2048,
        "stage": "decomposition",
    }
    result = {
        "classifications": [],
        "candidates": [full, missing],
        "dependencies": [
            {"premises": [element(source)["id"]], "conclusion": element(conclusion)["id"]}
            for source, conclusion in specification["dependency_proposals"]
        ],
    }
    extracted = extract_document(ir, config, replay=recorded_response(ir, config, result))
    overlay = semantic_overlay(ir, extracted["events"])
    candidates = overlay["candidates"]
    names = {
        row["id"]: "complete" if row["hypotheses"] else "missing-hypothesis" for row in candidates
    }
    fidelity_config = {
        **config,
        "stage": "candidate-fidelity",
        "model": "independent-original-recorded-reviewer",
    }
    fidelity_result = {
        "classifications": [],
        "dependencies": [],
        "candidate_fidelity": [
            {
                "candidate": row["id"],
                "verdict": specification["fidelity_verdicts"][names[row["id"]]],
                "source_anchors": [row["conclusion"]],
            }
            for row in candidates
        ],
    }
    fidelity = check_candidate_fidelity(
        ir,
        candidates,
        fidelity_config,
        replay=recorded_response(
            {**ir, "candidate_interpretations": candidates}, fidelity_config, fidelity_result
        ),
    )
    validate_fidelity_report(fidelity, ir, candidates)
    exported = {
        "revision": ir["revision"],
        "config_digest": extracted["config_digest"],
        "events": extracted["events"],
    }
    repeated = extract_document(ir, config, replay=exported)
    replay = {
        "semantic_roundtrip": "REPLAY_MATCH"
        if repeated["result"] == extracted["result"]
        else "REPLAY_MISMATCH",
        "stale_request": "UNEXPECTED_ACCEPTANCE",
    }
    stale = deepcopy(exported)
    stale["events"][0]["request_sha256"] = "0" * 64
    rejection = None
    try:
        extract_document(ir, config, replay=stale)
    except ValueError as exc:
        rejection = str(exc)
        replay["stale_request"] = "BINDING_REJECTED"
    label_by_id = {rows[0]["id"]: label for label, rows in by_label.items() if len(rows) == 1}
    observations = {
        "revision": ir["revision"],
        "candidate_dependencies": [
            [label_by_id[premise], label_by_id[row["conclusion"]]]
            for row in overlay["candidate_dependencies"]
            for premise in row["premises"]
        ],
        "fidelity_decisions": {
            names[row["candidate"]]: row["verdict"] for row in fidelity["decisions"]
        },
        "replay": replay,
    }
    if canonical_bytes(ir) != before:
        raise ValueError("BENCHMARK_SCENARIO_MUTATED_SOURCE")
    return {
        "observations": observations,
        "provenance": {
            "execution": "RECORDED_ORIGINAL_PROVIDER_FIXTURE",
            "authority": "MODEL_SUGGESTION",
            "replayed": True,
            "independent_fidelity_configuration": fidelity["config_digest"]
            != extracted["config_digest"],
            "source_unchanged": True,
            "candidate_coverage": overlay["candidate_coverage"],
            "replay_rejection": rejection,
            "formal_execution": "NOT_RUN",
            "authenticated_human_reviews": 0,
            "population_accuracy": None,
        },
    }


def revision_pair(before: Path, after: Path, entrypoint: str) -> dict[str, Any]:
    """Measure completed pure stages; this does not execute or reuse Lean proofs."""
    from .paper import ci, diff
    from .paper_store import PaperStore

    with TemporaryDirectory(prefix="proofmap-benchmark-revision-") as temporary:
        work = Path(temporary)
        first, first_code = ci(
            before,
            work / "before",
            work / "store",
            entrypoint=entrypoint,
            paper_id="original-benchmark-branches",
        )
        second, second_code = ci(
            after,
            work / "after",
            work / "store",
            entrypoint=entrypoint,
            paper_id="original-benchmark-branches",
        )
        if first_code or second_code:
            raise ValueError("BENCHMARK_REVISION_PIPELINE_FAILED")
        old_labels = {
            element["id"]: element["labels"][0]
            for element in first["document_ir"]["elements"]
            if element["kind"] == "ASSERTION" and len(element["labels"]) == 1
        }
        changed = set(diff(first, second)["invalidated_assertions"])
        rows = second["revision_plan"]["rows"]
        store = PaperStore(work / "store")
        try:
            store.rebuild()
            immutable = canonical_bytes(
                store.inspect(first["run_manifest"]["run_id"])["bundle"]
            ) == canonical_bytes(first)
        finally:
            store.close()
        return {
            "observations": {
                "revision": second["input_manifest"]["revision"],
                "invalidation": {label: ident in changed for ident, label in old_labels.items()},
                "reuse": {row["label"]: row["pure_execution"] == "REUSED" for row in rows},
            },
            "provenance": {
                "execution": "ACTUAL_OFFLINE_PIPELINE_PURE_STAGES",
                "source_revisions": [
                    first["input_manifest"]["revision"],
                    second["input_manifest"]["revision"],
                ],
                "completed_stages": [
                    {
                        key: row.get(key)
                        for key in (
                            "label",
                            "pure_execution",
                            "pure_stage",
                            "parent_stage",
                            "reasons",
                        )
                    }
                    for row in rows
                ],
                "executed_pure_stages": sum(row["pure_execution"] == "EXECUTED" for row in rows),
                "reused_pure_stages": sum(row["pure_execution"] == "REUSED" for row in rows),
                "historical_run_immutable_after_rebuild": immutable,
                "formal_execution": "NOT_RUN",
                "authenticated_human_reviews": 0,
                "accepted_claims": len(second["acceptance_records"]),
            },
        }
