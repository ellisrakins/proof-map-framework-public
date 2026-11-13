"""Trusted, restricted-source worker; copied by the controller into a read-only snapshot.

This module deliberately uses the standard library only. No submitted Python,
Lean modules, compiled libraries or project hooks are loaded. A fresh second
Lean process reconstructs the exact proposition; compiled output is not imported.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Library symlink unsupported")
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def main() -> int:
    request = json.loads(Path("/src/request.json").read_text(encoding="utf-8"))
    profile = request["profile"]
    executable = "/opt/lean/bin/lean"
    env = {
        "PATH": "/opt/lean/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "LEAN_PATH": "/opt/lean/lib/lean",
        "LEAN_SYSROOT": "/opt/lean",
    }
    version = subprocess.run(
        [executable, "--version"], capture_output=True, check=True, text=True, env=env, timeout=15
    ).stdout.strip()
    actual = {
        "lean_sha256": hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
        "library_digest": tree_digest(Path("/opt/lean/lib/lean")),
        "checker_digest": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "version": version,
        "platform": "linux/"
        + {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), "unsupported"),
        "executable": executable,
        "search_path": env["LEAN_PATH"],
    }
    if (
        any(
            actual[key] != profile[key]
            for key in (
                "lean_sha256",
                "library_digest",
                "checker_digest",
                "platform",
                "executable",
                "search_path",
            )
        )
        or "version 4.30.0," not in version
    ):
        print(json.dumps({"outcome": "MATERIAL_MISMATCH", "actual": actual}))
        return 2
    results = {}
    for name in ("Candidate", "Recheck"):
        process = subprocess.run(
            [executable, "/src/" + name + ".lean"],
            capture_output=True,
            check=False,
            text=True,
            env=env,
            timeout=profile["limits"]["seconds"],
        )
        results[name] = {
            "returncode": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
        }
        if name == "Candidate" and process.returncode:
            break
    print(json.dumps({"outcome": "CHECKED", "actual": actual, "results": results}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"outcome": "WORKER_ERROR", "error": type(exc).__name__}))
        sys.exit(2)
