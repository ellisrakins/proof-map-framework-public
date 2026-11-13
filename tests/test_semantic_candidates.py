"""Semantic decomposition and model fidelity stay source-bound and advisory."""

import json
import threading
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from proofmap.extractor import extract_document, make_request, semantic_overlay, validate_response
from proofmap.integrity import artifact_digest, canonical_bytes, digest
from proofmap.semantic_candidates import (
    check_candidate_fidelity,
    source_anchors,
    validate_fidelity_report,
)

CONFIG = {
    "provider": "ollama",
    "endpoint": "http://localhost:11434",
    "model": "fixture-extractor",
    "timeout_seconds": 3,
    "max_output_tokens": 512,
    "stage": "decomposition",
}


def document():
    return {
        "revision": "a" * 64,
        "elements": [
            {
                "id": "one",
                "kind": "PROSE",
                "text": "For integers x, assume x = 0. Then x + 1 = 1.",
                "scope": "root",
            },
            {
                "id": "two",
                "kind": "PROSE",
                "text": "Unresolved mathematical prose remains visible.",
                "scope": "root",
            },
        ],
        "references": [],
    }


def candidate(ir):
    anchors = source_anchors(ir)
    owned = [key for key, row in anchors.items() if row["element"] == "one"]
    return {
        "element": "one",
        "quantifiers": [owned[0]],
        "hypotheses": [owned[0]],
        "conclusion": owned[-1],
        "references": [],
        "symbol_bindings": [],
    }


def replay_for(ir, config, result):
    raw = json.dumps(
        {"done": True, "model": config["model"], "message": {"content": json.dumps(result)}}
    )
    event = {
        "request_sha256": artifact_digest(canonical_bytes(make_request(ir, config))),
        "config_digest": digest("extractor-config.v1", config),
        "raw_response": raw,
        "response_sha256": artifact_digest(raw.encode()),
    }
    return {"revision": ir["revision"], "config_digest": event["config_digest"], "events": [event]}


def test_prose_decomposition_retains_anchored_conflicts_and_coverage():
    ir = document()
    first = candidate(ir)
    second = {**first, "hypotheses": []}
    result = {"classifications": [], "dependencies": [], "candidates": [first, second]}
    recorded = replay_for(ir, CONFIG, result)
    output = extract_document(ir, CONFIG, replay=recorded)
    overlay = semantic_overlay(ir, output["events"])
    assert len(overlay["candidates"]) == 2
    assert {row["status"] for row in overlay["candidates"]} == {"CONFLICT_REVIEW_REQUIRED"}
    assert all(
        row["replayed"] and row["authority"] == "MODEL_SUGGESTION" for row in overlay["candidates"]
    )
    assert overlay["candidate_coverage"]["eligible"] == 2
    assert overlay["candidate_coverage"]["extracted"] == 1
    assert overlay["candidate_coverage"]["unsupported_or_uninterpreted"] == 1
    assert ir == document()


@pytest.mark.parametrize(
    "mutation",
    ["invented_anchor", "other_owner", "accepted", "offset", "unknown_reference", "forged_symbol"],
)
def test_forged_decomposition_cannot_create_source_or_authority(mutation):
    ir = document()
    row = candidate(ir)
    if mutation == "invented_anchor":
        row["conclusion"] = "invented"
    elif mutation == "other_owner":
        row["conclusion"] = next(
            key for key, value in source_anchors(ir).items() if value["element"] == "two"
        )
    elif mutation == "accepted":
        row["status"] = "ACCEPTED"
    elif mutation == "offset":
        row["start_byte"] = 0
    elif mutation == "unknown_reference":
        row["references"] = ["invented"]
    else:
        row["symbol_bindings"] = [{"use": "invented", "definition": "invented"}]
    with pytest.raises(ValueError):
        validate_response(
            {"classifications": [], "dependencies": [], "candidates": [row]}, ir, "decomposition"
        )


def test_real_http_decomposition_and_independent_fidelity_disagreement():
    ir = document()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(request)
            source = json.loads(request["messages"][1]["content"])
            result = {"classifications": [], "dependencies": []}
            if "candidate_fidelity" in request["format"]["properties"]:
                result["candidate_fidelity"] = [
                    {
                        "candidate": source["candidates"][0]["id"],
                        "verdict": "DISAGREE",
                        "source_anchors": [candidate(ir)["conclusion"]],
                    }
                ]
            else:
                result["candidates"] = [candidate(ir)]
            body = json.dumps(
                {
                    "done": True,
                    "model": request["model"],
                    "message": {"content": json.dumps(result)},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {**CONFIG, "endpoint": f"http://127.0.0.1:{server.server_port}"}
    try:
        output = extract_document(ir, config)
        rows = semantic_overlay(ir, output["events"])["candidates"]
        before = deepcopy(rows)
        checked = check_candidate_fidelity(
            ir,
            rows,
            {**config, "stage": "candidate-fidelity", "model": "independent-fixture-reviewer"},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert len(requests) == 2
    assert requests[0]["model"] != requests[1]["model"]
    assert checked["execution_status"] == "PASS"
    assert checked["decisions"][0]["verdict"] == "DISAGREE"
    assert checked["authority"] == "MODEL_SUGGESTION" and not checked["replayed"]
    assert rows == before
    assert rows[0]["status"] == "REVIEW_REQUIRED"
    validate_fidelity_report(checked, ir, rows)
    tampered = deepcopy(checked)
    tampered["decisions"][0]["verdict"] = "AGREE"
    with pytest.raises(ValueError, match="REPLAY_MISMATCH"):
        validate_fidelity_report(tampered, ir, rows)


def test_fidelity_unavailable_and_stale_binding_stay_explicit():
    ir = document()
    output = extract_document(
        ir,
        CONFIG,
        replay=replay_for(
            ir, CONFIG, {"classifications": [], "dependencies": [], "candidates": [candidate(ir)]}
        ),
    )
    rows = semantic_overlay(ir, output["events"])["candidates"]
    assert check_candidate_fidelity(ir, rows, None)["execution_status"] == "UNAVAILABLE"
    validate_fidelity_report(check_candidate_fidelity(ir, rows, None), ir, rows)
    with pytest.raises(ValueError, match="INDEPENDENT_STAGE"):
        check_candidate_fidelity(ir, rows, CONFIG)
    rows[0]["revision"] = "b" * 64
    with pytest.raises(ValueError, match="CANDIDATE_BINDING"):
        check_candidate_fidelity(ir, rows, {**CONFIG, "stage": "candidate-fidelity"})


def fidelity_replay_fixture():
    ir = document()
    result = {"classifications": [], "dependencies": [], "candidates": [candidate(ir)]}
    output = extract_document(ir, CONFIG, replay=replay_for(ir, CONFIG, result))
    rows = semantic_overlay(ir, output["events"])["candidates"]
    config = {**CONFIG, "stage": "candidate-fidelity"}
    response = {
        "classifications": [],
        "dependencies": [],
        "candidate_fidelity": [
            {
                "candidate": rows[0]["id"],
                "verdict": "AGREE",
                "source_anchors": [rows[0]["conclusion"]],
            }
        ],
    }
    replay = replay_for({**ir, "candidate_interpretations": rows}, config, response)
    return ir, rows, check_candidate_fidelity(ir, rows, config, replay=replay)


@pytest.mark.parametrize(
    "field",
    [
        "result",
        "request",
        "prompt_digest",
        "schema_digest",
        "model_reported",
        "immutable_model_version",
        "usage",
    ],
)
def test_fidelity_stored_event_fields_must_match_raw_replay(field):
    ir, rows, report = fidelity_replay_fixture()
    event = report["events"][0]
    if field == "result":
        event[field] = deepcopy(event[field])
        event[field]["candidate_fidelity"][0]["verdict"] = "DISAGREE"
    elif field == "request":
        event[field]["messages"][1]["content"] = "forged manuscript"
    elif field == "usage":
        event[field]["eval_count"] = 1
    elif field in {"prompt_digest", "schema_digest"}:
        event[field] = "0" * 64
    else:
        event[field] = "different-model"
    with pytest.raises(ValueError, match="REPLAY|EXTRACTION"):
        validate_fidelity_report(report, ir, rows)


def test_fidelity_same_model_separate_stage_has_honest_independence_label():
    ir, rows, report = fidelity_replay_fixture()
    assert report["configuration"]["model"] == CONFIG["model"]
    assert (
        report["independence"] == "SEPARATELY_CONFIGURED_STAGE_AND_PROMPT_NOT_INDEPENDENT_AUTHORITY"
    )
    validate_fidelity_report(report, ir, rows)
    report["independence"] = "INDEPENDENT_AUTHORITY"
    with pytest.raises(ValueError):
        validate_fidelity_report(report, ir, rows)


def test_fidelity_replay_flags_cannot_disagree_with_event_origin_labels():
    ir, rows, report = fidelity_replay_fixture()
    report["replayed"] = False
    with pytest.raises(ValueError, match="REPLAY"):
        validate_fidelity_report(report, ir, rows)


def test_unknown_semantic_stage_rejected_before_skipping_bindings():
    with pytest.raises(ValueError, match="STAGE"):
        validate_response(
            {"classifications": [], "dependencies": [], "candidate_fidelity": []},
            document(),
            "future-fidelity",
        )


def test_ownerless_reference_is_not_a_wildcard_binding():
    ir = document()
    reference = {"element": "two", "owner": None, "targets": [], "kind": "citation"}
    ir["references"] = [reference]
    row = candidate(ir)
    row["references"] = [digest("semantic-reference.v1", reference)]
    with pytest.raises(ValueError, match="REFERENCE_BINDING"):
        validate_response(
            {"classifications": [], "dependencies": [], "candidates": [row]}, ir, "decomposition"
        )


def test_declaration_context_follows_use_across_chunk_boundary():
    from proofmap.extractor import chunk_document

    definition = {
        "id": "definition",
        "kind": "MACRO_DEFINITION",
        "scope": "root",
        "text": r"\newcommand{\foo}{1}",
    }
    assertion = {
        "id": "claim",
        "kind": "ASSERTION",
        "scope": "root",
        "text": r"\foo=1",
        "context_dependencies": ["definition"],
    }
    occurrence = {
        "id": "use",
        "kind": "SYMBOL_OCCURRENCE",
        "scope": "root",
        "text": r"\foo",
        "owner": "claim",
        "definition": "definition",
        "binding_status": "RESOLVED",
    }
    ir = {
        "revision": "a" * 64,
        "references": [],
        "elements": [
            definition,
            {"id": "section", "kind": "SECTION", "text": "Later", "scope": "root"},
            assertion,
            occurrence,
        ],
    }
    chunks, findings = chunk_document(ir)
    containing = next(
        chunk for chunk in chunks if any(row["id"] == "claim" for row in chunk["elements"])
    )
    assert len(chunks) == 2 and not findings
    assert {row["id"] for row in containing["elements"]} >= {"claim", "use", "definition"}
    context = json.loads(make_request(containing, CONFIG)["messages"][1]["content"])
    assert context["symbols"] == [definition]


def test_replay_output_budget_matches_live_protocol_budget():
    from proofmap.extractor import extract

    ir = document()
    result = {"classifications": [], "dependencies": [], "candidates": [candidate(ir)]}
    event = replay_for(ir, CONFIG, result)["events"][0]
    event["raw_response"] += " " * 1_000_001
    event["response_sha256"] = artifact_digest(event["raw_response"].encode())
    with pytest.raises(ValueError, match="OUTPUT_BUDGET"):
        extract(ir, CONFIG, replay=event)


def test_fidelity_unavailable_still_rejects_forged_or_duplicate_candidates():
    ir, rows, report = fidelity_replay_fixture()
    with pytest.raises(ValueError, match="DUPLICATE"):
        check_candidate_fidelity(ir, rows * 2, None)
    rows[0]["revision"] = "b" * 64
    with pytest.raises(ValueError, match="CANDIDATE_BINDING"):
        check_candidate_fidelity(ir, rows, None)


def test_fidelity_configured_report_cannot_claim_unavailable_shape():
    ir, rows, report = fidelity_replay_fixture()
    report["execution_status"] = "UNAVAILABLE"
    with pytest.raises(ValueError, match="CONFIGURATION_STATUS"):
        validate_fidelity_report(report, ir, rows)
