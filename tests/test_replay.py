from pathlib import Path

import pytest

from proofmap.attempts import AttemptReceipt
from proofmap.cli import main
from proofmap.integrity import artifact_digest
from proofmap.replay import replay
from proofmap.runner import RunResult

CASE = Path("research/agoh_2026")
IMAGE = "lean-test@sha256:" + "a" * 64


def material(tmp_path):
    receipt = AttemptReceipt.from_json(CASE / "agoh_factorization_receipt.json")
    files = {}
    for name in ("agoh_counterexample_map.json", "agoh_factorization_candidate.lean"):
        raw = (CASE / name).read_bytes()
        (tmp_path / name).write_bytes(raw)
        files[name] = artifact_digest(raw)
    manifest = {
        "schema_version": "1.0",
        "map": "agoh_counterexample_map.json",
        "candidate": "agoh_factorization_candidate.lean",
        "files": files,
    }
    return receipt, manifest


def test_replay_mock_contract_not_execution_proof(tmp_path, monkeypatch):
    receipt, manifest = material(tmp_path)

    def fake_run(image, source, argv, limits):
        if argv[-1] == "--version":
            output = "Lean (version 4.30.0, test)"
        elif "sha256sum" in argv[0]:
            output = "a" * 64 + "  /usr/local/bin/lean"
        else:
            output = (
                receipt.obligation.declaration_name
                + " depends on axioms: [Classical.choice, Quot.sound, propext]"
            )
        return RunResult("PASS", 0, output, "", 0, image, limits)

    monkeypatch.setattr("proofmap.replay.run", fake_run)
    event = replay(receipt, tmp_path, manifest, IMAGE)
    assert event["outcome"] == "VERIFIED"
    assert event["authentication"] == "LOCAL_UNSIGNED_EVENT"
    assert event["parent_receipt"] == receipt.receipt_sha256
    assert event["semantic_invariants_match"]


def test_replay_unavailable_and_portable_paths(tmp_path, monkeypatch):
    receipt, manifest = material(tmp_path)
    monkeypatch.setattr("proofmap.runner.shutil.which", lambda _: None)
    event = replay(receipt, tmp_path, manifest, IMAGE)
    assert event["outcome"] == "UNAVAILABLE"
    assert (
        main(
            [
                "receipt-replay",
                str(CASE / "agoh_factorization_receipt.json"),
                "--artifact-root",
                str(tmp_path),
                "--out",
                str(tmp_path / "event.json"),
            ]
        )
        == 3
    )
    manifest["files"]["C:/stolen"] = "0" * 64
    with pytest.raises(ValueError, match="UNSAFE_PATH"):
        replay(receipt, tmp_path, manifest, IMAGE)


@pytest.mark.parametrize("mutation", ["hash", "schema", "missing", "executable"])
def test_replay_rejects_stale_bindings(tmp_path, mutation):
    receipt, manifest = material(tmp_path)
    executable = "/usr/local/bin/lean"
    if mutation == "hash":
        manifest["files"][manifest["candidate"]] = "0" * 64
    elif mutation == "schema":
        manifest["schema_version"] = "future"
    elif mutation == "missing":
        manifest["candidate"] = "missing"
    else:
        executable = "../lean"
    with pytest.raises(ValueError):
        replay(receipt, tmp_path, manifest, IMAGE, executable=executable)


@pytest.mark.parametrize("which", ["candidate", "map"])
def test_replay_rejects_changed_content_even_if_manifest_rehashed(tmp_path, which):
    import json

    receipt, manifest = material(tmp_path)
    path = tmp_path / manifest[which]
    if which == "candidate":
        path.write_text("by\n  sorry\n")
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["title"] = "Another map"
        path.write_text(json.dumps(data))
    manifest["files"][manifest[which]] = artifact_digest(path.read_bytes())
    with pytest.raises(ValueError, match="MISMATCH"):
        replay(receipt, tmp_path, manifest, IMAGE)


def test_replay_rejects_wrapper_and_toolchain_changes(tmp_path, monkeypatch):
    from dataclasses import replace

    receipt, manifest = material(tmp_path)
    forged = replace(
        receipt,
        verification=replace(receipt.verification, wrapper_sha256="b" * 64),
        receipt_sha256="",
    )
    with pytest.raises(ValueError, match="WRAPPER_MISMATCH"):
        replay(forged, tmp_path, manifest, IMAGE)
    monkeypatch.setattr(
        "proofmap.replay.run",
        lambda image, source, argv, limits: RunResult(
            "PASS", 0, "Lean (version 1.0.0)", "", 0, image, limits
        ),
    )
    with pytest.raises(ValueError, match="TOOLCHAIN_MISMATCH"):
        replay(receipt, tmp_path, manifest, IMAGE)
