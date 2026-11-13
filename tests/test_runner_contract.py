"""Process-controller unit tests. These do not replace the real Linux job."""

import io
from types import SimpleNamespace

import pytest

from proofmap.runner import Limits, command, run

IMAGE = "python@sha256:" + "a" * 64


@pytest.mark.parametrize(
    "case",
    [
        "success",
        "failure",
        "timeout",
        "output",
        "preflight",
        "oserror",
        "kill_error",
        "both_output",
        "wait_error",
    ],
)
def test_controller_contract(tmp_path, monkeypatch, case):
    monkeypatch.setattr("proofmap.runner.shutil.which", lambda _: "docker")

    class Process:
        stdout = io.BytesIO(b"x" * (200 if case == "output" else 1))
        stderr = io.BytesIO(b"x" * 100 if case == "both_output" else b"")
        returncode = None if case in {"timeout", "kill_error"} else 1 if case == "failure" else 0

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

        def wait(self, timeout):
            if case == "wait_error":
                import subprocess

                raise subprocess.TimeoutExpired("docker", timeout)
            return self.returncode

    process = Process()

    def subprocess_run(*args, **kwargs):
        if case == "kill_error" and args[0][1] == "kill":
            raise OSError("daemon disconnected")
        if case == "oserror":
            raise OSError("unavailable")
        return SimpleNamespace(returncode=1 if case == "preflight" else 0, stdout=b"linux\n")

    monkeypatch.setattr("proofmap.runner.subprocess.run", subprocess_run)
    monkeypatch.setattr("proofmap.runner.subprocess.Popen", lambda *args, **kwargs: process)
    if case in {"timeout", "kill_error"}:
        ticks = iter((0, 999, 1000))
        monkeypatch.setattr("proofmap.runner.time.monotonic", lambda: next(ticks))
    result = run(IMAGE, tmp_path, ("python",), Limits(output_bytes=100))
    assert (
        result.execution_status
        == {
            "success": "PASS",
            "failure": "FAIL",
            "timeout": "TIMEOUT",
            "output": "ERROR",
            "preflight": "UNAVAILABLE",
            "oserror": "UNAVAILABLE",
            "kill_error": "ERROR",
            "both_output": "ERROR",
            "wait_error": "ERROR",
        }[case]
    )
    assert len(result.stdout) + len(result.stderr) <= 100


@pytest.mark.parametrize("limits", [Limits(seconds=0), Limits(pids=True), Limits(cpus=100)])
def test_limit_validation(tmp_path, limits):
    with pytest.raises(ValueError):
        command(IMAGE, tmp_path, ("python",), "test", limits)


def test_argv_and_source_rejected(tmp_path):
    with pytest.raises(ValueError):
        command(IMAGE, tmp_path / "missing", ("python",), "test", Limits())
    with pytest.raises(ValueError):
        command(IMAGE, tmp_path, (), "test", Limits())
