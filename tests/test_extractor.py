import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from proofmap.extractor import extract, validate_response
from proofmap.paper_sources import acquire, parse


def ir():
    manifest, files = acquire(Path("tests/fixtures/papers/train/basic.tex"))
    return parse(manifest, files)


def test_real_http_protocol_fake_provider_and_offline_replay():
    document = ir()
    element = document["elements"][0]["id"]
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            observed.append(
                (self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            )
            body = json.dumps(
                {
                    "model": "fixture-model",
                    "done": True,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "classifications": [{"element": element, "kind": "PROSE"}],
                                "dependencies": [],
                            }
                        ),
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
    config = {
        "provider": "ollama",
        "endpoint": f"http://127.0.0.1:{server.server_port}",
        "model": "fixture-model",
        "timeout_seconds": 3,
        "max_output_tokens": 512,
    }
    try:
        event = extract(document, config)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert observed[0][0] == "/api/chat"
    assert observed[0][1]["stream"] is False
    assert event["usage"]["prompt_eval_count"] is None
    assert extract(document, config, replay=event)["result"] == event["result"]
    event["request_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="STALE"):
        extract(document, config, replay=event)


@pytest.mark.parametrize(
    "response",
    [
        {"classifications": [{"element": "unknown", "kind": "PROSE"}], "dependencies": []},
        {"classifications": [], "dependencies": [], "command": "echo injected"},
        {"classifications": [{"element": "unknown", "kind": "PROVED"}], "dependencies": []},
    ],
)
def test_model_cannot_promote_or_invent_sources(response):
    import jsonschema

    with pytest.raises((ValueError, jsonschema.ValidationError)):
        validate_response(response, ir())
