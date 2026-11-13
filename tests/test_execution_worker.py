"""Synthetic worker protocol tests. These are not real Lean/container checks."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from proofmap import lean_worker
from proofmap.integrity import write_json


def test_tree_material_hash_changes_for_name_content_and_addition(tmp_path):
    (tmp_path / "A.olean").write_bytes(b"first")
    first = lean_worker.tree_digest(tmp_path)
    (tmp_path / "A.olean").write_bytes(b"second")
    second = lean_worker.tree_digest(tmp_path)
    assert first != second
    (tmp_path / "A.olean").rename(tmp_path / "B.olean")
    assert lean_worker.tree_digest(tmp_path) not in {first, second}


@pytest.mark.parametrize(
    "mutation",
    ["none", "compiler-reject", "version", "compiler-hash", "library", "checker", "platform"],
)
def test_worker_resolves_exact_materials_before_lean(monkeypatch, tmp_path, capsys, mutation):
    src = tmp_path / "src"
    src.mkdir()
    lean = tmp_path / "lean"
    (lean / "bin").mkdir(parents=True)
    (lean / "lib" / "lean").mkdir(parents=True)
    (lean / "bin" / "lean").write_bytes(b"synthetic-executable")
    (lean / "lib" / "lean" / "Std.olean").write_bytes(b"synthetic-trusted-library")
    profile = {
        "lean_sha256": hashlib.sha256((lean / "bin" / "lean").read_bytes()).hexdigest(),
        "library_digest": lean_worker.tree_digest(lean / "lib" / "lean"),
        "checker_digest": hashlib.sha256(Path(lean_worker.__file__).read_bytes()).hexdigest(),
        "platform": "linux/amd64",
        "executable": "/opt/lean/bin/lean",
        "search_path": "/opt/lean/lib/lean",
        "limits": {"seconds": 120},
    }
    field = {
        "compiler-hash": "lean_sha256",
        "library": "library_digest",
        "checker": "checker_digest",
        "platform": "platform",
    }.get(mutation)
    if field:
        profile[field] = "mismatch"
    write_json(src / "request.json", {"profile": profile})

    def mapped_path(value):
        if str(value).startswith("/src/"):
            return src / str(value)[len("/src/") :]
        if str(value).startswith("/opt/lean/"):
            return lean / str(value)[len("/opt/lean/") :]
        return Path(value)

    monkeypatch.setattr(lean_worker, "Path", mapped_path)
    monkeypatch.setattr(lean_worker.platform, "machine", lambda: "x86_64")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["env"] == {
            "PATH": "/opt/lean/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "LEAN_PATH": "/opt/lean/lib/lean",
            "LEAN_SYSROOT": "/opt/lean",
        }
        if argv[-1] == "--version":
            version = "4.30.0" if mutation != "version" else "0.0.0"
            return subprocess.CompletedProcess(
                argv, 0, "Lean (version " + version + ", synthetic)", ""
            )
        code = 1 if mutation == "compiler-reject" else 0
        return subprocess.CompletedProcess(
            argv, code, "'proofmap_target' does not depend on any axioms", ""
        )

    monkeypatch.setattr(lean_worker.subprocess, "run", run)
    code = lean_worker.main()
    report = json.loads(capsys.readouterr().out)
    if mutation in {"none", "compiler-reject"}:
        assert code == 0
        assert report["outcome"] == "CHECKED"
        assert len(calls) == (3 if mutation == "none" else 2)
    else:
        assert code == 2
        assert report["outcome"] == "MATERIAL_MISMATCH"
        assert len(calls) == 1


def test_tree_symlink_unsupported_contract(tmp_path, monkeypatch):
    entry = tmp_path / "link"
    entry.write_bytes(b"material")
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == entry)
    with pytest.raises(ValueError, match="symlink"):
        lean_worker.tree_digest(tmp_path)
