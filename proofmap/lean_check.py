"""Lean compiler checks for generated proof-map scaffold files."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


def _subprocess_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


@dataclass(frozen=True)
class LeanCheckResult:
    path: Path
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _elan_lean_path() -> Path:
    exe = "lean.exe" if os.name == "nt" else "lean"
    return Path.home() / ".elan" / "bin" / exe


def resolve_lean_executable(lean_executable: str | None = None) -> str | None:
    """Resolve a Lean executable from an explicit path, PATH, or elan's default bin dir."""

    if lean_executable:
        found = shutil.which(lean_executable)
        if found:
            return found
        candidate = Path(lean_executable).expanduser()
        if candidate.exists():
            return str(candidate)
        return lean_executable

    env_value = os.environ.get("PROOFMAP_LEAN")
    if env_value:
        resolved = resolve_lean_executable(env_value)
        if resolved:
            return resolved

    found = shutil.which("lean")
    if found:
        return found

    elan_path = _elan_lean_path()
    if elan_path.exists():
        return str(elan_path)

    return None


def check_lean_file(
    path: str | Path,
    *,
    lean_executable: str | None = None,
    timeout: float = 60.0,
) -> LeanCheckResult:
    """Run Lean on one file and return the compiler result."""

    lean = resolve_lean_executable(lean_executable)
    if lean is None:
        raise FileNotFoundError(
            "Lean executable not found. Install elan/Lean or set PROOFMAP_LEAN."
        )

    lean_path = Path(path).resolve()
    command = [lean, str(lean_path)]
    try:
        completed = subprocess.run(
            command,
            cwd=str(lean_path.parent),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _subprocess_text(exc.stdout)
        stderr = _subprocess_text(exc.stderr)
        return LeanCheckResult(
            path=lean_path,
            command=command,
            returncode=-1,
            stdout=stdout,
            stderr=stderr + f"\nLean check timed out after {timeout:g}s.",
        )

    return LeanCheckResult(
        path=lean_path,
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def check_lean_files(
    paths: list[str | Path],
    *,
    lean_executable: str | None = None,
    timeout: float = 60.0,
) -> list[LeanCheckResult]:
    """Run Lean over multiple files, preserving input order."""

    lean = resolve_lean_executable(lean_executable)
    if lean is None:
        raise FileNotFoundError(
            "Lean executable not found. Install elan/Lean or set PROOFMAP_LEAN."
        )
    return [check_lean_file(path, lean_executable=lean, timeout=timeout) for path in paths]
