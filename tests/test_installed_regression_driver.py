"""Installed regression provenance boundaries; synthetic records are not qualification."""

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from copy import deepcopy
from importlib.util import find_spec
from pathlib import Path

import pytest

from scripts import test_installed_wheel as driver
from scripts.alpha_evidence import _source_fingerprint


@pytest.fixture
def material(tmp_path):
    source = tmp_path / "checkout"
    source.mkdir()
    files = {
        "proofmap/__init__.py": b'"""Synthetic test package."""\n',
        "proofmap/resources/item.json": b'{"kind":"fixture"}\n',
        "pyproject.toml": b'[project]\nname = "proof-map-boundary-analysis"\nversion = "1.2.3"\n',
        "tests/test_fixture.py": b"def test_fixture(): assert True\n",
        ".gitignore": b".work/\n",
    }
    for name, raw in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    subprocess.run(["git", "init", "--quiet", str(source)], check=True, capture_output=True)
    wheel = tmp_path / "fixture.whl"
    make_wheel(wheel, files)
    return source, wheel, files


def make_wheel(wheel, files):
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, raw in files.items():
            if name.startswith("proofmap/"):
                archive.writestr(name, raw)
        archive.writestr(
            "proof_map_boundary_analysis-1.2.3.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: proof-map-boundary-analysis\nVersion: 1.2.3\n",
        )


def test_source_snapshot_matches_capture_and_stages_only_identical_test_material(
    material, tmp_path
):
    source, wheel, _ = material
    snapshot = driver.source_snapshot(source)
    assert driver.sha(driver.canonical(snapshot)) == _source_fingerprint(source)
    assert driver.verify_wheel_source(wheel, source, snapshot) == "1.2.3"
    stage = tmp_path / "stage"
    selected = driver.stage_material(source, stage, snapshot)
    assert not (stage / "proofmap").exists() and not (stage / ".git").exists()
    assert (stage / "tests/test_fixture.py").read_bytes() == (
        source / "tests/test_fixture.py"
    ).read_bytes()
    assert driver.verify_material(stage, selected)["file_count"] == 3
    (stage / "tests/test_fixture.py").write_text("def test_forged(): pass\n")
    with pytest.raises(ValueError, match="staged material changed"):
        driver.verify_material(stage, selected)


@pytest.mark.parametrize("change", ["stale", "missing", "extra", "version"])
def test_wheel_must_match_current_source_inventory_bytes_and_version(material, change):
    source, wheel, files = material
    if change == "stale":
        files["proofmap/__init__.py"] = b"old source\n"
    elif change == "missing":
        del files["proofmap/resources/item.json"]
    elif change == "extra":
        files["proofmap/extra.py"] = b"pass\n"
    else:
        (source / "pyproject.toml").write_text('[project]\nversion = "1.2.4"\n')
    make_wheel(wheel, files)
    with pytest.raises(ValueError, match="wheel|version"):
        driver.verify_wheel_source(wheel, source, driver.source_snapshot(source))


@pytest.mark.parametrize(
    "path", ["../outside", "a/../outside", "/absolute", "a\\b", "C:/outside", "a//b"]
)
def test_staging_rejects_escaping_or_ambiguous_paths(path):
    with pytest.raises(ValueError, match="unsafe material path"):
        driver.safe_relative(path)


def test_staging_rejects_source_drift_and_package_insertion(material, tmp_path):
    source, _, _ = material
    snapshot = driver.source_snapshot(source)
    (source / "tests/test_fixture.py").write_text("changed\n")
    with pytest.raises(ValueError, match="source changed before copy"):
        driver.stage_material(source, tmp_path / "stale", snapshot)
    selected = driver.stage_material(source, tmp_path / "stage", driver.source_snapshot(source))
    (tmp_path / "stage/proofmap").mkdir()
    with pytest.raises(ValueError, match="product package present"):
        driver.verify_material(tmp_path / "stage", selected)


@pytest.fixture
def observed_record(material, tmp_path):
    """A labelled synthetic envelope used only to test validation rejection paths."""
    source, wheel, _ = material
    snapshot = driver.source_snapshot(source)
    fingerprint = driver.sha(driver.canonical(snapshot))
    package_rows = driver.package_material(snapshot)
    package_digest = driver.sha(driver.canonical(package_rows))
    stage = tmp_path / "stage"
    staged = driver.stage_material(source, stage, snapshot)
    identity = {"source_fingerprint": fingerprint, "package_version": "1.2.3", "run_id": "fixture"}
    report = {
        "schema_version": "1.0",
        "kind": "pytest",
        "status": "PASS",
        "exit_code": 0,
        "job": "python-tests",
        "profile": "python-linux-3.12",
        "identity": identity,
        "tests": [
            {"nodeid": "tests/test_fixture.py::test_fixture", "outcome": "passed"},
            {"nodeid": "tests/test_fixture.py::test_optional", "outcome": "skipped"},
        ],
        "artifacts": [],
    }
    package = tmp_path / "env/lib/python3.12/site-packages/proofmap/__init__.py"
    install = {
        "package_version": "1.2.3",
        "package_path": package.as_posix(),
        "environment_path": (tmp_path / "env").as_posix(),
        "verified_file_count": len(package_rows),
        "package_material_sha256": package_digest,
        "module_origins": {"proofmap": package.as_posix()},
    }
    return {
        "schema_version": "1.0",
        "kind": "INSTALLED_REGRESSION_OUTCOMES",
        "status": "PASS",
        "profile": "installed-regression",
        "pytest_profile": "python-linux-3.12",
        "source_fingerprint": fingerprint,
        "source_fingerprint_after": fingerprint,
        "source_material": snapshot,
        "source_package_material_sha256": package_digest,
        "wheel_package_material_sha256": package_digest,
        "wheel_sha256": driver.sha(wheel.read_bytes()),
        "wheel_sha256_after": driver.sha(wheel.read_bytes()),
        "package_version": "1.2.3",
        "outside_checkout": True,
        "isolated_python": True,
        "source_path": source.as_posix(),
        "stage_path": stage.as_posix(),
        "staged_material": driver.verify_material(stage, staged),
        "staged_material_after": driver.verify_material(stage, staged),
        "installed_before": deepcopy(install),
        "installed_after": deepcopy(install),
        "pytest_exit_code": 0,
        "pytest_evidence": report,
        "pytest_evidence_sha256": driver.sha(driver.canonical(report) + b"\n"),
        "tests": driver.summarize_tests(report),
        "coverage_sha256": "a" * 64,
        "full_suite": True,
        "test_selection": ["tests"],
    }


def test_installed_outcome_validator_retains_real_outcome_dimensions(observed_record):
    driver.validate_outcomes(observed_record, observed_record["pytest_evidence"]["identity"])
    assert observed_record["tests"]["outcomes"]["skipped"] == 1
    assert observed_record["tests"]["outcomes"]["passed"] == 1
    with pytest.raises(ValueError, match="identity differs"):
        driver.validate_outcomes(observed_record, {"source_fingerprint": "0" * 64})


@pytest.mark.parametrize("case", ["same", "missing", "different"])
def test_gate_requires_separately_collected_matching_installed_pytest(
    observed_record, tmp_path, case
):
    from test_alpha_acceptance import IDENTITY, contract

    from scripts.check_alpha_acceptance import evaluate

    value = deepcopy(observed_record)
    expected = {
        **IDENTITY,
        "source_fingerprint": value["source_fingerprint"],
        "package_version": "1.2.3",
    }
    value["pytest_evidence"]["identity"] = expected
    value["pytest_evidence_sha256"] = driver.sha(driver.canonical(value["pytest_evidence"]) + b"\n")
    path = tmp_path / "outcomes.json"
    driver.write_json(path, value)
    outer = {
        "schema_version": "1.0",
        "kind": "command",
        "status": "PASS",
        "exit_code": 0,
        "job": "python-tests",
        "profile": "installed-regression",
        "identity": expected,
        "tests": [],
        "artifacts": [
            {
                "name": "installed-regression-outcomes",
                "path": path.name,
                "sha256": driver.sha(path.read_bytes()),
            }
        ],
    }
    reports = [outer]
    if case != "missing":
        separately_collected = deepcopy(value["pytest_evidence"])
        if case == "different":
            separately_collected["tests"][1]["outcome"] = "passed"
        reports.append(separately_collected)
    manifest, baseline = contract()
    result = evaluate(manifest, baseline, reports, expected, [tmp_path] * len(reports))
    assert ("INSTALLED_PYTEST_REPORT_MISSING_OR_DIFFERENT" in result["errors"]) == (case != "same")
    assert not any("INVALID_ARTIFACT" in issue for issue in result["errors"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v.update(profile="source-checkout-test"),
        lambda v: v.update(outside_checkout=False),
        lambda v: v.update(source_fingerprint_after="0" * 64),
        lambda v: v.update(wheel_package_material_sha256="0" * 64),
        lambda v: v.update(wheel_sha256_after="0" * 64),
        lambda v: v["staged_material"].update(file_count=True),
        lambda v: v["installed_after"].update(verified_file_count=True),
        lambda v: v["installed_after"].update(package_material_sha256="0" * 64),
        lambda v: v["installed_after"]["module_origins"].update(
            proofmap=v["source_path"] + "/proofmap/__init__.py"
        ),
        lambda v: v["pytest_evidence"].update(status="FAIL"),
        lambda v: v["pytest_evidence"]["identity"].update(package_version="1.2.4"),
        lambda v: v["pytest_evidence"].update(tests=[]),
        lambda v: v["tests"].update(collected=True),
        lambda v: v["tests"]["outcomes"].update(passed=True),
        lambda v: v.update(test_selection=["tests/test_fixture.py"]),
    ],
)
def test_installed_outcomes_reject_missing_drifted_filtered_or_promoted_evidence(
    observed_record, mutation
):
    changed = deepcopy(observed_record)
    mutation(changed)
    with pytest.raises(ValueError):
        driver.validate_outcomes(changed)


def test_launcher_preserves_failures_without_claiming_execution(tmp_path):
    out = tmp_path / "diagnostics"
    assert (
        driver.main(
            [
                "--wheel",
                str(tmp_path / "missing.whl"),
                "--out",
                str(out),
                "--profile",
                "python-linux-3.12",
            ]
        )
        == 1
    )
    assert json.loads((out / "launcher-failure.json").read_text())["status"] == "FAIL"
    assert not (out / "outcomes.json").exists()


def _process_running(pid):
    if os.name == "nt":
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        api.OpenProcess.restype = ctypes.c_void_p
        api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        api.WaitForSingleObject.restype = ctypes.c_uint32
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = api.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return api.WaitForSingleObject(handle, 0) == 258
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    status = Path(f"/proc/{pid}/stat")
    if sys.platform == "linux":
        # An orphan zombie has terminated and released its files; only its new
        # parent (normally init) can reap its remaining process-table entry.
        try:
            return status.read_text().split(") ", 1)[1].split()[0] != "Z"
        except FileNotFoundError:
            return False
    return True


def _wait_until(predicate, *, timeout, reason):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, reason
        time.sleep(0.02)


def test_timeout_terminates_child_and_grandchild_and_releases_loaded_extension(
    tmp_path, monkeypatch
):
    module = find_spec("coverage.tracer")
    assert module is not None and module.origin
    held_library = tmp_path / Path(module.origin).name
    shutil.copyfile(module.origin, held_library)
    program = tmp_path / "family.py"
    program.write_text(
        """
import ctypes, os, subprocess, sys, time
from pathlib import Path
root = Path(sys.argv[2])
mode = sys.argv[1]
(root / (mode + '.pid')).write_text(str(os.getpid()))
if mode != 'grandchild':
    subprocess.Popen([sys.executable, __file__, 'child' if mode == 'parent' else 'grandchild', str(root), sys.argv[3]])
else:
    library = ctypes.CDLL(sys.argv[3])
    locked_file = (root / 'held.txt').open('w')
    (root / 'heartbeat').write_text(str(time.monotonic_ns()))
    (root / 'ready').write_text('loaded')
while True:
    if mode == 'grandchild':
        (root / 'heartbeat').write_text(str(time.monotonic_ns()))
    time.sleep(0.05)
""",
        encoding="utf-8",
    )
    command = [sys.executable, str(program), "parent", str(tmp_path), str(held_library)]
    popen = driver.subprocess.Popen
    execution_elapsed = []

    def started_family(*args, **kwargs):
        process = popen(*args, **kwargs)
        if args[0] != command:
            return process
        original_wait = process.wait
        first_wait = True

        def wait(*, timeout):
            nonlocal first_wait
            if first_wait:
                first_wait = False
                # Subprocess coverage starts three instrumented interpreters.
                # Bound fixture setup independently, then exercise the unchanged
                # real three-second wait after all descendants hold resources.
                _wait_until(
                    lambda: (tmp_path / "ready").exists(),
                    timeout=30,
                    reason="process family did not finish bounded startup",
                )
                started = time.monotonic()
                try:
                    return original_wait(timeout=timeout)
                finally:
                    execution_elapsed.append(time.monotonic() - started)
            return original_wait(timeout=timeout)

        monkeypatch.setattr(process, "wait", wait)
        return process

    monkeypatch.setattr(driver.subprocess, "Popen", started_family)
    with pytest.raises(driver.ProcessTreeTimeout) as caught:
        driver.run_process_tree(command, cwd=tmp_path, env=os.environ.copy(), timeout=3)
    assert caught.value.cmd == command and caught.value.timeout == 3
    assert len(execution_elapsed) == 1 and execution_elapsed[0] >= 3
    assert caught.value.cleanup_errors == []
    assert (tmp_path / "ready").read_text() == "loaded"
    pids = [int(path.read_text()) for path in tmp_path.glob("*.pid")]
    assert len(pids) == 3
    # POSIX killpg delivers signals to descendants asynchronously; the direct
    # parent wait does not reap grandchildren. Keep resource-release assertions
    # strict while allowing bounded signal delivery and OS handle teardown.
    _wait_until(
        lambda: all(not _process_running(pid) for pid in pids),
        timeout=10,
        reason="process descendants remained alive after timeout cleanup",
    )
    heartbeat = (tmp_path / "heartbeat").read_text()
    time.sleep(0.15)
    assert (tmp_path / "heartbeat").read_text() == heartbeat
    # Windows denies unlink while the grandchild still maps this extension DLL.
    held_library.unlink()
    (tmp_path / "held.txt").unlink()


def test_process_tree_preserves_nonzero_exit_without_extending_deadline(tmp_path):
    assert (
        driver.run_process_tree(
            [sys.executable, "-c", "raise SystemExit(7)"],
            cwd=tmp_path,
            env=os.environ.copy(),
            timeout=3,
        )
        == 7
    )


def test_timeout_remains_primary_when_process_cleanup_reports_failure(tmp_path, monkeypatch):
    original = driver._stop_process_tree

    def cleanup(process, job):
        return original(process, job) + ["injected cleanup diagnostic"]

    monkeypatch.setattr(driver, "_stop_process_tree", cleanup)
    with pytest.raises(driver.ProcessTreeTimeout) as caught:
        driver.run_process_tree(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=tmp_path,
            env=os.environ.copy(),
            timeout=0.2,
        )
    assert caught.value.timeout == 0.2
    assert caught.value.cleanup_errors == ["injected cleanup diagnostic"]


def test_timeout_diagnostic_survives_temporary_cleanup_permission_error(tmp_path, monkeypatch):
    temporary = driver.tempfile.TemporaryDirectory(dir=tmp_path)
    cleanup = temporary.cleanup
    monkeypatch.setattr(driver.tempfile, "TemporaryDirectory", lambda **kwargs: temporary)

    def locked():
        raise PermissionError("fixture DLL is locked")

    monkeypatch.setattr(temporary, "cleanup", locked)

    def timed_out(source, wheel, out, profile, coverage_out):
        with driver.temporary_workspace(out):
            raise driver.ProcessTreeTimeout(["worker"], 900, [])

    monkeypatch.setattr(driver, "run_suite", timed_out)
    out = tmp_path / "diagnostics"
    try:
        assert (
            driver.main(
                [
                    "--wheel",
                    str(tmp_path / "unused.whl"),
                    "--out",
                    str(out),
                    "--profile",
                    "python-windows-3.12",
                ]
            )
            == 1
        )
        failure = json.loads((out / "launcher-failure.json").read_text())
        assert failure["type"] == "ProcessTreeTimeout" and failure["timeout_seconds"] == 900
        assert failure["command"] == ["worker"]
        assert failure["process_tree_cleanup"] == {"completed": True, "errors": []}
        assert "900" in failure["error"] and "locked" not in failure["error"]
        secondary = json.loads((out / "cleanup-failure.json").read_text())
        assert "locked" in secondary["cleanup_error"] and "900" in secondary["primary_error"]
        assert not (out / "outcomes.json").exists()
    finally:
        cleanup()
