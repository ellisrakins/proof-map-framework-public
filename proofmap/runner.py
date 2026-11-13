"""Bounded offline Linux-container runner. No host fallback for untrusted code."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Limits:
    seconds: int = 30
    memory_mb: int = 512
    cpus: int = 1
    pids: int = 64
    output_bytes: int = 1_000_000
    temp_mb: int = 32

    def validate(self) -> None:
        for name, maximum in (
            ("seconds", 300),
            ("memory_mb", 4096),
            ("cpus", 4),
            ("pids", 256),
            ("output_bytes", 4_000_000),
            ("temp_mb", 128),
        ):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("RUNNER_LIMIT: " + name)


@dataclass(frozen=True)
class RunResult:
    execution_status: str
    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    image: str
    limits: Limits
    isolation: str = "linux-container-offline-v1"


def command(
    image: str, source: Path, argv: tuple[str, ...], name: str, limits: Limits
) -> list[str]:
    limits.validate()
    if not re.fullmatch(r"(?:[a-zA-Z0-9./:_-]+@)?sha256:[a-f0-9]{64}", image):
        raise ValueError("RUNNER_IMAGE_MUST_BE_DIGEST_PINNED")
    if not source.is_dir() or source.is_symlink() or "," in str(source):
        raise ValueError("RUNNER_SOURCE_DIRECTORY")
    if not argv or not all(isinstance(x, str) and "\x00" not in x for x in argv):
        raise ValueError("RUNNER_ARGV")
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--pull=never",
        "--network=none",
        "--user=65534:65534",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        f"--cpus={limits.cpus}",
        f"--memory={limits.memory_mb}m",
        f"--memory-swap={limits.memory_mb}m",
        f"--pids-limit={limits.pids}",
        "--ulimit",
        f"fsize={limits.temp_mb * 1024 * 1024}",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,size={limits.temp_mb}m",
        "--workdir=/src",
        "--env=HOME=/tmp",
        "--env=PATH=/usr/local/bin:/usr/bin:/bin",
        "--mount",
        f"type=bind,src={source.resolve()},dst=/src,readonly",
        image,
        *argv,
    ]


def run(
    image: str,
    source: Path,
    argv: tuple[str, ...],
    limits: Limits | None = None,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> RunResult:
    limits = limits or Limits()
    name = "proofmap-" + uuid.uuid4().hex
    args = command(image, source, argv, name, limits)
    started = time.monotonic()
    if cancelled is not None and cancelled():
        return RunResult("CANCELLED", None, "", "Cancelled before dispatch", 0, image, limits)
    if shutil.which("docker") is None:
        return RunResult(
            "UNAVAILABLE", None, "", "Docker unavailable; host fallback forbidden", 0, image, limits
        )
    # Host secrets are not passed through; Docker socket is never mounted.
    env = {
        key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if key in os.environ
    }
    try:
        probe = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{.Os}}"],
            env=env,
            capture_output=True,
            timeout=min(limits.seconds, 15),
            check=False,
        )
        if probe.returncode or probe.stdout.strip() != b"linux":
            return RunResult(
                "UNAVAILABLE", None, "", "Pinned Linux image not acquired locally", 0, image, limits
            )
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return RunResult("UNAVAILABLE", None, "", type(exc).__name__, 0, image, limits)
    output: list[bytearray] = [bytearray(), bytearray()]
    exceeded = threading.Event()
    output_lock = threading.Lock()

    def read(stream: object, index: int) -> None:
        # Runtime streams are binary pipes; retain at most the configured cap.
        assert hasattr(stream, "read")
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            with output_lock:
                remaining = limits.output_bytes - sum(map(len, output))
                output[index].extend(chunk[: max(0, remaining)])
                if len(chunk) > remaining:
                    exceeded.set()
                    break

    threads = [
        threading.Thread(target=read, args=(stream, i), daemon=True)
        for i, stream in enumerate((process.stdout, process.stderr))
    ]
    for thread in threads:
        thread.start()
    status = "PASS"
    try:
        while process.poll() is None:
            if cancelled is not None and cancelled():
                status = "CANCELLED"
                break
            if exceeded.is_set() or time.monotonic() - started > limits.seconds:
                status = "ERROR" if exceeded.is_set() else "TIMEOUT"
                break
            time.sleep(0.02)
    finally:
        if process.poll() is None:
            # Kill the whole container, not just its client process/one child.
            try:
                killed = subprocess.run(
                    ["docker", "kill", name], env=env, capture_output=True, timeout=15, check=False
                )
                if killed.returncode:
                    status = "ERROR"
            except (OSError, subprocess.SubprocessError):
                status = "ERROR"
            finally:
                process.kill()
        try:
            process.wait(timeout=15)
        except subprocess.SubprocessError:
            status = "ERROR"
        for thread in threads:
            thread.join(timeout=2)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
    if exceeded.is_set():
        status = "ERROR"
    elif process.returncode and status == "PASS":
        status = "FAIL"
    return RunResult(
        status,
        process.returncode,
        output[0].decode("utf-8", errors="replace"),
        output[1].decode("utf-8", errors="replace"),
        time.monotonic() - started,
        image,
        limits,
    )
