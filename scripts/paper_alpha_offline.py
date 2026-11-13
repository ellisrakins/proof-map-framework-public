"""Copyable installed-distribution scenarios C/D; the local HTTP provider is a test double."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import threading
import zipfile
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path
from typing import Any


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def cli(arguments: list[str], expected: int, *, installed: bool) -> dict[str, Any]:
    if installed:
        process = subprocess.run(
            [sys.executable, "-I", "-m", "proofmap.cli", "paper", *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        code, stdout, stderr = process.returncode, process.stdout, process.stderr
    else:
        from proofmap.cli import main

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["paper", *arguments])
        stdout, stderr = out.getvalue(), err.getvalue()
    check(code == expected, f"CLI {arguments[0]} returned {code}, expected {expected}: {stderr}")
    return {"command": arguments[0], "returncode": code, "stdout": stdout, "stderr": stderr}


def installed_material(wheel: Path | None) -> dict[str, Any]:
    import proofmap

    package = Path(proofmap.__file__).resolve().parent
    result: dict[str, Any] = {
        "package_version": version("proof-map-boundary-analysis"),
        "package_path": str(package),
        "wheel_sha256": None,
        "verified_files": 0,
        "installed": False,
    }
    if wheel is None:
        return result
    check("site-packages" in package.parts, "Driver did not import an installed wheel")
    check(
        Path(sys.prefix).resolve() in package.parents,
        "Package lies outside the isolated environment",
    )
    count = 0
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if not name.startswith("proofmap/") or name.endswith("/"):
                continue
            relative = Path(name).relative_to("proofmap")
            check(".." not in relative.parts, "Unsafe wheel material path")
            check(
                (package / relative).read_bytes() == archive.read(name),
                "Installed package differs from wheel: " + name,
            )
            count += 1
    check(count > 0, "Wheel contains no package material")
    result.update(
        installed=True,
        verified_files=count,
        wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
    )
    return result


def run_scenarios(fixtures: Path, root: Path, *, wheel: Path | None = None) -> dict[str, Any]:
    from proofmap.integrity import canonical_bytes, digest, load_json, write_json
    from proofmap.paper import load_bundle

    root.mkdir(parents=True, exist_ok=True)
    material = installed_material(wheel)
    installed = material["installed"]
    copied = root / "fixtures"
    shutil.copytree(fixtures, copied)
    store = root / "store"
    commands: list[dict[str, Any]] = []

    def command(args: list[str], expected: int = 0) -> dict[str, Any]:
        event = cli(args, expected, installed=installed)
        commands.append(event)
        return event

    identity = copied / "train" / "reflexivity.tex"
    offline = root / "offline"
    command(
        [
            "ci",
            str(identity),
            "--extractor",
            "none",
            "--paper-id",
            "offline-identity",
            "--out",
            str(offline),
            "--store",
            str(store),
        ]
    )
    plain = load_bundle(offline)
    check(
        bool(plain["assertions"]) and not plain["extraction_events"],
        "Offline ingestion did not retain authored claims",
    )
    listed = json.loads(command(["list", "--store", str(store)])["stdout"])
    inspected = json.loads(
        command(
            ["inspect", plain["run_manifest"]["run_id"], "--view", "review", "--store", str(store)]
        )["stdout"]
    )
    check(
        bool(listed) and len(inspected["claims"]) == len(plain["assertions"]),
        "Offline index/inspection mismatch",
    )
    command(["report", str(offline), "--out", str(root / "offline-report"), "--store", str(store)])
    formal_out = root / "formal-unavailable"
    command(
        [
            "ci",
            str(identity),
            "--require-formal",
            "--paper-id",
            "offline-identity",
            "--out",
            str(formal_out),
            "--store",
            str(store),
        ],
        3,
    )
    required = load_bundle(formal_out)
    check(
        required["assessment"]["outcomes"]["formal_compilation"] == "UNAVAILABLE"
        and not required["execution_events"],
        "Required formal unavailability was hidden",
    )
    scenario_c = {
        "offline_assertions": len(plain["assertions"]),
        "indexed_runs": len(listed),
        "inspected_claims": len(inspected["claims"]),
        "required_formal_exit": 3,
        "required_formal_status": "UNAVAILABLE",
        "model_events": len(plain["extraction_events"]),
        "execution_events": len(required["execution_events"]),
        "report_files": sorted(p.name for p in (root / "offline-report").iterdir()),
    }

    multi_out = root / "multi"
    command(
        [
            "ci",
            str(copied / "alpha_semantics"),
            "--entrypoint",
            "main.tex",
            "--out",
            str(multi_out),
            "--store",
            str(store),
        ]
    )
    multi = load_bundle(multi_out)
    ir = multi["document_ir"]
    citations = [
        ref for ref in ir["references"] if ref["kind"] == "CITATION" and ref.get("targets")
    ]
    uses = [
        el
        for el in ir["elements"]
        if el["kind"] == "SYMBOL_OCCURRENCE" and el.get("binding_status") == "RESOLVED"
    ]
    check(
        len(multi["input_manifest"]["artifacts"]) >= 3 and bool(citations) and bool(uses),
        "Multi-file citation/scope path incomplete",
    )

    pdf_results: dict[str, dict[str, Any]] = {}
    for filename in ("born_digital.pdf", "scan.pdf"):
        output = root / filename.replace(".pdf", "")
        command(["ci", str(copied / "pdf" / filename), "--out", str(output), "--store", str(store)])
        pdf = load_bundle(output)
        pdf_results[filename] = {
            "pages": len(pdf["document_ir"]["elements"]),
            "characters": sum(len(el["text"]) for el in pdf["document_ir"]["elements"]),
            "finding_codes": sorted({f["code"] for f in pdf["findings"]}),
        }
    check(
        pdf_results["born_digital.pdf"]["characters"] > 0, "Born-digital PDF text not reconstructed"
    )
    check(
        "NEEDS_OCR" in pdf_results["scan.pdf"]["finding_codes"],
        "Scan incorrectly claimed extraction",
    )

    observed: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            observed.append(
                {"path": self.path, "model": request["model"], "stream": request["stream"]}
            )
            source = json.loads(request["messages"][1]["content"])
            candidates = []
            for element in source["elements"]:
                if element["kind"] not in {"ASSERTION", "PROSE"}:
                    continue
                anchor = next(
                    (
                        key
                        for key, row in source["anchors"].items()
                        if row["element"] == element["id"]
                    ),
                    None,
                )
                if anchor is not None:
                    candidates.append(
                        {
                            "element": element["id"],
                            "quantifiers": [],
                            "hypotheses": [],
                            "conclusion": anchor,
                            "references": [],
                            "symbol_bindings": [],
                        }
                    )
            result = {"classifications": [], "dependencies": [], "candidates": candidates}
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

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {
        "extractor": {
            "provider": "ollama",
            "endpoint": f"http://127.0.0.1:{server.server_port}",
            "model": "explicit-local-protocol-test-double",
            "timeout_seconds": 3,
            "max_output_tokens": 2048,
            "stage": "decomposition",
        }
    }
    config_path = root / "extractor-config.json"
    write_json(config_path, config)
    prose = copied / "heldout" / "prose_only.tex"
    extracted_out = root / "extracted"
    try:
        command(
            [
                "ci",
                str(prose),
                "--extractor",
                "configured",
                "--config",
                str(config_path),
                "--out",
                str(extracted_out),
                "--store",
                str(store),
            ]
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    extracted = load_bundle(extracted_out)
    candidates = extracted["semantic_overlay"]["candidates"]
    check(
        bool(observed) and bool(candidates), "Configured protocol did not emit anchored candidates"
    )
    replay_out = root / "replayed"
    command(
        [
            "ci",
            str(prose),
            "--extractor",
            "replay",
            "--config",
            str(config_path),
            "--replay-event",
            str(extracted_out / "extraction_events.json"),
            "--out",
            str(replay_out),
            "--store",
            str(store),
        ]
    )
    replayed = load_bundle(replay_out)
    check(
        [r["id"] for r in candidates]
        == [r["id"] for r in replayed["semantic_overlay"]["candidates"]],
        "Replay changed candidate subjects",
    )
    check(
        all(r["authority"] == "MODEL_SUGGESTION" for r in candidates), "Model output was promoted"
    )
    forged_replay = deepcopy(extracted["extraction_events"])
    forged_replay[0]["request_sha256"] = "0" * 64
    write_json(root / "forged-replay.json", forged_replay)
    command(
        [
            "ci",
            str(prose),
            "--extractor",
            "replay",
            "--config",
            str(config_path),
            "--replay-event",
            str(root / "forged-replay.json"),
            "--out",
            str(root / "forged-replay"),
            "--store",
            str(store),
        ],
        3,
    )

    review_out = root / "review-original"
    command(
        [
            "ci",
            str(copied / "review_override" / "main.tex"),
            "--paper-id",
            "review-example",
            "--out",
            str(review_out),
            "--store",
            str(store),
        ]
    )
    original = load_bundle(review_out)
    proof = next(e for e in original["document_ir"]["elements"] if e["kind"] == "PROOF")
    check(proof["proof_for"] is None, "Ambiguous proof was guessed")
    draft_path = root / "override.json"
    command(
        [
            "override-export",
            str(review_out),
            "--author",
            "Attributed fixture editor",
            "--out",
            str(draft_path),
        ]
    )
    draft = load_json(draft_path)
    targets = {row["id"]: row for row in draft["targets"]}
    labels = {label: e["id"] for e in original["document_ir"]["elements"] for label in e["labels"]}
    for target, kind, value in (
        (labels["claim:custom"], "role", "LEMMA"),
        (proof["id"], "proof_for", labels["claim:second"]),
        (labels["claim:second"], "dependencies", [labels["claim:custom"]]),
    ):
        row = targets[target]
        draft["changes"].append(
            {
                "kind": kind,
                "target": target,
                "scope": row["scope"],
                "source_digest": row["source_digest"],
                "value": value,
                "note": "Explicit interpretation for the original alpha fixture.",
            }
        )
    write_json(draft_path, draft)
    changed_out = root / "review-derived"
    command(
        [
            "override-apply",
            str(review_out),
            str(draft_path),
            "--out",
            str(changed_out),
            "--store",
            str(store),
        ]
    )
    changed = load_bundle(changed_out)
    check(
        canonical_bytes(original["document_ir"]) == canonical_bytes(changed["document_ir"])
        and original["extraction_events"] == changed["extraction_events"],
        "Override mutated source or model output",
    )
    check(original["argument_map"] != changed["argument_map"], "Override did not recompute the map")
    query = json.loads(
        command(["query", "--store", str(store), "--paper", "review-example", "--role", "LEMMA"])[
            "stdout"
        ]
    )
    check(
        len(query) == 1 and query[0]["assertion"] == labels["claim:custom"],
        "Derived role was not queryable",
    )
    command(
        ["report", str(changed_out), "--out", str(root / "review-report"), "--store", str(store)]
    )
    report = load_json(root / "review-report" / "report.json")
    check(
        any(c["role"] == "LEMMA" for c in report["claims"]), "Report retained stale interpretation"
    )
    draft["revision"] = "0" * 64
    write_json(root / "stale-override.json", draft)
    command(
        [
            "override-apply",
            str(review_out),
            str(root / "stale-override.json"),
            "--out",
            str(root / "stale-derived"),
            "--store",
            str(store),
        ],
        2,
    )
    check(not (root / "stale-derived").exists(), "Rejected override produced output")
    check(
        not changed["execution_events"] and not changed["acceptance_records"],
        "Interpretation override conferred authority",
    )
    scenario_d = {
        "source_artifacts": len(multi["input_manifest"]["artifacts"]),
        "resolved_citations": len(citations),
        "resolved_macro_uses": len(uses),
        "ambiguous_proof_preserved": proof["proof_for"] is None,
        "pdf": pdf_results,
        "provider": {
            "kind": "LOCAL_HTTP_TEST_DOUBLE",
            "requests": observed,
            "candidate_count": len(candidates),
            "candidate_ids": [r["id"] for r in candidates],
            "replayed_candidate_ids": [r["id"] for r in replayed["semantic_overlay"]["candidates"]],
            "forged_replay_exit": 3,
            "authority": "MODEL_SUGGESTION",
        },
        "override": {
            "changes": len(changed["interpretation_overrides"][-1]["changes"]),
            "original_run": original["run_manifest"]["run_id"],
            "derived_run": changed["run_manifest"]["run_id"],
            "original_graph": digest("alpha-offline-graph.v1", original["argument_map"]),
            "derived_graph": digest("alpha-offline-graph.v1", changed["argument_map"]),
            "raw_ir_digest": digest("alpha-offline-source.v1", original["document_ir"]),
            "derived_raw_ir_digest": digest("alpha-offline-source.v1", changed["document_ir"]),
            "attribution_authenticated": False,
            "query_matches": len(query),
            "stale_override_exit": 2,
            "execution_events": 0,
            "accepted_claims": changed["assessment"]["outcomes"]["coverage"]["accepted_claims"],
        },
    }
    result = {
        "schema_version": "1.0",
        "kind": "PAPER_ALPHA_OFFLINE_OUTCOMES",
        "profile": "installed-wheel" if installed else "source-checkout-test",
        "material": material,
        "scenarios": {"C": scenario_c, "D": scenario_d},
        "commands": commands,
    }
    validate_outcomes(result, require_installed=installed)
    return result


def validate_outcomes(value: dict[str, Any], *, require_installed: bool = True) -> None:
    from proofmap.integrity import require_digest

    check(
        value.get("schema_version") == "1.0"
        and value.get("kind") == "PAPER_ALPHA_OFFLINE_OUTCOMES",
        "Offline outcome schema",
    )
    material = value["material"]
    check(
        type(material["verified_files"]) is int and isinstance(material["package_version"], str),
        "Malformed installed material",
    )
    if require_installed:
        check(
            value["profile"] == "installed-wheel"
            and material["installed"] is True
            and material["verified_files"] > 0
            and len(material["wheel_sha256"]) == 64,
            "Actual installed-wheel evidence required",
        )
    # Each pair corresponds to an operation exercised by run_scenarios. Counts
    # vary with fixtures; successful and expected negative paths must be present.
    required_commands = {
        ("ci", 0),
        ("ci", 3),
        ("list", 0),
        ("inspect", 0),
        ("report", 0),
        ("override-export", 0),
        ("override-apply", 0),
        ("override-apply", 2),
        ("query", 0),
    }
    commands = value.get("commands")
    if not isinstance(commands, list) or not commands:
        raise ValueError("Missing CLI operation outcomes")
    observed_commands = set()
    for command in commands:
        check(
            isinstance(command, dict)
            and set(command) == {"command", "returncode", "stdout", "stderr"}
            and all(isinstance(command[key], str) for key in ("command", "stdout", "stderr"))
            and type(command["returncode"]) is int,
            "Malformed CLI operation outcome",
        )
        pair = (command["command"], command["returncode"])
        check(pair in required_commands, "Unexpected CLI operation exit")
        observed_commands.add(pair)
    check(required_commands <= observed_commands, "Missing required CLI operation/exit")
    c, d = value["scenarios"]["C"], value["scenarios"]["D"]
    counts = [
        c[name]
        for name in (
            "offline_assertions",
            "indexed_runs",
            "inspected_claims",
            "required_formal_exit",
            "model_events",
            "execution_events",
        )
    ]
    counts.extend(
        d[name] for name in ("source_artifacts", "resolved_citations", "resolved_macro_uses")
    )
    counts.extend(
        d["pdf"][name][key]
        for name in ("born_digital.pdf", "scan.pdf")
        for key in ("pages", "characters")
    )
    counts.extend(d["provider"][name] for name in ("candidate_count", "forged_replay_exit"))
    counts.extend(
        d["override"][name]
        for name in (
            "changes",
            "query_matches",
            "stale_override_exit",
            "execution_events",
            "accepted_claims",
        )
    )
    check(
        all(type(count) is int and count >= 0 for count in counts),
        "Outcome counts must be nonnegative integers",
    )
    check(
        c["offline_assertions"] > 0
        and c["indexed_runs"] > 0
        and c["inspected_claims"] == c["offline_assertions"],
        "Incomplete offline index/inspection",
    )
    check(
        c["required_formal_exit"] == 3
        and c["required_formal_status"] == "UNAVAILABLE"
        and c["model_events"] == c["execution_events"] == 0,
        "Required unavailable-formal contract",
    )
    check(
        {"report.json", "report.md", "report.html", "results.sarif"} <= set(c["report_files"]),
        "Missing report format",
    )
    check(
        d["source_artifacts"] >= 3
        and d["resolved_citations"] > 0
        and d["resolved_macro_uses"] > 0
        and d["ambiguous_proof_preserved"] is True,
        "Missing source scope/citation/proof behavior",
    )
    check(
        d["pdf"]["born_digital.pdf"]["characters"] > 0
        and all(d["pdf"][name]["pages"] > 0 for name in ("born_digital.pdf", "scan.pdf"))
        and "NEEDS_OCR" in d["pdf"]["scan.pdf"]["finding_codes"],
        "Missing real PDF outcomes",
    )
    p, o = d["provider"], d["override"]
    candidate_ids = p["candidate_ids"]
    check(
        isinstance(candidate_ids, list) and all(isinstance(ident, str) for ident in candidate_ids),
        "Malformed candidate identifiers",
    )
    for ident in candidate_ids:
        require_digest(ident)
    check(
        p["candidate_count"] == len(candidate_ids) == len(set(candidate_ids)),
        "Candidate count/identifier mismatch",
    )
    check(
        p["kind"] == "LOCAL_HTTP_TEST_DOUBLE"
        and bool(p["requests"])
        and p["candidate_count"] > 0
        and p["candidate_ids"] == p["replayed_candidate_ids"]
        and p["forged_replay_exit"] == 3
        and p["authority"] == "MODEL_SUGGESTION",
        "Missing anchored protocol/replay outcomes",
    )
    check(
        o["changes"] == 3
        and o["original_run"] != o["derived_run"]
        and o["original_graph"] != o["derived_graph"]
        and o["raw_ir_digest"] == o["derived_raw_ir_digest"]
        and o["query_matches"] == 1
        and o["stale_override_exit"] == 2
        and o["attribution_authenticated"] is False
        and o["execution_events"] == o["accepted_claims"] == 0,
        "Missing immutable override/authority outcomes",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    args = parser.parse_args()
    result = run_scenarios(args.fixtures.resolve(), args.work.resolve(), wheel=args.wheel.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({"profile": result["profile"], "scenarios": ["C", "D"], "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
