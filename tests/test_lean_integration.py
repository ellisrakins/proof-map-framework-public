import subprocess
from pathlib import Path

import pytest

from proofmap.examples import build_strong_weak_interface_map
from proofmap.lean_check import check_lean_file, resolve_lean_executable
from proofmap.lean_export import lean_ident, write_lean_skeleton


def test_lean_timeout_normalizes_partial_byte_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "Timeout.lean"
    path.write_text("theorem timeout_demo : True := by trivial\n", encoding="utf-8")

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["lean-test", str(path)],
            timeout=0.01,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    monkeypatch.setattr(subprocess, "run", timeout)
    result = check_lean_file(path, lean_executable="lean-test", timeout=0.01)
    assert result.returncode == -1
    assert result.stdout == "partial stdout"
    assert "partial stderr" in result.stderr
    assert "timed out" in result.stderr


def test_lean_ident_sanitizes_proof_map_ids():
    assert lean_ident("qcd.yang-mills.mass_gap") == "qcd_yang_mills_mass_gap"
    assert lean_ident("4d.yang_mills") == "n_4d_yang_mills"


def test_generated_lean_scaffold_compiles_when_lean_is_installed(tmp_path: Path):
    lean = resolve_lean_executable()
    if lean is None:
        pytest.skip("Lean executable is not installed")

    path = tmp_path / "StrongWeakSketch.lean"
    write_lean_skeleton(build_strong_weak_interface_map(), path)
    result = check_lean_file(path, lean_executable=lean, timeout=120.0)
    assert result.ok, result.stderr or result.stdout
