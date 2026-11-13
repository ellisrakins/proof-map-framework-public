import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from proofmap import extractor
from proofmap.integrity import artifact_digest, canonical_bytes, digest

CONFIG = {
    "provider": "ollama",
    "endpoint": "http://localhost:11434",
    "model": "fixture",
    "timeout_seconds": 3,
    "max_output_tokens": 128,
}


def large_ir(count=600):
    return {
        "revision": "revision",
        "parser": {"name": "fixture", "version": "1"},
        "elements": [
            {"id": f"s{i}", "kind": "PROSE", "text": f"Source {i}", "scope": "global"}
            for i in range(count)
        ],
        "references": [],
    }


def record(document, config, *, replay=None, **kwargs):
    request = extractor.make_request(document, config)
    element = document["elements"][0]["id"]
    raw = json.dumps(
        {
            "done": True,
            "model": "fixture",
            "message": {
                "content": json.dumps(
                    {
                        "classifications": [{"element": element, "kind": "ASSERTION"}],
                        "dependencies": [],
                    }
                )
            },
        }
    )
    event = {
        "request_sha256": artifact_digest(canonical_bytes(request)),
        "config_digest": digest("extractor-config.v1", config),
        "raw_response": raw,
        "response_sha256": artifact_digest(raw.encode()),
    }
    return ORIGINAL(document, config, replay=event)


ORIGINAL = extractor.extract


def test_long_input_chunks_and_exact_recorded_replay(monkeypatch):
    monkeypatch.setattr(extractor, "extract", record)
    result = extractor.extract_document(large_ir(), CONFIG)
    assert len(result["events"]) == 3
    assert len(result["result"]["classifications"]) == 3
    assert result["usage"]["eval_count"] is None
    monkeypatch.setattr(extractor, "extract", ORIGINAL)
    replayed = extractor.extract_document(large_ir(), CONFIG, replay=result)
    assert replayed["result"] == result["result"]
    assert all(e["replayed"] for e in replayed["events"])
    result["events"][1]["raw_response"] += " "
    with pytest.raises(ValueError, match="TAMPERED"):
        extractor.extract_document(large_ir(), CONFIG, replay=result)


def test_oversize_element_is_visible_without_truncation(monkeypatch):
    monkeypatch.setattr(extractor, "extract", record)
    ir = large_ir(3)
    ir["elements"][1]["text"] = "x" * 80_000
    result = extractor.extract_document(ir, CONFIG)
    assert result["status"] == "PARTIAL"
    assert result["findings"][0]["code"] == "EXTRACTOR_ELEMENT_BUDGET"
    assert result["findings"][0]["source"] == "s1"
    assert not any("s1" in chunk["source_ids"] for chunk in result["chunks"])
    assert result["events"]


def theorem_group():
    return [
        {"id": "theorem", "kind": "ASSERTION", "text": "For every x, x=x.", "scope": "global"},
        {
            "id": "formula",
            "kind": "MATH_EXPRESSION",
            "text": "x=x",
            "scope": "theorem-scope",
            "owner": "theorem",
        },
        {
            "id": "proof",
            "kind": "PROOF",
            "text": "By reflexivity.",
            "scope": "global",
            "proof_for": "theorem",
        },
        {
            "id": "proof-formula",
            "kind": "MATH_EXPRESSION",
            "text": "x=x",
            "scope": "proof-scope",
            "owner": "proof",
        },
    ]


@pytest.mark.parametrize("boundary", ["elements", "bytes"])
def test_theorem_math_and_attached_proof_remain_one_bounded_group(boundary):
    ir = large_ir(255 if boundary == "elements" else 1)
    if boundary == "bytes":
        ir["elements"][0]["text"] = "x" * 63_760
    ir["elements"].extend(theorem_group())
    chunks, findings = extractor.chunk_document(ir)
    assert not findings
    assert len(chunks) == 2
    assert {el["id"] for el in chunks[1]["elements"]} == {el["id"] for el in theorem_group()}
    assert [el["id"] for chunk in chunks for el in chunk["elements"]] == [
        el["id"] for el in ir["elements"]
    ]
    for chunk in chunks:
        extractor.make_request(chunk, CONFIG)


def test_hierarchy_and_reference_owners_group_nested_proof_material():
    ir = large_ir(255)
    group = theorem_group()
    group[1].pop("owner")  # historical math elements relied on their exact scope
    group[3].pop("owner")
    ir["elements"].extend(group)
    ir["elements"].append(
        {"id": "reference", "kind": "REFERENCE", "text": "ref", "scope": "nested-scope"}
    )
    ir["scopes"] = [
        {"id": "theorem-scope", "parent": "global", "element": "theorem"},
        {"id": "proof-scope", "parent": "global", "element": "proof"},
    ]
    ir["references"] = [{"element": "reference", "owner": "proof", "targets": []}]
    chunks, findings = extractor.chunk_document(ir)
    assert not findings
    assert [el["id"] for el in chunks[1]["elements"]] == [el["id"] for el in group] + ["reference"]


def test_oversized_theorem_proof_group_is_retained_whole_and_reported():
    ir = large_ir(1)
    group = theorem_group()
    group[0]["text"] = "x" * 33_000
    group[2]["text"] = "y" * 33_000
    ir["elements"].extend(group)
    ir["elements"].append(
        {"id": "after", "kind": "PROSE", "text": "Independent text.", "scope": "global"}
    )
    chunks, findings = extractor.chunk_document(ir)
    assert [el["id"] for chunk in chunks for el in chunk["elements"]] == ["s0", "after"]
    assert findings[0]["code"] == "EXTRACTOR_GROUP_BUDGET"
    assert findings[0]["source_ids"] == [el["id"] for el in group]
    assert ir["elements"][1]["text"] == "x" * 33_000


def test_section_boundaries_and_reference_context_do_not_duplicate_group_members():
    ir = large_ir(1)
    ir["elements"].extend(
        [
            {"id": "section", "kind": "SECTION", "text": "Results", "scope": "global"},
            *theorem_group(),
        ]
    )
    ir["references"] = [{"element": "proof", "owner": "proof", "targets": ["theorem", "s0", "s0"]}]
    chunks, findings = extractor.chunk_document(ir)
    assert not findings
    assert [e["id"] for e in chunks[0]["elements"]] == ["s0"]
    ids = [e["id"] for e in chunks[1]["elements"]]
    assert ids[0] == "section" and ids[-1] == "s0"
    assert len(ids) == len(set(ids))


def test_real_parser_group_keeps_nested_equation_and_reference(tmp_path):
    from proofmap.paper_sources import acquire, parse

    manuscript = tmp_path / "group.tex"
    manuscript.write_text(
        r"\begin{theorem}\label{t}For every $x\in\mathbb{Z}$,\[x=x.\]\end{theorem}"
        r"\begin{proof}\begin{equation}x=x\end{equation}See \ref{t}.\end{proof}",
        encoding="utf-8",
    )
    manifest, files = acquire(manuscript)
    ir = parse(manifest, files)
    ids = [el["id"] for el in ir["elements"]]
    ir["elements"] = [*large_ir(255)["elements"], *ir["elements"]]
    chunks, findings = extractor.chunk_document(ir)
    assert not findings
    assert len(chunks) == 2
    assert [el["id"] for el in chunks[1]["elements"]] == ids


def test_oversized_group_is_not_reintroduced_as_partial_reference_context():
    ir = large_ir(0)
    group = theorem_group()
    group[0]["text"] = "x" * 80_000
    ir["elements"] = [
        *group,
        {"id": "after", "kind": "REFERENCE", "text": "Independent reference.", "scope": "global"},
    ]
    ir["references"] = [{"element": "after", "owner": None, "targets": ["formula"]}]
    chunks, findings = extractor.chunk_document(ir)
    assert [el["id"] for chunk in chunks for el in chunk["elements"]] == ["after"]
    assert {finding["code"] for finding in findings} == {
        "EXTRACTOR_ELEMENT_BUDGET",
        "EXTRACTOR_CONTEXT_BUDGET",
    }


def test_group_element_limit_and_duplicate_source_ids_are_enforced():
    ir = large_ir(0)
    ir["elements"] = theorem_group() + [
        {
            "id": f"formula-{index}",
            "kind": "MATH_EXPRESSION",
            "text": "x=x",
            "scope": "proof-scope",
            "owner": "proof",
        }
        for index in range(253)
    ]
    chunks, findings = extractor.chunk_document(ir)
    assert not chunks
    assert findings[0]["code"] == "EXTRACTOR_GROUP_BUDGET"
    assert len(findings[0]["source_ids"]) == 257
    ir["elements"].append(ir["elements"][0])
    with pytest.raises(ValueError, match="EXTRACTOR_DUPLICATE_SOURCE_ID"):
        extractor.chunk_document(ir)


def test_run_request_budget_and_conflicting_semantics(monkeypatch):
    monkeypatch.setattr(extractor, "extract", record)
    result = extractor.extract_document(large_ir(), {**CONFIG, "max_requests": 1})
    assert result["status"] == "PARTIAL"
    assert len(result["events"]) == 1
    assert any(f["code"] == "EXTRACTOR_RUN_BUDGET" for f in result["findings"])
    with pytest.raises(ValueError, match="CONFLICTING"):
        extractor.validate_response(
            {
                "classifications": [
                    {"element": "s0", "kind": "ASSERTION"},
                    {"element": "s0", "kind": "PROSE"},
                ],
                "dependencies": [],
            },
            large_ir(),
        )


def test_semantic_overlay_has_only_reviewable_source_bound_candidates(monkeypatch):
    monkeypatch.setattr(extractor, "extract", record)
    ir = large_ir(2)
    events = extractor.extract_document(ir, CONFIG)["events"]
    events[0]["result"]["dependencies"] = [{"conclusion": "s1", "premises": ["s0"]}]
    overlay = extractor.semantic_overlay(ir, events)
    assert overlay["classifications"][0]["authority"] == "MODEL_SUGGESTION"
    candidate = overlay["candidate_dependencies"][0]
    assert candidate["conclusion"] == "s1"
    assert candidate["status"] == "REVIEW_REQUIRED"
    assert candidate["evidence"] == []
    assert ir["elements"][0]["kind"] == "PROSE"


def test_slow_stream_is_stopped_by_absolute_request_deadline():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            try:
                for _ in range(20):
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(0.15)
            except OSError:
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {**CONFIG, "endpoint": f"http://127.0.0.1:{server.server_port}", "timeout_seconds": 1}
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            ORIGINAL(large_ir(1), config)
        assert time.monotonic() - started < 2.5
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
