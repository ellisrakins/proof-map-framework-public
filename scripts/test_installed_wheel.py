"""Run the full regression suite once against a wheel, outside the source checkout.

The launcher only stages test material and installs dependencies. The isolated
worker imports the product exclusively from the fresh environment's site-packages.
"""

from __future__ import annotations

import argparse
import ast
import ctypes
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import venv
import zipfile
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from email.parser import BytesParser
from importlib import metadata, util
from pathlib import Path, PurePosixPath
from typing import Any


class ProcessTreeTimeout(subprocess.TimeoutExpired):
    """Keep the execution deadline as the primary failure after process cleanup."""

    def __init__(self, command: list[str], timeout: float, cleanup_errors: list[str]) -> None:
        super().__init__(command, timeout)
        self.cleanup_errors = cleanup_errors


def _windows_error() -> OSError:
    if sys.platform == "win32":
        return ctypes.WinError(ctypes.get_last_error())
    return OSError("Windows process ownership is unavailable on this platform")


class _WindowsJob:
    """Own Windows descendants until they terminate, including loaded extension DLLs."""

    handle: Any

    def __init__(self) -> None:
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64),
                ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD),
                ("minimum_working_set", ctypes.c_size_t),
                ("maximum_working_set", ctypes.c_size_t),
                ("active_process_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling_class", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "read_ops",
                    "write_ops",
                    "other_ops",
                    "read_bytes",
                    "write_bytes",
                    "other_bytes",
                )
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits),
                ("io", IoCounters),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t),
                ("peak_job_memory", ctypes.c_size_t),
            ]

        self.api: Any
        if sys.platform == "win32":
            self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        else:
            raise _windows_error()
        prototypes = {
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
        for name, (arguments, result) in prototypes.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise _windows_error()
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = _windows_error()
            self.close()
            raise error

    def assign(self, pid: int) -> None:
        process = self.api.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
        if not process:
            raise _windows_error()
        try:
            if not self.api.AssignProcessToJobObject(self.handle, process):
                raise _windows_error()
        finally:
            self.api.CloseHandle(process)

    def stop(self) -> None:
        from ctypes import wintypes

        class Accounting(ctypes.Structure):
            _fields_ = [
                ("user_time", ctypes.c_int64),
                ("kernel_time", ctypes.c_int64),
                ("period_user_time", ctypes.c_int64),
                ("period_kernel_time", ctypes.c_int64),
                ("page_faults", wintypes.DWORD),
                ("total_processes", wintypes.DWORD),
                ("active_processes", wintypes.DWORD),
                ("terminated_processes", wintypes.DWORD),
            ]

        if not self.api.TerminateJobObject(self.handle, 1):
            raise _windows_error()
        deadline = time.monotonic() + 30
        while True:
            accounting = Accounting()
            if not self.api.QueryInformationJobObject(
                self.handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None
            ):
                raise _windows_error()
            if accounting.active_processes == 0:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "Windows job descendants did not terminate within cleanup deadline"
                )
            time.sleep(0.05)

    def close(self) -> None:
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def _stop_process_tree(process: subprocess.Popen[bytes], job: _WindowsJob | None) -> list[str]:
    errors = []
    if sys.platform == "win32":
        # Kill the live parent tree before waiting for/reaping the direct child.
        # This also covers a venv launcher child created just before job assignment.
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=30,
            )
            if result.returncode and process.poll() is None:
                errors.append("taskkill: " + result.stderr.decode(errors="replace").strip())
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append("taskkill: " + str(exc))
        if job is not None:
            try:
                job.stop()
            except OSError as exc:
                errors.append("Windows job cleanup: " + str(exc))
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            errors.append("process group cleanup: " + str(exc))
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=30)
            errors.append("Direct child needed fallback termination")
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append("Direct child cleanup: " + str(exc))
    except OSError as exc:
        errors.append("Direct child wait: " + str(exc))
    return errors


def run_process_tree(command: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> int:
    """Wait with the existing deadline; stop descendants before environment cleanup."""
    job = _WindowsJob() if os.name == "nt" else None
    process: subprocess.Popen[bytes] | None = None
    primary: BaseException | None = None
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=os.name != "nt")
        try:
            if job is not None:
                job.assign(process.pid)
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            errors = _stop_process_tree(process, job)
            raise ProcessTreeTimeout(command, timeout, errors) from exc
        except BaseException:
            _stop_process_tree(process, job)
            raise
    except BaseException as exc:
        primary = exc
        raise
    finally:
        if job is not None:
            try:
                # A successful parent may still have orphaned children. Release
                # their DLL handles before deleting the environment as well.
                job.stop()
            except OSError as exc:
                if primary is None:
                    raise
                if isinstance(primary, ProcessTreeTimeout):
                    primary.cleanup_errors.append("Final Windows job cleanup: " + str(exc))
                print("Process cleanup also failed: " + str(exc), file=sys.stderr)
            finally:
                job.close()


@contextmanager
def temporary_workspace(out: Path) -> Iterator[Path]:
    temporary = tempfile.TemporaryDirectory(prefix="proofmap-installed-regression-")
    root = Path(temporary.name).resolve()
    primary: BaseException | None = None
    try:
        yield root
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            require(Path(temporary.name).resolve() == root, "temporary cleanup target changed")
            temporary.cleanup()
        except (OSError, ValueError) as exc:
            if primary is None:
                raise
            # Preserve the timeout/worker failure even if an external lock still
            # prevents deletion. Keep the path and secondary failure inspectable.
            try:
                write_json(
                    out / "cleanup-failure.json",
                    {
                        "status": "FAIL",
                        "temporary_path": str(root),
                        "primary_error": str(primary),
                        "cleanup_error": str(exc),
                    },
                )
            except OSError as diagnostic_error:
                print(
                    "Cleanup diagnostic could not be written: " + str(diagnostic_error),
                    file=sys.stderr,
                )
            print("Temporary cleanup also failed: " + str(exc), file=sys.stderr)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError("INSTALLED_REGRESSION: " + message)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


def source_snapshot(root: Path) -> list[dict[str, str]]:
    """Use the evidence plugin's exact tracked/dirty/untracked identity algorithm."""
    names = set(
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
    )
    result = []
    for raw in sorted(names):
        if not raw:
            continue
        name = os.fsdecode(raw)
        path = root / name
        if path.is_symlink():
            result.append(
                {"path": name, "kind": "symlink", "sha256": sha(os.fsencode(os.readlink(path)))}
            )
        elif not path.exists():
            result.append({"path": name, "kind": "missing"})
        else:
            require(path.is_file(), "unsupported source entry " + name)
            result.append({"path": name, "kind": "file", "sha256": sha(path.read_bytes())})
    require(bool(result), "empty source snapshot")
    return result


def safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    require(
        bool(name)
        and not path.is_absolute()
        and "\\" not in name
        and all(part not in {"", ".", ".."} and ":" not in part for part in name.split("/")),
        "unsafe material path",
    )
    return path


def stage_material(root: Path, stage: Path, snapshot: list[dict[str, str]]) -> list[dict[str, str]]:
    require(not stage.exists(), "staging directory must be new")
    stage.mkdir(parents=True)
    selected = []
    for row in snapshot:
        name = safe_relative(row["path"])
        if name.parts[0] in {"proofmap", ".git"} or row["kind"] == "missing":
            continue
        require(row["kind"] == "file", "staged symlinks are unsupported")
        source, target = root / name, stage / name
        require(source.resolve().is_relative_to(root), "material escapes source root")
        require(sha(source.read_bytes()) == row["sha256"], "source changed before copy")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        selected.append(dict(row))
    require(bool(selected), "no staged test material")
    verify_material(stage, selected)
    return selected


def verify_material(stage: Path, material: list[dict[str, str]]) -> dict[str, Any]:
    require(not (stage / "proofmap").exists(), "checkout product package present in staging")
    require(not (stage / ".git").exists(), "checkout Git metadata present in staging")
    for row in material:
        path = stage / safe_relative(row["path"])
        require(
            path.is_file()
            and not path.is_symlink()
            and path.resolve().is_relative_to(stage)
            and sha(path.read_bytes()) == row["sha256"],
            "staged material changed: " + row["path"],
        )
    return {"sha256": sha(canonical(material)), "file_count": len(material)}


def wheel_material(wheel: Path) -> tuple[str, dict[str, bytes]]:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "duplicate wheel entry")
        for name in names:
            safe_relative(name.rstrip("/"))
        metas = [name for name in names if name.endswith(".dist-info/METADATA")]
        require(len(metas) == 1, "one distribution metadata record required")
        value = BytesParser().parsebytes(archive.read(metas[0]))
        require(value["Name"] == "proof-map-boundary-analysis", "unexpected distribution")
        version = value["Version"]
        require(isinstance(version, str) and bool(version), "missing wheel version")
        files = {
            name: archive.read(name)
            for name in names
            if name.startswith("proofmap/") and not name.endswith("/")
        }
        require("proofmap/__init__.py" in files, "wheel package missing")
        return str(version), files


def package_material(snapshot: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row for row in snapshot if row["path"].startswith("proofmap/") and row["kind"] == "file"
    ]


def verify_wheel_source(wheel: Path, root: Path, snapshot: list[dict[str, str]]) -> str:
    version, files = wheel_material(wheel)
    expected = {row["path"]: row["sha256"] for row in package_material(snapshot)}
    require(set(files) == set(expected), "wheel/source package file inventory differs")
    require(all(sha(raw) == expected[name] for name, raw in files.items()), "stale wheel bytes")
    project = re.search(
        r"(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)",
        (root / "pyproject.toml").read_text(encoding="utf-8"),
    )
    literal = re.search(r"(?m)^version\s*=\s*([\"'][^\n]+?[\"'])", project[1] if project else "")
    require(literal is not None, "static source package version required")
    assert literal is not None
    require(ast.literal_eval(literal[1]) == version, "source/wheel version mismatch")
    return version


def verify_installed(wheel: Path, source: Path, stage: Path) -> dict[str, Any]:
    version, files = wheel_material(wheel)
    # Resolve the package without executing it before pytest-cov starts. Loading
    # product modules here would silently lose import-time coverage in the suite.
    spec = util.find_spec("proofmap")
    require(spec is not None and isinstance(spec.origin, str), "installed package not resolvable")
    assert spec is not None and isinstance(spec.origin, str)
    package = Path(spec.origin).resolve()
    installed_root = package.parent.parent
    require(
        package.is_relative_to(Path(sys.prefix).resolve()), "product is outside fresh environment"
    )
    require(not package.is_relative_to(source), "product imported from checkout")
    require(not package.is_relative_to(stage), "product imported from staged test material")
    require(
        metadata.version("proof-map-boundary-analysis") == version, "installed version mismatch"
    )
    actual = {
        path.relative_to(installed_root).as_posix()
        for path in package.parent.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    require(actual == set(files), "installed package file inventory differs")
    for name, raw in files.items():
        path = installed_root / name
        require(
            not path.is_symlink() and path.read_bytes() == raw, "installed file differs: " + name
        )
    loaded = {}
    for name, module in tuple(sys.modules.items()):
        if name == "proofmap" or name.startswith("proofmap."):
            origin = getattr(module, "__file__", None)
            require(isinstance(origin, str), "product module lacks file origin: " + name)
            assert isinstance(origin, str)
            path = Path(origin).resolve()
            require(path.is_relative_to(package.parent), "foreign product module: " + name)
            require(
                path.relative_to(installed_root).as_posix() in files, "unpackaged module: " + name
            )
            loaded[name] = path.as_posix()
    rows = [
        {"path": name, "kind": "file", "sha256": sha(raw)} for name, raw in sorted(files.items())
    ]
    return {
        "package_version": version,
        "package_path": package.as_posix(),
        "environment_path": Path(sys.prefix).resolve().as_posix(),
        "verified_file_count": len(files),
        "package_material_sha256": sha(canonical(rows)),
        "module_origins": loaded,
    }


def summarize_tests(evidence: dict[str, Any]) -> dict[str, Any]:
    rows = evidence.get("tests")
    require(isinstance(rows, list) and bool(rows), "no observed regression tests")
    assert isinstance(rows, list)
    nodeids = [row["nodeid"] for row in rows]
    require(len(nodeids) == len(set(nodeids)), "duplicate observed regression tests")
    require(all(name.startswith("tests/") for name in nodeids), "non-source-relative test identity")
    allowed = {"passed", "failed", "error", "skipped", "xfailed", "xpassed"}
    require(all(row["outcome"] in allowed for row in rows), "unknown pytest outcome")
    counts = Counter(row["outcome"] for row in rows)
    return {"collected": len(rows), "outcomes": {name: counts[name] for name in sorted(allowed)}}


def validate_outcomes(
    value: dict[str, Any], expected_identity: dict[str, Any] | None = None
) -> None:
    """Validate substantive installed results; never substitute this for a producer."""
    require(
        value["schema_version"] == "1.0"
        and value["kind"] == "INSTALLED_REGRESSION_OUTCOMES"
        and value["status"] == "PASS"
        and value["profile"] == "installed-regression",
        "installed regression result required",
    )
    require(
        value["outside_checkout"] is True and value["isolated_python"] is True, "isolation flags"
    )
    snapshot = value["source_material"]
    require(isinstance(snapshot, list) and bool(snapshot), "empty source material")
    paths = [row["path"] for row in snapshot]
    require(paths == sorted(set(paths)), "source material ordering or duplication")
    for row in snapshot:
        safe_relative(row["path"])
        require(row["kind"] in {"file", "symlink", "missing"}, "source material kind")
        if row["kind"] != "missing":
            require(bool(re.fullmatch(r"[a-f0-9]{64}", row["sha256"])), "material hash")
    require(sha(canonical(snapshot)) == value["source_fingerprint"], "source material identity")
    require(value["source_fingerprint_after"] == value["source_fingerprint"], "source drift")
    require(bool(re.fullmatch(r"[a-f0-9]{64}", value["wheel_sha256"])), "wheel digest")
    require(value["wheel_sha256_after"] == value["wheel_sha256"], "wheel drift")
    package_rows = package_material(snapshot)
    require(bool(package_rows), "no source package files")
    package_digest = sha(canonical(package_rows))
    require(value["source_package_material_sha256"] == package_digest, "source package material")
    require(
        value["wheel_package_material_sha256"] == package_digest, "wheel/source material mismatch"
    )
    staged = [
        row
        for row in snapshot
        if PurePosixPath(row["path"]).parts[0] not in {"proofmap", ".git"}
        and row["kind"] != "missing"
    ]
    require(bool(staged) and all(row["kind"] == "file" for row in staged), "staged material kinds")
    wanted_stage = {"sha256": sha(canonical(staged)), "file_count": len(staged)}
    require(
        value["staged_material"] == wanted_stage == value["staged_material_after"], "staging drift"
    )
    require(type(value["staged_material"]["file_count"]) is int, "staged count type")
    source, stage = (PurePosixPath(value[name]) for name in ("source_path", "stage_path"))
    require(not stage.is_relative_to(source), "staging within checkout")
    for key in ("installed_before", "installed_after"):
        row = value[key]
        package, environment = (
            PurePosixPath(row["package_path"]),
            PurePosixPath(row["environment_path"]),
        )
        require(
            package.is_relative_to(environment)
            and "site-packages" in package.parts
            and not package.is_relative_to(source)
            and not package.is_relative_to(stage),
            "installed origin is not isolated site-packages",
        )
        require(row["package_version"] == value["package_version"], "installed version drift")
        require(
            type(row["verified_file_count"]) is int
            and row["verified_file_count"] == len(package_rows)
            and row["package_material_sha256"] == package_digest,
            "installed/source package material mismatch",
        )
        if key == "installed_after":
            require(bool(row["module_origins"]), "no observed module origins")
        for name, origin in row["module_origins"].items():
            require(name == "proofmap" or name.startswith("proofmap."), "nonproduct origin")
            path = PurePosixPath(origin)
            require(path.is_relative_to(package.parent), "checkout module origin")
            require(
                path.relative_to(package.parent.parent).as_posix()
                in {r["path"] for r in package_rows},
                "unpackaged module origin",
            )
    before, after = value["installed_before"], value["installed_after"]
    require(before["package_path"] == after["package_path"], "installed location changed")
    report = value["pytest_evidence"]
    require(
        report["schema_version"] == "1.0"
        and report["kind"] == "pytest"
        and report["job"] == "python-tests"
        and report["profile"] == value["pytest_profile"]
        and report["status"] == "PASS"
        and type(report["exit_code"]) is int
        and report["exit_code"] == 0,
        "nested observed pytest evidence",
    )
    require(
        report["identity"]["source_fingerprint"] == value["source_fingerprint"],
        "pytest source binding",
    )
    require(
        report["identity"]["package_version"] == value["package_version"], "pytest version binding"
    )
    if expected_identity is not None:
        require(
            report["identity"] == expected_identity, "nested pytest identity differs from producer"
        )
    require(
        sha(canonical(report) + b"\n") == value["pytest_evidence_sha256"], "nested pytest bytes"
    )
    summary = summarize_tests(report)
    require(
        value["tests"] == summary and type(value["tests"]["collected"]) is int,
        "observed test counts",
    )
    require(all(type(n) is int for n in value["tests"]["outcomes"].values()), "outcome count type")
    require(
        summary["outcomes"]["passed"] > 0
        and not summary["outcomes"]["failed"]
        and not summary["outcomes"]["error"],
        "failed or empty suite",
    )
    require(
        type(value["pytest_exit_code"]) is int and value["pytest_exit_code"] == 0, "pytest failure"
    )
    require(value["full_suite"] is True and value["test_selection"] == ["tests"], "filtered suite")
    require(bool(re.fullmatch(r"[a-f0-9]{64}", value["coverage_sha256"])), "coverage digest")


def worker(request_path: Path) -> int:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    source, stage, wheel = (Path(request[name]).resolve() for name in ("source", "stage", "wheel"))
    out = Path(request["out"]).resolve()
    require(Path.cwd().resolve() == stage, "worker must execute outside checkout in staged cwd")
    require(not stage.is_relative_to(source), "staging inside checkout")
    require(sys.flags.isolated == 1, "worker must use Python isolated mode")
    # Only data/scripts/tests are added. There is deliberately no proofmap here.
    sys.path.insert(0, str(stage))
    require(
        not any(Path(p).resolve().is_relative_to(source) for p in sys.path if p),
        "checkout import route present",
    )
    before = verify_installed(wheel, source, stage)
    wheel_before = sha(wheel.read_bytes())
    material_before = verify_material(stage, request["material"])
    verify_wheel_source(wheel, source, request["source_material"])
    import pytest

    evidence = out / "pytest-evidence.json"
    coverage = out / "coverage.json"
    arguments = [
        "-p",
        "scripts.alpha_evidence",
        "--alpha-source-root",
        str(source),
        "--alpha-evidence",
        str(evidence),
        "--alpha-job",
        "python-tests",
        "--alpha-profile",
        request["profile"],
        "--rootdir",
        str(stage),
        "--basetemp",
        str(stage.parent / "pytest-temporary"),
        "-o",
        "pythonpath=" + str(stage),
        "-q",
        "--cov=proofmap",
        "--cov-branch",
        "--cov-fail-under=85",
        "--cov-report=json:" + str(coverage),
        "tests",
    ]
    code = int(pytest.main(arguments))
    after = verify_installed(wheel, source, stage)
    material_after = verify_material(stage, request["material"])
    after_snapshot = source_snapshot(source)
    report = json.loads(evidence.read_text(encoding="utf-8"))
    summary = summarize_tests(report)
    require(
        report["identity"]["source_fingerprint"] == request["source_fingerprint"],
        "source identity changed",
    )
    require(coverage.is_file(), "coverage artifact missing")
    result = {
        "schema_version": "1.0",
        "kind": "INSTALLED_REGRESSION_OUTCOMES",
        "status": "PASS" if code == 0 and report["status"] == "PASS" else "FAIL",
        "profile": "installed-regression",
        "pytest_profile": request["profile"],
        "source_fingerprint": request["source_fingerprint"],
        "source_fingerprint_after": sha(canonical(after_snapshot)),
        "source_material": request["source_material"],
        "source_package_material_sha256": sha(
            canonical(package_material(request["source_material"]))
        ),
        "wheel_package_material_sha256": before["package_material_sha256"],
        "wheel_sha256": wheel_before,
        "package_version": before["package_version"],
        "wheel_sha256_after": sha(wheel.read_bytes()),
        "outside_checkout": True,
        "isolated_python": True,
        "source_path": source.as_posix(),
        "stage_path": stage.as_posix(),
        "staged_material": material_before,
        "staged_material_after": material_after,
        "installed_before": before,
        "installed_after": after,
        "pytest_exit_code": code,
        "tests": summary,
        "pytest_evidence": report,
        "full_suite": True,
        "test_selection": ["tests"],
        "pytest_evidence_sha256": sha(evidence.read_bytes()),
        "coverage_sha256": sha(coverage.read_bytes()),
    }
    write_json(out / "outcomes.json", result)
    if result["status"] == "PASS":
        validate_outcomes(result)
    return code


def run_suite(source: Path, wheel: Path, out: Path, profile: str, coverage_out: Path | None) -> int:
    source, wheel, out = source.resolve(strict=True), wheel.resolve(strict=True), out.resolve()
    require(profile.startswith("python-"), "explicit matrix profile required")
    snapshot = source_snapshot(source)
    fingerprint = sha(canonical(snapshot))
    wheel_fingerprint = sha(wheel.read_bytes())
    verify_wheel_source(wheel, source, snapshot)
    out.mkdir(parents=True, exist_ok=True)
    require(
        not (out / "pytest-evidence.json").exists() and not (out / "outcomes.json").exists(),
        "fresh regression output directory required",
    )
    with temporary_workspace(out) as root:
        require(not root.is_relative_to(source), "temporary directory is inside checkout")
        stage = root / "material"
        material = stage_material(source, stage, snapshot)
        copied_wheel = root / wheel.name
        shutil.copyfile(wheel, copied_wheel)
        env_dir = root / "env"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        env = os.environ.copy()
        for name in ("PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS"):
            env.pop(name, None)
        install_command = [
            str(python),
            "-I",
            "-m",
            "pip",
            "install",
            "-c",
            str(stage / "constraints-ci.txt"),
            str(copied_wheel) + "[test,paper,trust,dev]",
            "types-jsonschema",
        ]
        install_code = run_process_tree(install_command, cwd=root, env=env, timeout=600)
        if install_code:
            raise subprocess.CalledProcessError(install_code, install_command)
        request = root / "request.json"
        write_json(
            request,
            {
                "source": str(source),
                "stage": str(stage),
                "wheel": str(copied_wheel),
                "out": str(out),
                "profile": profile,
                "source_fingerprint": fingerprint,
                "material": material,
                "source_material": snapshot,
            },
        )
        worker_path = stage / "scripts/test_installed_wheel.py"
        code = run_process_tree(
            [str(python), "-I", str(worker_path), "--worker", str(request)],
            cwd=stage,
            env=env,
            timeout=900,
        )
        require(
            source_snapshot(source) == snapshot, "source changed during installed qualification"
        )
        verify_material(stage, material)
        require(
            sha(wheel.read_bytes()) == wheel_fingerprint == sha(copied_wheel.read_bytes()),
            "wheel changed during run",
        )
    if coverage_out is not None and (out / "coverage.json").exists():
        coverage_out = coverage_out.resolve()
        coverage_out.parent.mkdir(parents=True, exist_ok=True)
        if coverage_out != out / "coverage.json":
            shutil.copyfile(out / "coverage.json", coverage_out)
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--coverage-out", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.worker:
            return worker(args.worker)
        require(
            args.wheel is not None and args.out is not None and args.profile is not None,
            "--wheel, --out and --profile are required",
        )
        return run_suite(args.source_root, args.wheel, args.out, args.profile, args.coverage_out)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        if args.out:
            failure: dict[str, Any] = {
                "status": "FAIL",
                "error": str(exc),
                "type": type(exc).__name__,
            }
            if isinstance(exc, subprocess.TimeoutExpired):
                failure.update(command=exc.cmd, timeout_seconds=exc.timeout)
            if isinstance(exc, ProcessTreeTimeout):
                failure["process_tree_cleanup"] = {
                    "completed": not exc.cleanup_errors,
                    "errors": exc.cleanup_errors,
                }
            write_json(args.out / "launcher-failure.json", failure)
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
