"""Loopback-only research studio. No model calls, execution authority or public hosting."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import mimetypes
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .integrity import strict_loads
from .metrics import analyze, identify_defects
from .model import ProofMap
from .schema import validate
from .surface import build_surface_layout

MAX_UPLOAD = 8 * 1024 * 1024
MAX_REQUEST = ((MAX_UPLOAD + 2) // 3) * 4 + 4096
MAX_RESULT = 32 * 1024 * 1024
ANALYSIS_TIMEOUT = 90
STATIC = Path(__file__).with_name("studio_static")
ASSETS = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/styles.css": "styles.css",
}
NOTICE = (
    "Geometry is a visualization heuristic, not proof. Authored statuses are not accepted evidence."
)


def map_response(pm: ProofMap, mode: str = "map") -> dict[str, Any]:
    """Present diagnostics without conferring authority on imported map metadata."""
    metrics = analyze(pm).to_dict()
    metrics["accepted_claims"] = 0
    return {
        "title": pm.title,
        "mode": mode,
        "notice": NOTICE,
        "nodes": [node.to_dict() for node in pm.nodes.values()],
        "edges": [edge.to_dict() for edge in pm.edges],
        "metrics": metrics,
        "surface": build_surface_layout(pm).to_dict(),
        "findings": [
            {"title": d.defect_type, "detail": d.description, "nodes": d.affected_nodes}
            for d in identify_defects(pm)
        ],
        "claims": [],
        "checks": [{"checker": "imported-authored-status", "status": "NOT_VERIFIED"}],
    }


def demo_response() -> dict[str, Any]:
    from .examples import build_strong_weak_interface_map

    result = map_response(build_strong_weak_interface_map(), "demo")
    result["notice"] = "Bundled illustrative physics map. " + NOTICE
    return result


def paper_response(bundle: dict[str, Any], name: str) -> dict[str, Any]:
    """Show source-linked claims, never substitute lexical links for evidence."""
    from .paper_reports import report_model

    report = report_model(bundle)
    claims = report["claims"]
    nodes = [
        {
            "id": c["id"],
            "label": c["title"],
            "statement": c["source"]["text"],
            "layer": "BOUNDARY",
            "status": "AUTHOR_ASSERTED",
            "kind": c["role"],
            "domain": "Manuscript",
            "uncertainty": None,
            "source": c["source"],
        }
        for c in claims
    ]
    ids = {n["id"] for n in nodes}
    edges = [
        {"source": premise, "target": row["conclusion"], "kind": "AUTHOR_DEPENDENCY"}
        for row in bundle["argument_map"].get("inferences", [])
        for premise in row["premises"]
        if premise in ids and row["conclusion"] in ids
    ]
    findings = [
        {
            "title": str(row.get("code", row.get("kind", "Review finding"))),
            "detail": str(row.get("message", row.get("detail", row.get("description", row)))),
        }
        for row in bundle["findings"]
    ]
    if not nodes:
        findings.insert(
            0,
            {
                "title": "No source assertions extracted",
                "detail": "This parser did not identify theorem-like assertions. Text-bearing PDFs and supported TeX are bounded inputs; scanned PDFs need OCR outside this workflow.",
            },
        )
    coverage = report["outcomes"]["coverage"]
    return {
        "title": name,
        "mode": "paper",
        "notice": "Source assertions and lexical dependencies only. No model, Lean execution, fidelity approval or proof acceptance occurred. Paper geometry is a navigation layout, not a measured proof boundary.",
        "nodes": nodes,
        "edges": edges,
        "metrics": {
            **coverage,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "boundary_count": len(nodes),
            "accepted_claims": 0,
        },
        "findings": findings,
        "claims": claims,
        "checks": report["checkers"],
        "outcomes": report["outcomes"],
        "revision": report["revision"],
        "analysis_digest": report["analysis_digest"],
        "planning": report["planning"],
    }


def analyze_file(path: Path, name: str, work: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        value = strict_loads(path.read_bytes())
        if not isinstance(value, dict):
            raise ValueError("Expected a ProofMap JSON object")
        if len(value.get("nodes", [])) > 2000 or len(value.get("edges", [])) > 8000:
            raise ValueError("Studio map limit: 2,000 nodes and 8,000 edges")
        issues = validate("proofmap", value)
        if issues:
            raise ValueError("Invalid ProofMap: " + issues[0].message)
        return map_response(ProofMap.from_dict(value))
    from .paper import ci

    bundle, _code = ci(path, work / "review", work / "store", extractor="none")
    return paper_response(bundle, name)


def decode_upload(payload: Any) -> tuple[str, bytes]:
    if not isinstance(payload, dict) or set(payload) != {"name", "content"}:
        raise ValueError("Expected name and base64 content")
    name, content = payload["name"], payload["content"]
    if not isinstance(name, str) or not name or len(name) > 200:
        raise ValueError("Invalid filename")
    if any(c in name for c in "/\\:\x00") or name in {".", ".."}:
        raise ValueError("Only a plain filename is allowed")
    if Path(name).suffix.lower() not in {".tex", ".pdf", ".json"}:
        raise ValueError("Upload a .tex, text-bearing .pdf, or ProofMap .json file")
    if not isinstance(content, str) or len(content) > ((MAX_UPLOAD + 2) // 3) * 4:
        raise ValueError("Upload exceeds the 8 MiB limit")
    try:
        raw = base64.b64decode(content, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid base64 content") from exc
    if not raw or len(raw) > MAX_UPLOAD:
        raise ValueError("Upload must contain 1 byte to 8 MiB")
    return name, raw


def analyze_upload(payload: Any) -> dict[str, Any]:
    name, raw = decode_upload(payload)
    with tempfile.TemporaryDirectory(prefix="proofmap-studio-") as root:
        work = Path(root)
        source = work / ("manuscript" + Path(name).suffix.lower())
        source.write_bytes(raw)
        target = work / "result.json"
        # All inputs are data. No shell, model API, controller keys or user-supplied command.
        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "proofmap.studio",
                    "--analyze-worker",
                    str(source),
                    str(target),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=ANALYSIS_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Analysis timed out after 90 seconds; try a smaller document") from exc
        except subprocess.CalledProcessError as exc:
            raise ValueError(
                "Analysis worker failed; check the installed paper dependencies"
            ) from exc
        if not target.is_file() or target.stat().st_size > MAX_RESULT:
            raise ValueError("Analysis exceeded the result-size limit")
        result = strict_loads(target.read_bytes())
        if not isinstance(result, dict):
            raise ValueError("Analysis worker returned an invalid response; expected a JSON object")
        if "error" in result:
            if not isinstance(result["error"], str):
                raise ValueError("Analysis worker returned an invalid error response")
            raise ValueError(result["error"])
        if result.get("mode") == "paper":
            result["title"] = name
        return result


class StudioServer(ThreadingHTTPServer):
    # Wait for handlers to close worker SQLite and temporary files.
    daemon_threads = False
    block_on_close = True

    def __init__(self, port: int = 8765):
        super().__init__(("127.0.0.1", port), StudioHandler)
        self.analysis_slot = threading.BoundedSemaphore(1)
        self.allowed_hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}


class StudioHandler(BaseHTTPRequestHandler):
    server: StudioServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format: str, *args: Any) -> None:
        # Do not log source filenames, paper contents or arbitrary query strings.
        pass

    def _reply(self, code: int, raw: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, code: int, value: Any) -> None:
        self._reply(
            code,
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode(),
            "application/json; charset=utf-8",
        )

    def _trusted(self) -> bool:
        hosts = self.headers.get_all("Host", [])
        origins = self.headers.get_all("Origin", [])
        valid = len(hosts) == 1 and hosts[0] in self.server.allowed_hosts
        valid = valid and (
            not origins or (len(origins) == 1 and origins[0] == "http://" + hosts[0])
        )
        if not valid:
            self._json(403, {"error": "Only same-origin loopback requests are allowed"})
        return valid

    def do_GET(self) -> None:
        if not self._trusted():
            return
        path = urlsplit(self.path).path
        if path == "/api/demo":
            self._json(200, demo_response())
        elif path in ASSETS and (STATIC / ASSETS[path]).is_file():
            asset = STATIC / ASSETS[path]
            mime = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            if asset.suffix == ".js":
                mime = "text/javascript"
            self._reply(200, asset.read_bytes(), mime + "; charset=utf-8")
        else:
            self._json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if not self._trusted():
            return
        if self.path != "/api/analyze":
            self._json(404, {"error": "Not found"})
            return
        if (
            self.headers.get("Content-Type", "").split(";")[0] != "application/json"
            or self.headers.get("X-Proofmap-Studio") != "1"
        ):
            self._json(415, {"error": "Use application/json and the Studio request header"})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
            self._json(411, {"error": "A single Content-Length is required"})
            return
        size = int(lengths[0])
        if not 0 < size <= MAX_REQUEST:
            self._json(413, {"error": "Upload exceeds the 8 MiB limit"})
            return
        if not self.server.analysis_slot.acquire(blocking=False):
            self._json(429, {"error": "An analysis is already running; retry after it finishes"})
            return
        try:
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError("Incomplete request")
            self._json(200, analyze_upload(strict_loads(raw)))
        except (ValueError, TypeError, KeyError, TimeoutError) as exc:
            self._json(400, {"error": str(exc)[:500]})
        except Exception:
            self._json(500, {"error": "Analysis failed; no proof or acceptance was granted"})
        finally:
            self.server.analysis_slot.release()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--analyze-worker", nargs=2, metavar=("INPUT", "OUTPUT"), help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)
    if args.analyze_worker:
        source, target = map(Path, args.analyze_worker)
        try:
            result = analyze_file(source, source.name, source.parent)
        except Exception as exc:
            result = {"error": f"{type(exc).__name__}: {str(exc)[:400]}"}
        target.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        return
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    with StudioServer(args.port) as server:
        print(f"Proof Map Studio: http://127.0.0.1:{server.server_port}", flush=True)
        print("Local-only analysis. Ctrl+C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
