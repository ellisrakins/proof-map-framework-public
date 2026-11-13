"""Replay the CLI's own persisted model events without a live provider."""

import json
import threading
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from proofmap.cli import main
from proofmap.extractor import chunk_document
from proofmap.integrity import load_json, write_json


@pytest.fixture(scope="module")
def recorded_paper(tmp_path_factory, request):
    tmp_path = tmp_path_factory.mktemp("recorded-paper")
    count = getattr(request, "param", None)
    source = tmp_path / "paper.tex"
    if count is None:
        # Negative replay contracts need two real events, not a large paper.
        # Natural section boundaries preserve missing/extra chunk detection;
        # the explicit positive [270] case still tests the >256-element split.
        source.write_text(
            r"\section{First}\begin{remark}First observation.\end{remark}"
            "\n"
            r"\section{Second}\begin{remark}Second observation.\end{remark}"
        )
    else:
        source.write_text(
            "\n".join(r"\begin{remark}Observation.\end{remark}" for _ in range(count))
        )
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            elements = json.loads(request["messages"][1]["content"])["elements"]
            assertion = next(element for element in elements if element["kind"] == "ASSERTION")
            requests.append(request)
            body = json.dumps(
                {
                    "done": True,
                    "model": "recorded-cli-test",
                    "message": {
                        "content": json.dumps(
                            {
                                "classifications": [{"element": assertion["id"], "kind": "REMARK"}],
                                "dependencies": [],
                            }
                        )
                    },
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
    config = tmp_path / "config.json"
    write_json(
        config,
        {
            "extractor": {
                "provider": "ollama",
                "endpoint": f"http://127.0.0.1:{server.server_port}",
                "model": "recorded-cli-test",
                "timeout_seconds": 3,
                "max_output_tokens": 128,
            }
        },
    )
    output = tmp_path / "recorded"
    args = ["paper", "ci", str(source), "--config", str(config)]
    try:
        assert (
            main(
                args
                + [
                    "--extractor",
                    "configured",
                    "--out",
                    str(output),
                    "--store",
                    str(tmp_path / "store"),
                ]
            )
            == 0
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert len(requests) == (2 if count is None else (count + 255) // 256)
    if count is None:
        chunks, findings = chunk_document(load_json(output / "document_ir.json"))
        events = load_json(output / "extraction_events.json")
        assert not findings and len(chunks) == len(events) == 2
        assert all(
            any(element["kind"] == "ASSERTION" for element in chunk["elements"]) for chunk in chunks
        )
        assert len({event["request_sha256"] for event in events}) == 2
    return args, output


@pytest.mark.parametrize("recorded_paper", [1, 270], indirect=True)
def test_cli_replays_exported_and_compatible_records_offline(recorded_paper, tmp_path, monkeypatch):
    args, original = recorded_paper

    def no_network(*args, **kwargs):
        raise AssertionError("Replay contacted a model endpoint")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", no_network)
    before = load_json(original / "extraction_events.json")
    document = tmp_path / "document.json"
    write_json(
        document,
        {
            "revision": before[0]["revision"],
            "config_digest": before[0]["config_digest"],
            "events": before,
        },
    )
    recordings = [original / "extraction_events.json", document]
    if len(before) == 1:
        legacy = tmp_path / "legacy.json"
        write_json(
            legacy,
            {
                k: before[0][k]
                for k in ("request_sha256", "config_digest", "raw_response", "response_sha256")
            },
        )
        recordings.append(legacy)
    for i, recording in enumerate(recordings):
        output = tmp_path / f"replayed-{i}"
        assert (
            main(
                args
                + [
                    "--extractor",
                    "replay",
                    "--replay-event",
                    str(recording),
                    "--out",
                    str(output),
                    "--store",
                    str(tmp_path / f"replay-store-{i}"),
                ]
            )
            == 0
        )
        after = load_json(output / "extraction_events.json")
        assert [e["result"] for e in after] == [e["result"] for e in before]
        assert all(e["replayed"] for e in after)
        assert load_json(output / "argument_map.json") == load_json(original / "argument_map.json")
        assert load_json(output / "assessment.json")["outcomes"]["coverage"]["accepted_claims"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "revision",
        "config",
        "payload",
        "missing",
        "extra",
        "shape",
        "field_type",
        "oversize",
        "document_binding",
        "document_shape",
        "empty_object",
        "event_limit",
    ],
)
def test_exported_replay_rejects_stale_or_malformed_input(recorded_paper, tmp_path, mutation):
    args, original = recorded_paper
    records = deepcopy(load_json(original / "extraction_events.json"))
    assert len(records) == 2
    if mutation == "revision":
        records[0]["revision"] = "0" * 64
    elif mutation == "config":
        records[0]["config_digest"] = "0" * 64
    elif mutation == "payload":
        records[0]["raw_response"] += " "
    elif mutation == "missing":
        records.pop()
        assert len(records) == 1 and records[0]
    elif mutation == "extra":
        records.append(records[0])
        assert len(records) == 3
    elif mutation == "shape":
        records = [None]
    elif mutation == "field_type":
        records[0]["raw_response"] = None
    elif mutation == "oversize":
        records[0]["raw_response"] = "x" * 1_000_001
    elif mutation == "document_binding":
        records = {
            "revision": "0" * 64,
            "config_digest": records[0]["config_digest"],
            "events": records,
        }
    elif mutation == "document_shape":
        records = {
            "revision": records[0]["revision"],
            "config_digest": records[0]["config_digest"],
            "events": {},
        }
    elif mutation == "empty_object":
        records = {}
    else:
        records *= 33
        assert len(records) == 66
    replay = tmp_path / "bad.json"
    write_json(replay, records)
    output = tmp_path / "bad-result"
    assert (
        main(
            args
            + [
                "--extractor",
                "replay",
                "--replay-event",
                str(replay),
                "--out",
                str(output),
                "--store",
                str(tmp_path / "bad-store"),
            ]
        )
        == 3
    )
    assert load_json(output / "extraction_events.json") == []
    assert load_json(output / "assessment.json")["outcomes"]["pipeline_execution"] == "ERROR"
