"""Local Studio trust boundary and real public-map adapter tests."""

from __future__ import annotations

import base64
import http.client
import json
import threading
from pathlib import Path

import pytest

from proofmap import studio
from proofmap.examples import build_minimal_conops_map


def upload(name: str, raw: bytes) -> dict[str, str]:
    return {"name": name, "content": base64.b64encode(raw).decode()}


@pytest.fixture
def server():
    instance = studio.StudioServer(0)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance
    instance.shutdown()
    instance.server_close()
    thread.join(timeout=2)


def request(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    result = response.status, response.read(), dict(response.getheaders())
    connection.close()
    return result


def test_demo_is_existing_public_map_not_accepted_proof():
    result = studio.demo_response()
    assert result["mode"] == "demo"
    assert len(result["nodes"]) > 10
    assert len(result["surface"]["points"]) == len(result["nodes"])
    assert result["metrics"]["accepted_claims"] == 0
    assert "not proof" in result["notice"]
    assert result["checks"][0]["status"] == "NOT_VERIFIED"


@pytest.mark.parametrize(
    "name", ["../a.tex", "a/b.tex", "C:\\a.tex", "a:foo.tex", "file.py", "", "a\x00.tex"]
)
def test_reject_unsafe_filename(name):
    with pytest.raises(ValueError):
        studio.decode_upload(upload(name, b"hello"))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        {"name": "a.tex", "content": "%%%"},
        {"name": "a.tex", "content": ""},
        {"name": "a.tex", "content": 3},
    ],
)
def test_reject_invalid_upload(payload):
    with pytest.raises(ValueError):
        studio.decode_upload(payload)


def test_upload_limit(monkeypatch):
    monkeypatch.setattr(studio, "MAX_UPLOAD", 4)
    with pytest.raises(ValueError):
        studio.decode_upload(upload("paper.tex", b"12345"))
    assert studio.decode_upload(upload("paper.tex", b"1234")) == ("paper.tex", b"1234")


def test_json_uses_real_schema_and_metrics(tmp_path):
    source = tmp_path / "map.json"
    pm = build_minimal_conops_map()
    source.write_text(pm.to_json(), encoding="utf-8")
    result = studio.analyze_file(source, source.name, tmp_path)
    assert result["metrics"]["node_count"] == len(pm.nodes)
    assert result["metrics"]["accepted_claims"] == 0
    source.write_text('{"nodes": [], "edges": [], "surprise": true}', encoding="utf-8")
    with pytest.raises(ValueError):
        studio.analyze_file(source, source.name, tmp_path)


def test_paper_adapter_never_promotes_assertions(monkeypatch):
    from proofmap import paper_reports

    report = {
        "claims": [{"id": "a", "title": "Claim A", "source": {"text": "x=x"}, "role": "THEOREM"}],
        "outcomes": {"coverage": {"accepted_claims": 99}},
        "checkers": [],
        "revision": "r",
        "analysis_digest": "d",
        "planning": {},
    }
    monkeypatch.setattr(paper_reports, "report_model", lambda _: report)
    result = studio.paper_response(
        {"argument_map": {"inferences": []}, "findings": [], "document_ir": {"elements": []}},
        "paper.tex",
    )
    assert result["nodes"][0]["status"] == "AUTHOR_ASSERTED"
    assert result["nodes"][0]["uncertainty"] is None
    assert result["metrics"]["accepted_claims"] == 0
    assert "No model" in result["notice"]


def test_host_origin_and_asset_boundaries(server):
    assert request(server, "GET", "/api/demo")[0] == 200
    assert request(server, "GET", "/api/demo", headers={"Host": "attacker.example"})[0] == 403
    assert (
        request(server, "GET", "/api/demo", headers={"Origin": "https://attacker.example"})[0]
        == 403
    )
    assert request(server, "GET", "/api/demo", headers={"Origin": "null"})[0] == 403
    assert request(server, "GET", "/../pyproject.toml")[0] == 404
    status, _, headers = request(server, "GET", "/api/demo")
    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


def test_post_requires_json_and_custom_header(server):
    body = json.dumps(upload("paper.tex", b"x"))
    assert request(server, "POST", "/api/analyze", body)[0] == 415
    assert (
        request(server, "POST", "/api/analyze", body, {"Content-Type": "application/json"})[0]
        == 415
    )


def test_post_validates_before_analysis(server, monkeypatch):
    monkeypatch.setattr(studio, "analyze_upload", lambda payload: {"title": payload["name"]})
    headers = {"Content-Type": "application/json", "X-Proofmap-Studio": "1"}
    status, raw, _ = request(
        server, "POST", "/api/analyze", json.dumps(upload("x.tex", b"x")), headers
    )
    assert status == 200 and json.loads(raw)["title"] == "x.tex"
    assert request(server, "POST", "/api/analyze", "{bad", headers)[0] == 400
    assert (
        request(
            server,
            "POST",
            "/api/analyze",
            "x",
            {**headers, "Content-Length": str(studio.MAX_REQUEST + 1)},
        )[0]
        == 413
    )
    server.analysis_slot.acquire()
    try:
        assert request(server, "POST", "/api/analyze", "{}", headers)[0] == 429
    finally:
        server.analysis_slot.release()


def test_worker_analyzes_map_and_cleans_temp_storage():
    pm = build_minimal_conops_map()
    result = studio.analyze_upload(upload("map.json", pm.to_json().encode()))
    assert result["title"] == pm.title
    assert result["metrics"]["node_count"] == len(pm.nodes)


def test_worker_real_tex_analysis():
    pytest.importorskip("pylatexenc")
    pytest.importorskip("pypdf")
    raw = Path("tests/fixtures/papers/train/basic.tex").read_bytes()
    result = studio.analyze_upload(upload("basic.tex", raw))
    assert result["mode"] == "paper"
    assert result["title"] == "basic.tex"
    assert result["nodes"]
    assert result["metrics"]["accepted_claims"] == 0
    assert all(n["status"] == "AUTHOR_ASSERTED" for n in result["nodes"])
    assert result["checks"]


def test_worker_timeout_is_actionable(monkeypatch):
    import subprocess

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("worker", 90)

    monkeypatch.setattr(studio.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="timed out"):
        studio.analyze_upload(upload("x.tex", b"x"))


def test_worker_failure_is_actionable(monkeypatch):
    import subprocess

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "worker")

    monkeypatch.setattr(studio.subprocess, "run", fail)
    with pytest.raises(ValueError, match="worker failed"):
        studio.analyze_upload(upload("x.tex", b"x"))


def test_worker_real_pdf_analysis(tmp_path):
    pytest.importorskip("pypdf")
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    path = tmp_path / "paper.pdf"
    document = canvas.Canvas(str(path))
    document.drawString(50, 750, "Theorem 1. For every integer x, x + 0 = x.")
    document.drawString(50, 720, "Proof. This is the additive identity.")
    document.save()
    result = studio.analyze_upload(upload("paper.pdf", path.read_bytes()))
    assert result["metrics"]["source_pages"] == 1
    assert "Imported 1 PDF pages" in result["findings"][0]["detail"]
    assert result["mode"] == "paper"
    assert result["metrics"]["accepted_claims"] == 0
    assert result["outcomes"]["formal_statement_fidelity"] == "NOT_REVIEWED"


def test_map_resource_limit(tmp_path):
    source = tmp_path / "map.json"
    source.write_text(json.dumps({"nodes": [{}] * 2001, "edges": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="2,000"):
        studio.analyze_file(source, source.name, tmp_path)


def test_duplicate_json_keys_rejected(tmp_path):
    source = tmp_path / "map.json"
    source.write_text('{"nodes": [], "nodes": []}', encoding="utf-8")
    with pytest.raises(ValueError):
        studio.analyze_file(source, source.name, tmp_path)


def test_server_close_waits_for_active_analysis(monkeypatch):
    """Shutdown must not abandon the handler's worker/temp-directory cleanup."""
    entered, finish, cleaned, closed = (threading.Event() for _ in range(4))

    def analyze(_payload):
        entered.set()
        try:
            assert finish.wait(5)
            return {"title": "complete"}
        finally:
            cleaned.set()

    monkeypatch.setattr(studio, "analyze_upload", analyze)
    instance = studio.StudioServer(0)
    serving = threading.Thread(target=instance.serve_forever)
    serving.start()
    results = []
    client = threading.Thread(
        target=lambda: results.append(
            request(
                instance,
                "POST",
                "/api/analyze",
                "{}",
                {"Content-Type": "application/json", "X-Proofmap-Studio": "1"},
            )
        )
    )
    client.start()
    assert entered.wait(3)
    instance.shutdown()

    def close():
        instance.server_close()
        closed.set()

    closing = threading.Thread(target=close)
    closing.start()
    try:
        assert not closed.wait(0.1)
        assert not cleaned.is_set()
    finally:
        finish.set()
        client.join(timeout=5)
        closing.join(timeout=5)
        serving.join(timeout=5)
    assert cleaned.is_set() and closed.is_set()
    assert results[0][0] == 200


@pytest.mark.parametrize("result", [None, [], ["error"], "error", 42, True])
def test_worker_rejects_non_object_output(monkeypatch, result):
    def malformed(command, **kwargs):
        Path(command[-1]).write_text(json.dumps(result), encoding="utf-8")

    monkeypatch.setattr(studio.subprocess, "run", malformed)
    with pytest.raises(ValueError, match="expected a JSON object"):
        studio.analyze_upload(upload("x.tex", b"x"))


def test_worker_rejects_non_string_error(monkeypatch):
    def malformed(command, **kwargs):
        Path(command[-1]).write_text('{"error": null}', encoding="utf-8")

    monkeypatch.setattr(studio.subprocess, "run", malformed)
    with pytest.raises(ValueError, match="invalid error response"):
        studio.analyze_upload(upload("x.tex", b"x"))


@pytest.mark.parametrize("name", ["paper.pdf", "paper.tex"])
def test_paper_upload_enforces_parser_byte_limit(name):
    with pytest.raises(ValueError, match="4,000,000-byte"):
        studio.decode_upload(upload(name, b"x" * 4_000_001))
