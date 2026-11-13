"""Exercise evidence capture using real temporary Git repositories and pytest runs."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from proofmap.integrity import artifact_digest, load_json, write_json
from scripts.alpha_evidence import command, identity

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def source(tmp_path, monkeypatch):
    for name in (
        "ALPHA_PR_HEAD",
        "GITHUB_EVENT_PATH",
        "ALPHA_RUN_ID",
        "ALPHA_RUN_ATTEMPT",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALPHA_RUN_ID", "local-test")
    root = tmp_path / "source"
    root.mkdir()
    (root / ".gitignore").write_text(".work/\n__pycache__/\n.pytest_cache/\n")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "1.2.3"\n[tool.pytest.ini_options]\n'
    )
    (root / "acceptance").mkdir()
    write_json(root / "acceptance/paper_ci_alpha.json", {"requirements": []})
    (root / "tracked.txt").write_text("initial source")
    for argv in (
        ["init", "--quiet"],
        ["add", "."],
        [
            "-c",
            "user.name=Alpha Tests",
            "-c",
            "user.email=alpha@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
    ):
        subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True)
    return root


def manifest(source):
    return source / "acceptance/paper_ci_alpha.json"


def test_identity_binds_actual_dirty_untracked_deleted_and_manifest_bytes(source):
    original = identity(source, manifest(source))
    assert original["package_version"] == "1.2.3"
    assert original["run_id"] == "local-test"
    assert original["run_attempt"] == "1"
    assert original["pr_head"] is None
    assert original["manifest_sha256"] == artifact_digest(manifest(source).read_bytes())
    fingerprints = {original["source_fingerprint"]}
    (source / "tracked.txt").write_text("modified")
    fingerprints.add(identity(source, manifest(source))["source_fingerprint"])
    (source / "new.py").write_text("print('new implementation')")
    fingerprints.add(identity(source, manifest(source))["source_fingerprint"])
    (source / "tracked.txt").unlink()
    fingerprints.add(identity(source, manifest(source))["source_fingerprint"])
    assert len(fingerprints) == 4
    current = identity(source, manifest(source))
    assert current["tested_commit"] == original["tested_commit"]
    assert current["git_tree"] == original["git_tree"]
    (source / ".work").mkdir()
    (source / ".work/output.json").write_text("ignored output")
    assert identity(source, manifest(source)) == current
    manifest(source).write_bytes(manifest(source).read_bytes() + b"\n")
    assert identity(source, manifest(source))["manifest_sha256"] != current["manifest_sha256"]


def test_identity_separates_pr_head_checkout_and_run_attempt(source, monkeypatch, tmp_path):
    monkeypatch.delenv("ALPHA_RUN_ID")
    event = tmp_path / "event.json"
    write_json(event, {"pull_request": {"head": {"sha": "a" * 40}}})
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_RUN_ID", "456")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    observed = identity(source, manifest(source))
    assert observed["pr_head"] == "a" * 40
    assert observed["tested_commit"] != observed["pr_head"]
    assert observed["run_id"] == "456" and observed["run_attempt"] == "2"
    monkeypatch.setenv("ALPHA_PR_HEAD", "b" * 40)
    monkeypatch.setenv("ALPHA_RUN_ID", "local-session")
    monkeypatch.setenv("ALPHA_RUN_ATTEMPT", "3")
    changed = identity(source, manifest(source))
    assert changed["pr_head"] == "b" * 40
    assert changed["run_id"] == "local-session" and changed["run_attempt"] == "3"
    monkeypatch.setenv("ALPHA_PR_HEAD", "not-an-immutable-sha")
    with pytest.raises(ValueError, match="Git SHA"):
        identity(source, manifest(source))


@pytest.mark.parametrize("value", [None, "", "   "])
def test_identity_requires_explicit_local_run_id(source, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("ALPHA_RUN_ID")
    else:
        monkeypatch.setenv("ALPHA_RUN_ID", value)
    with pytest.raises(ValueError, match="Set ALPHA_RUN_ID"):
        identity(source, manifest(source))


def run_pytest(source, code, *extra):
    (source / "test_observed.py").write_text(code)
    output = source / ".work/evidence.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "scripts.alpha_evidence",
            "--alpha-evidence",
            str(output),
            "--alpha-job",
            "unit",
            "--alpha-profile",
            "offline",
            "-q",
            *extra,
        ],
        cwd=source,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert output.is_file(), result.stdout + result.stderr
    return result, load_json(output)


def test_pytest_records_pass_skip_xfail_and_xpass_without_promoting_them(source):
    result, report = run_pytest(
        source,
        """
import pytest
def test_pass(): pass
@pytest.mark.skip(reason='optional capability')
def test_skip(): pass
@pytest.mark.xfail(reason='known issue')
def test_xfail(): assert False
@pytest.mark.xfail(reason='unexpected pass')
def test_xpass(): pass
""",
    )
    assert result.returncode == 0
    assert report["status"] == "PASS"
    assert {test["nodeid"]: test["outcome"] for test in report["tests"]} == {
        "test_observed.py::test_pass": "passed",
        "test_observed.py::test_skip": "skipped",
        "test_observed.py::test_xfail": "xfailed",
        "test_observed.py::test_xpass": "xpassed",
    }


@pytest.mark.parametrize(
    "case", ["teardown", "strict_xpass", "maxfail", "collect_only", "empty", "collection_error"]
)
def test_pytest_failed_unexecuted_and_empty_cases_cannot_report_pass(source, case):
    programs = {
        "teardown": "import pytest\n@pytest.fixture\ndef broken():\n yield\n assert False\ndef test_pass(broken): pass\n",
        "strict_xpass": "import pytest\n@pytest.mark.xfail(strict=True)\ndef test_pass(): pass\n",
        "maxfail": "def test_first(): assert False\ndef test_second(): pass\n",
        "collect_only": "def test_pass(): pass\n",
        "empty": "# zero collected cases\n",
        "collection_error": "raise RuntimeError('broken collection')\n",
    }
    options = (
        ["--maxfail=1"]
        if case == "maxfail"
        else ["--collect-only"]
        if case == "collect_only"
        else []
    )
    result, report = run_pytest(source, programs[case], *options)
    assert report["status"] == "FAIL"
    if case == "maxfail":
        assert [test["outcome"] for test in report["tests"]] == ["failed", "error"]
    elif case == "strict_xpass":
        assert report["tests"][0]["outcome"] == "xpassed"
    elif case == "empty":
        assert report["tests"] == [] and result.returncode == 5
    else:
        assert report["tests"][0]["outcome"] == "error"


def test_pytest_mutation_fails_an_otherwise_successful_run(source):
    result, report = run_pytest(
        source,
        """
from pathlib import Path
def test_mutates_source():
    Path('tracked.txt').write_text('changed during execution')
""",
    )
    assert result.returncode == 1
    assert report["status"] == "FAIL" and report["exit_code"] == 1
    assert report["tests"][0]["outcome"] == "passed"
    assert (
        report["identity"]["source_fingerprint"]
        != identity(source, manifest(source))["source_fingerprint"]
    )
    diagnostic = load_json(source / ".work/evidence.json.identity.json")
    assert diagnostic["final_identity"] == identity(source, manifest(source))
    assert diagnostic["differing_identity_fields"] == ["source_fingerprint"]
    assert diagnostic["exit_code_before_identity_check"] == 0
    assert diagnostic["identity_error"] is None


@pytest.mark.parametrize("mutate", [False, True])
def test_installed_pytest_identity_uses_original_source_checkout(source, tmp_path, mutate):
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    program = (
        "from pathlib import Path\ndef test_changes_original():\n"
        + f"    Path({str(source / 'tracked.txt')!r}).write_text('changed')\n"
        if mutate
        else "def test_pass(): pass\n"
    )
    expected = identity(source, manifest(source))
    result, report = run_pytest(staged, program, "--alpha-source-root", str(source))
    assert report["identity"] == expected
    assert report["identity"]["package_version"] == "1.2.3"
    assert report["status"] == ("FAIL" if mutate else "PASS")
    assert result.returncode == (1 if mutate else 0)


def test_pytest_finalization_plugin_failure_cannot_report_pass(source):
    (source / "conftest.py").write_text("""
import pytest
@pytest.hookimpl(wrapper=True)
def pytest_sessionfinish(session, exitstatus):
    yield
    session.exitstatus = 1
""")
    result, report = run_pytest(source, "def test_pass(): pass\n")
    assert result.returncode == 1
    assert report["status"] == "FAIL" and report["exit_code"] == 1
    assert report["tests"][0]["outcome"] == "passed"


@pytest.mark.parametrize("case", ["pass", "nonzero", "missing", "stale", "mutation"])
def test_command_observes_exit_fresh_artifacts_and_source_identity(source, case):
    output = source / ".work/job/evidence.json"
    artifact = output.parent / "summary.json"
    output.parent.mkdir(parents=True)
    if case == "stale":
        write_json(artifact, {"old": True})
    program = (
        f'from pathlib import Path; Path({str(artifact)!r}).write_text(\'{{"status":"PASS"}}\')'
    )
    if case in {"missing", "stale"}:
        program = "pass"
    elif case == "nonzero":
        program += "; raise SystemExit(9)"
    elif case == "mutation":
        program += f"; Path({str(source / 'tracked.txt')!r}).write_text('changed')"
    code = command(
        source,
        manifest(source),
        output,
        "build",
        "wheel",
        [f"summary={artifact}"],
        [sys.executable, "-c", program],
    )
    report = load_json(output)
    assert report["status"] == ("PASS" if case == "pass" else "FAIL")
    assert code == (0 if case == "pass" else 9 if case == "nonzero" else 1)
    assert report["exit_code"] == code
    assert report["tests"] == [] and report["kind"] == "command"
    diagnostic = load_json(output.with_name(output.name + ".identity.json"))
    assert diagnostic["child_exit_code"] == (9 if case == "nonzero" else 0)
    assert diagnostic["identity_unchanged"] is (case != "mutation")
    assert diagnostic["artifacts_valid"] is (case not in {"missing", "stale"})
    assert diagnostic["final_identity"] == identity(source, manifest(source))
    # Original readiness discovery still sees only the actual evidence envelope.
    assert list(output.parent.glob("*evidence.json")) == [output]
    if case == "pass":
        assert report["artifacts"] == [
            {
                "name": "summary",
                "path": "summary.json",
                "sha256": artifact_digest(artifact.read_bytes()),
            }
        ]


def test_command_rejects_artifact_escape_and_duplicate_names(source, tmp_path):
    output = source / ".work/evidence.json"
    for artifacts in (
        [f"escape={tmp_path / 'outside.json'}"],
        [f"one={output.parent / 'a'}", f"one={output.parent / 'b'}"],
    ):
        with pytest.raises(ValueError):
            command(
                source,
                manifest(source),
                output,
                "job",
                "profile",
                artifacts,
                [sys.executable, "-c", "raise SystemExit('must not execute')"],
            )


def test_command_cli_runs_once_and_records_actual_output(source):
    output = source / ".work/evidence.json"
    artifact = output.parent / "result.txt"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.alpha_evidence",
            "command",
            "--root",
            str(source),
            "--job",
            "cli",
            "--profile",
            "offline",
            "--out",
            str(output),
            "--artifact",
            f"result={artifact}",
            "--",
            sys.executable,
            "-c",
            f"from pathlib import Path; p=Path({str(artifact)!r}); p.write_text(p.read_text()+'once' if p.exists() else 'once')",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert artifact.read_text() == "once"
    assert load_json(output)["status"] == "PASS"


def test_plugin_is_inert_without_capture_option(tmp_path):
    (tmp_path / "test_simple.py").write_text("def test_pass(): pass\n")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "scripts.alpha_evidence",
            "--rootdir",
            str(tmp_path),
            str(tmp_path / "test_simple.py"),
            "-q",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not list(tmp_path.glob("*.json"))


def test_command_startup_failure_cannot_report_pass(source):
    output = source / ".work/evidence.json"
    assert (
        command(
            source,
            manifest(source),
            output,
            "job",
            "profile",
            [],
            [str(source / "absent-executable")],
        )
        == 1
    )
    report = load_json(output)
    assert report["status"] == "FAIL" and report["exit_code"] == 1


@pytest.mark.parametrize(
    "error",
    [
        PermissionError("secret-private-path"),
        ValueError("secret-value"),
        subprocess.CalledProcessError(128, ["git", "secret-command"], stderr=b"secret-output"),
    ],
)
def test_command_retains_safe_final_identity_error_and_child_success(source, monkeypatch, error):
    from scripts import alpha_evidence

    actual_identity = alpha_evidence.identity
    calls = 0

    def final_error(root, path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error
        return actual_identity(root, path)

    monkeypatch.setattr(alpha_evidence, "identity", final_error)
    output = source / ".work/evidence.json"
    assert (
        command(
            source, manifest(source), output, "unit", "offline", [], [sys.executable, "-c", "pass"]
        )
        == 1
    )
    report = load_json(output)
    sidecar = output.with_name(output.name + ".identity.json")
    diagnostic = load_json(sidecar)
    assert calls == 2
    assert report["status"] == "FAIL" and report["exit_code"] == 1
    assert diagnostic["child_exit_code"] == 0
    assert diagnostic["identity_unchanged"] is False
    assert diagnostic["final_identity"] is None
    assert diagnostic["identity_error"] == {
        "type": type(error).__name__,
        "message": "Final source identity could not be read.",
    }
    assert "secret" not in sidecar.read_text()


def test_pytest_actual_final_git_read_error_is_retained_without_promoting_pass(source):
    result, report = run_pytest(
        source,
        "from pathlib import Path\ndef test_pass_then_git_unavailable():\n"
        "    Path('.git').rename('.git-unavailable')\n"
        "    Path('.git').write_text('invalid repository marker')\n",
    )
    diagnostic = load_json(source / ".work/evidence.json.identity.json")
    assert result.returncode == 1
    assert report["status"] == "FAIL" and report["tests"][0]["outcome"] == "passed"
    assert diagnostic["exit_code_before_identity_check"] == 0
    assert diagnostic["identity_unchanged"] is False
    assert diagnostic["identity_error"]["type"] == "CalledProcessError"


def test_command_diagnostic_write_failure_cannot_report_pass(source, capsys):
    output = source / ".work/evidence.json"
    blocked = output.with_name(output.name + ".identity.json")
    blocked.mkdir(parents=True)
    assert (
        command(
            source, manifest(source), output, "unit", "offline", [], [sys.executable, "-c", "pass"]
        )
        == 1
    )
    report = load_json(output)
    assert report["status"] == "FAIL" and report["exit_code"] == 1
    assert "diagnostic could not be retained" in capsys.readouterr().err


def test_pytest_diagnostic_write_failure_cannot_report_pass(source):
    (source / ".work/evidence.json.identity.json").mkdir(parents=True)
    result, report = run_pytest(source, "def test_pass(): pass\n")
    assert result.returncode == 1
    assert report["status"] == "FAIL" and report["tests"][0]["outcome"] == "passed"
    assert "diagnostic could not be retained" in result.stderr


def test_child_artifact_cannot_overwrite_final_identity_diagnostic(source):
    output = source / ".work/evidence.json"
    sidecar = output.with_name(output.name + ".identity.json")
    with pytest.raises(ValueError, match="identity diagnostic"):
        command(
            source,
            manifest(source),
            output,
            "unit",
            "offline",
            [f"forged={sidecar}"],
            [sys.executable, "-c", "raise SystemExit('must not execute')"],
        )


def test_original_windows_driver_keeps_unchanged_interface_fail_closed(source):
    from scripts.windows_pytest_partitions import _unchanged

    started = identity(source, manifest(source))
    assert _unchanged(source, manifest(source), started) is True
    (source / "tracked.txt").write_text("changed")
    assert _unchanged(source, manifest(source), started) is False
    (source / ".git").rename(source / ".git-unavailable")
    (source / ".git").write_text("invalid repository marker")
    assert _unchanged(source, manifest(source), started) is False
