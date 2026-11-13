"""Controller-owned process scopes for bounded campaign adapters.

Workers receive public adapter inputs and an acquired lease, never controller
signing keys. A Windows job or POSIX process group owns their parser descendants.
Cleanup completes before a cancelled task can publish its terminal state.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import sysconfig
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from ..integrity import canonical_bytes, strict_loads

MAX_WORKER_OUTPUT = 8_000_000
CLEANUP_SECONDS = 5


class _WindowsJob:
    def __init__(self) -> None:
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64),
                ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD),
                ("minimum", ctypes.c_size_t),
                ("maximum", ctypes.c_size_t),
                ("active", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", ctypes.c_uint64 * 6),
                ("memory", ctypes.c_size_t * 4),
            ]

        self.api: Any = ctypes.WinDLL("kernel32", use_last_error=True)
        definitions = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
                wintypes.BOOL,
            ),
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "QueryInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p],
                wintypes.BOOL,
            ),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, result) in definitions.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, pid: int) -> None:
        process = self.api.OpenProcess(0x0100 | 0x0001, False, pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.api.AssignProcessToJobObject(self.handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.api.CloseHandle(process)

    def stop(self) -> None:
        from ctypes import wintypes

        class Accounting(ctypes.Structure):
            _fields_ = [
                ("times", ctypes.c_int64 * 4),
                ("faults", wintypes.DWORD),
                ("total", wintypes.DWORD),
                ("active", wintypes.DWORD),
                ("terminated", wintypes.DWORD),
            ]

        if not self.api.TerminateJobObject(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())
        deadline = time.monotonic() + CLEANUP_SECONDS
        while True:
            state = Accounting()
            if not self.api.QueryInformationJobObject(
                self.handle, 1, ctypes.byref(state), ctypes.sizeof(state), None
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if state.active == 0:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("CAMPAIGN_WORKER_TREE_CLEANUP_TIMEOUT")
            time.sleep(0.02)

    def close(self) -> None:
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def _live_group(group: int) -> bool:
    proc = Path("/proc")
    if sys.platform.startswith("linux") and proc.is_dir():
        # Killed, unreaped zombies hold no execution or open resources.
        for entry in proc.iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                if int(fields[2]) == group and fields[0] != "Z":
                    return True
            except (OSError, ValueError, IndexError):
                continue
        return False
    try:
        posix: Any = os
        posix.killpg(group, 0)
    except ProcessLookupError:
        return False
    return True


def _stop(process: subprocess.Popen[bytes], job: _WindowsJob | None) -> None:
    if job is not None:
        job.stop()
    else:
        try:
            posix: Any = os
            posix.killpg(process.pid, getattr(signal, "SIGKILL", 9))
        except ProcessLookupError:
            pass
    process.wait(timeout=CLEANUP_SECONDS)
    if job is None:
        deadline = time.monotonic() + CLEANUP_SECONDS
        while _live_group(process.pid):
            if time.monotonic() >= deadline:
                raise TimeoutError("CAMPAIGN_WORKER_TREE_CLEANUP_TIMEOUT")
            time.sleep(0.02)


def run_adapter(
    request: dict[str, Any], cancelled: Callable[[], bool], cleanup_started: Callable[[], Any]
) -> dict[str, Any]:
    """Pulse the lease through startup, work and cleanup; reject unsafe publication."""
    # The real interpreter avoids the Windows venv launcher's pre-assignment
    # child race. Only this installed product and its dependency directory enter
    # the isolated interpreter's path; request data cannot select a command.
    paths = [str(Path(__file__).resolve().parents[2]), sysconfig.get_path("purelib")]
    bootstrap = (
        "import sys,site;sys.path[:0]="
        + repr(paths)
        + ";site.addsitedir("
        + repr(sysconfig.get_path("purelib"))
        + ")"
        + ";sys.executable="
        + repr(sys.executable)
        + ";from proofmap.campaign.worker import main;main()"
    )
    command = [getattr(sys, "_base_executable", sys.executable), "-I", "-c", bootstrap]
    environment = {
        name: os.environ[name]
        for name in (
            "PATH",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "COVERAGE_PROCESS_CONFIG",
            "COVERAGE_PROCESS_START",
            "COVERAGE_FILE",
        )
        if name in os.environ
    }
    job = _WindowsJob() if os.name == "nt" else None
    process: subprocess.Popen[bytes] | None = None
    stopped = False
    dispatched = False
    cleanup_error = None
    response: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="campaign-adapter-") as folder:
        directory = Path(folder)
        with (directory / "request.json").open("wb") as incoming:
            incoming.write(canonical_bytes(request))
        with (
            (directory / "output.json").open("w+b") as output,
            (directory / "errors.txt").open("w+b") as errors,
        ):
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=output,
                    stderr=errors,
                    env=environment,
                    start_new_session=os.name != "nt",
                )
                if job is not None:
                    job.assign(process.pid)
                if cancelled():
                    stopped = True
                else:
                    assert process.stdin is not None
                    # A tiny gated message follows process ownership. The large
                    # public input stays in a private temporary file.
                    process.stdin.write(str(directory / "request.json").encode("utf-8"))
                    process.stdin.close()
                    dispatched = True
                while not stopped and process.poll() is None:
                    stopped = cancelled()
                    if (
                        os.fstat(output.fileno()).st_size > MAX_WORKER_OUTPUT
                        or os.fstat(errors.fileno()).st_size > 64_000
                    ):
                        raise ValueError("CAMPAIGN_WORKER_OUTPUT_LIMIT")
                    if not stopped:
                        time.sleep(0.02)
                if not stopped:
                    output.seek(0)
                    raw = output.read(MAX_WORKER_OUTPUT + 1)
                    if len(raw) > MAX_WORKER_OUTPUT or process.returncode:
                        raise ValueError("CAMPAIGN_WORKER_FAILED")
                    decoded = strict_loads(raw)
                    if (
                        not isinstance(decoded, dict)
                        or decoded.get("state")
                        not in {"SUCCEEDED", "CHECK_FAILED", "UNAVAILABLE", "ERROR"}
                        or (
                            decoded.get("evidence") is not None
                            and not isinstance(decoded["evidence"], dict)
                        )
                        or (
                            decoded.get("error") is not None
                            and not isinstance(decoded["error"], str)
                        )
                    ):
                        raise ValueError("CAMPAIGN_WORKER_RESPONSE_INVALID")
                    response = cast(dict[str, Any], decoded)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                response = {"state": "ERROR", "error": type(exc).__name__ + ":" + str(exc)[:256]}
            finally:
                if process is not None:
                    try:
                        cleanup_started()
                        _stop(process, job)
                    except (OSError, subprocess.SubprocessError) as exc:
                        cleanup_error = type(exc).__name__ + ":" + str(exc)[:256]
                        if process.poll() is None:
                            try:
                                process.kill()
                                process.wait(timeout=CLEANUP_SECONDS)
                            except (OSError, subprocess.SubprocessError) as fallback:
                                cleanup_error += ";" + str(fallback)[:128]
                if job is not None:
                    job.close()
    if stopped or cleanup_error:
        response = {
            "state": "ERROR" if cleanup_error else "CANCELLED",
            "error": cleanup_error or "CAMPAIGN_ADAPTER_STOPPED",
            "evidence": {"runner_status": "ERROR" if cleanup_error else "CANCELLED"},
        }
    response["cleanup"] = {"completed": cleanup_error is None, "error": cleanup_error}
    response["model_effect"] = (
        "POSSIBLE_EXTERNAL_EFFECT"
        if dispatched and request["kind"] == "EXTRACT_CONFIGURED"
        else "NOT_DISPATCHED"
    )
    return response
