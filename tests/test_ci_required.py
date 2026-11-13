import re
import runpy
from pathlib import Path

import pytest

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "ci_required.py"))
REQUIRED = MODULE["REQUIRED"]
accepted = MODULE["accepted"]


def workflow_job(name):
    text = Path(".github/workflows/ci.yml").read_text()
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [\w-]+:|\Z)", text, re.M | re.S)
    assert match is not None, f"Missing workflow job: {name}"
    return match[1]


def test_complete_success():
    assert accepted({name: {"result": "success"} for name in REQUIRED})


@pytest.mark.parametrize("state", ["failure", "cancelled", "skipped", "neutral", "", None])
def test_non_success_always_fails(state):
    results = {name: {"result": "success"} for name in REQUIRED}
    results[REQUIRED[0]]["result"] = state
    assert not accepted(results)


def test_missing_and_unexpected_fails():
    results = {name: {"result": "success"} for name in REQUIRED}
    results.pop(REQUIRED[0])
    assert not accepted(results)
    results["attacker-job"] = {"result": "success"}
    assert not accepted(results)


def test_workflow_has_same_fixed_required_set():
    text = Path(".github/workflows/ci.yml").read_text()
    assert "if: always()" in text
    assert "needs: [" + ", ".join(REQUIRED) + "]" in text
    assert "set(results) == set(required)" in text


def test_isolated_paper_integration_is_mandatory_and_never_skippable():
    assert "paper-e2e-isolated" in REQUIRED
    text = Path(".github/workflows/ci.yml").read_text()
    job = workflow_job("paper-e2e-isolated")
    assert "continue-on-error" not in job
    assert "paper_e2e_isolated.py" in text
    assert "provision_lean_profile.py" in text
    results = {name: {"result": "success"} for name in REQUIRED}
    for state in ("skipped", "failure", "cancelled"):
        results["paper-e2e-isolated"]["result"] = state
        assert not accepted(results)


@pytest.mark.parametrize("state", ["failure", "cancelled", "skipped", "neutral", "", None])
def test_alpha_readiness_cannot_be_skipped_or_fail(state):
    assert "alpha-readiness" in REQUIRED
    results = {name: {"result": "success"} for name in REQUIRED}
    results["alpha-readiness"]["result"] = state
    assert not accepted(results)
    results.pop("alpha-readiness")
    assert not accepted(results)


def test_alpha_readiness_consumes_existing_jobs_without_a_dependency_cycle():
    readiness = workflow_job("alpha-readiness")
    assert "if: always()" in readiness
    assert "continue-on-error" not in readiness
    assert "--check-only" not in readiness
    assert "python -m pytest" not in readiness
    required_producers = {
        "quality",
        "python-tests",
        "schema-migration",
        "semantic-properties",
        "verification-real",
        "sandbox-security",
        "paper-ci-fixtures",
        "paper-e2e-isolated",
        "browser-security",
        "package-build",
        "dependency-audit",
        "workflow-security",
        "windows-regression",
    }
    needs = re.search(r"needs: \[([^]]+)\]", readiness)
    assert needs is not None
    assert set(needs[1].split(", ")) == required_producers
    assert "pattern: alpha-evidence-*" in readiness
    assert "merge-multiple: true" in readiness
    assert "path: .work/alpha" in readiness
    assert "--evidence-dir .work/alpha" in readiness
    assert "--out .work/alpha-acceptance.json" in readiness
    assert "--summary .work/alpha-acceptance.md" in readiness
    assert "include-hidden-files: true" in readiness
    assert "if-no-files-found: error" in readiness


@pytest.mark.parametrize(
    ("job", "profile"),
    [
        ("schema-migration", "linux-unit"),
        ("semantic-properties", "linux-unit"),
        ("sandbox-security", "linux-sandbox"),
        ("paper-ci-fixtures", "linux-unit"),
        ("browser-security", "chromium"),
        ("workflow-security", "linux-unit"),
    ],
)
def test_existing_pytest_jobs_collect_and_preserve_alpha_evidence(job, profile):
    text = workflow_job(job)
    assert text.count("python -m pytest") == 1
    assert "-p scripts.alpha_evidence" in text
    assert f"--alpha-evidence .work/alpha/{job}/evidence.json" in text
    assert f"--alpha-job {job} --alpha-profile {profile}" in text
    assert f"name: alpha-evidence-{job}" in text
    assert "path: .work/alpha" in text
    assert "if: always()" in text
    assert "if-no-files-found: error" in text
    assert "include-hidden-files: true" in text


def test_real_execution_reports_keep_distinct_profiles_and_artifact_bindings():
    isolated = workflow_job("paper-e2e-isolated")
    assert "--profile linux-isolated" in isolated
    assert (
        "--artifact isolated-paper-outcomes="
        ".work/alpha/paper-e2e-isolated/diagnostics/outcomes.json" in isolated
    )
    assert isolated.count("python scripts/paper_e2e_isolated.py") == 1
    host = workflow_job("verification-real")
    assert "--profile host-lean" in host
    assert host.count("python scripts/verify_real.py") == 1
    package = workflow_job("package-build")
    assert "--profile installed-wheel" in package
    assert "--artifact wheel=.work/alpha/package-build/package.whl" in package
    assert "--audit-wheel .work/alpha/package-build/package.whl" in package
    assert package.count("python scripts/wheel_smoke.py") == 1


def test_matrix_evidence_retains_coverage_and_separate_platform_identities():
    text = workflow_job("python-tests")
    assert text.count("python -m pytest") == 1
    assert "--cov-branch --cov-fail-under=85 --cov-report=json:.work/coverage.json" in text
    assert "python scripts/check_critical_coverage.py .work/coverage.json" in text
    assert "profile_os: linux" in text
    assert text.count("profile_os: windows") == 5
    assert "--alpha-profile python-${{ matrix.profile_os }}-${{ matrix.python }}" in text
    assert "--alpha-job python-tests " in text
    assert "name: alpha-evidence-python-${{ matrix.profile_os }}-${{ matrix.python }}" in text
    assert "path: .work/alpha" in text
    assert "tests/test_alpha_acceptance.py tests/test_alpha_evidence.py" in workflow_job(
        "workflow-security"
    )
    assert "tests/test_alpha_isolated_artifact.py" in workflow_job("workflow-security")


@pytest.mark.parametrize("state", ["failure", "cancelled", "skipped", "neutral", "", None])
def test_windows_partition_aggregation_is_mandatory(state):
    assert "windows-regression" in REQUIRED
    results = {name: {"result": "success"} for name in REQUIRED}
    results["windows-regression"]["result"] = state
    assert not accepted(results)
    results.pop("windows-regression")
    assert not accepted(results)


def test_windows_partitions_preserve_full_profile_and_bounded_aggregation():
    matrix = workflow_job("python-tests")
    for index in range(4):
        assert f"partition: {index}" in matrix
    assert "timeout-minutes: 20" in matrix
    assert "windows_pytest_partitions.py run --index ${{ matrix.partition }}" in matrix
    assert "name: windows-pytest-partition-${{ matrix.partition }}" in matrix
    assert "if-no-files-found: error" in matrix
    aggregate = workflow_job("windows-regression")
    assert "if: always()" in aggregate and "needs: [python-tests]" in aggregate
    assert "runs-on: windows-latest" in aggregate
    assert "python-version: '3.12'" in aggregate
    assert "timeout-minutes: 20" in aggregate
    assert "continue-on-error" not in aggregate
    assert "pattern: windows-pytest-partition-*" in aggregate
    assert "--job windows-regression --profile partitioned-regression" in aggregate
    assert "--artifact partitioned-regression-outcomes=" in aggregate
    assert "windows_pytest_partitions.py aggregate --parts .work/windows-parts" in aggregate
    assert "name: alpha-evidence-windows-regression" in aggregate
    assert "tests/test_windows_pytest_partitions.py" in workflow_job("workflow-security")
    assert "-e '.[test,trust]' coverage" in workflow_job("alpha-readiness")


def test_generated_reports_do_not_change_source_fingerprint():
    matrix = workflow_job("python-tests")
    assert "--cov-report=json:.work/coverage.json" in matrix
    assert "path: .work/coverage.json" in matrix
    assert "--cov-report=json:coverage.json" not in matrix
    audit = workflow_job("dependency-audit")
    assert "--output .work/alpha/dependency-audit/audit.json" in audit
    assert "--output dependency-audit.json" not in audit
    assert "'.[test,trust]'" in workflow_job("alpha-readiness")


def test_workflow_preserves_source_bytes_before_checkout():
    text = Path(".github/workflows/ci.yml").read_text()
    workflow_settings = text.split("\njobs:", 1)[0]
    assert "GIT_CONFIG_COUNT: '1'" in workflow_settings
    assert "GIT_CONFIG_KEY_0: core.autocrlf" in workflow_settings
    assert "GIT_CONFIG_VALUE_0: 'false'" in workflow_settings
    assert "git config --global" not in text


@pytest.mark.parametrize("job", ["quality", "dependency-audit"])
def test_quality_and_dependency_audit_preserve_execution_evidence(job):
    text = workflow_job(job)
    assert f"--job {job} --profile {job}" in text
    assert f"--out .work/alpha/{job}/evidence.json" in text
    assert f"name: alpha-evidence-{job}" in text
    assert "if: always()" in text
    assert "include-hidden-files: true" in text
    assert "if-no-files-found: error" in text


def test_workflow_cost_and_dispatch_authority():
    text = Path(".github/workflows/ci.yml").read_text()
    assert "branches: [main]" in text
    assert "on: [push, pull_request" not in text
    paper = Path(".github/workflows/paper-ci.yml").read_text()
    assert "github.ref == 'refs/heads/main'" in paper
    assert "git -C validator rev-parse HEAD" in paper
    assert "git -C manuscript rev-parse HEAD" in paper
    assert "python -I validator/scripts/paper_ci_corpus.py" in paper


def test_dispatch_validator_allowlist_is_enforced_before_checkout():
    paper = Path(".github/workflows/paper-ci.yml").read_text()
    guard = paper.index("- name: Enforce approved dispatch validator")
    assert guard < paper.index("- uses: actions/checkout")
    guard_text = paper[guard : paper.index("- uses: actions/checkout")]
    assert "if: github.event_name == 'workflow_dispatch'" in guard_text
    assert "VALIDATOR_REF: ${{ inputs.validator-ref }}" in guard_text
    allowed = re.search(r"options: \['([a-f0-9]{40})'\]", paper)
    assert allowed is not None
    assert f'test "$VALIDATOR_REF" = "{allowed[1]}"' in guard_text
    assert 'test "$VALIDATOR_REF" != "' + "0" * 40 + '"' in guard_text


def test_integrated_driver_fails_with_diagnostics_when_wheel_missing(tmp_path, monkeypatch):
    module = runpy.run_path("scripts/paper_e2e_isolated.py")
    monkeypatch.setattr(
        "sys.argv",
        [
            "paper_e2e_isolated.py",
            "--wheel",
            str(tmp_path / "missing.whl"),
            "--profile",
            str(tmp_path / "profile.json"),
            "--out",
            str(tmp_path),
        ],
    )
    assert module["main"]() == 1
    from proofmap.integrity import load_json

    assert load_json(tmp_path / "launcher-failure.json")["status"] == "FAIL"


@pytest.mark.parametrize("case", ["complete", "missing", "below"])
def test_critical_coverage_fails_closed(tmp_path, monkeypatch, case):
    from proofmap.integrity import write_json

    names = {"integrity", "kernel", "trust", "runner", "replay"}
    payload = {
        "files": {f"proofmap/{name}.py": {"summary": {"percent_covered": 90}} for name in names}
    }
    if case == "missing":
        payload["files"].pop("proofmap/trust.py")
    if case == "below":
        payload["files"]["proofmap/kernel.py"]["summary"]["percent_covered"] = 89.99
    path = tmp_path / "coverage.json"
    write_json(path, payload)
    monkeypatch.setattr("sys.argv", ["check_critical_coverage.py", str(path)])
    if case == "complete":
        runpy.run_path("scripts/check_critical_coverage.py")
    else:
        with pytest.raises(SystemExit, match="1"):
            runpy.run_path("scripts/check_critical_coverage.py")
