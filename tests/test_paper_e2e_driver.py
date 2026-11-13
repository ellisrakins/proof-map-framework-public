"""Integration-driver provenance and diagnostic regressions; no simulated proof claims."""

import json
import subprocess

import pytest

from scripts import paper_e2e_isolated as driver


def test_independent_revision_fixture_is_source_derived_and_contains_checked_antecedent(tmp_path):
    from proofmap.formalize import formalize_document
    from proofmap.paper_sources import acquire, parse

    path = tmp_path / "branches.tex"
    path.write_text(driver.BRANCH_MANUSCRIPT, encoding="utf-8")
    manifest, artifacts = acquire(path)
    original = formalize_document(parse(manifest, artifacts))
    assert len(original) == 2 and all(row["status"] == "SUPPORTED" for row in original)
    assert all(row["exact_check"]["equal"] for row in original)
    path.write_text(
        driver.BRANCH_MANUSCRIPT.replace(r"\offset}{1}", r"\offset}{2}"), encoding="utf-8"
    )
    manifest, artifacts = acquire(path)
    revised = formalize_document(parse(manifest, artifacts))
    assert original[0]["obligation"] != revised[0]["obligation"]
    assert original[1]["obligation"]["statement"] == revised[1]["obligation"]["statement"]
    assert original[1]["candidate"] == revised[1]["candidate"]
    assert original[1]["obligation"]["target_node_id"] != revised[1]["obligation"]["target_node_id"]


def test_launcher_keeps_worker_failure_diagnostics(tmp_path, monkeypatch):
    child_failure = {"status": "FAIL", "error": "actual Lean failure", "type": "ValueError"}
    (tmp_path / "failure.json").write_text(json.dumps(child_failure), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "driver",
            "--wheel",
            str(tmp_path / "missing.whl"),
            "--profile",
            str(tmp_path / "profile.json"),
            "--out",
            str(tmp_path),
        ],
    )
    assert driver.main() == 1
    assert json.loads((tmp_path / "failure.json").read_text()) == child_failure
    assert json.loads((tmp_path / "launcher-failure.json").read_text())["type"] == "ValueError"


@pytest.mark.parametrize("mismatch", [None, "validator_sha", "manuscript_sha"])
def test_data_only_checks_both_immutable_revisions(tmp_path, monkeypatch, mismatch):
    submission = tmp_path / "submission"
    submission.mkdir()
    output = tmp_path / "data-only"
    validator_sha, manuscript_sha = "a" * 40, "b" * 40

    def run(command, **kwargs):
        assert command[command.index("--validator-sha") + 1] == validator_sha
        assert command[command.index("--manuscript-sha") + 1] == manuscript_sha
        assert "-I" in command
        assert kwargs["cwd"] == submission
        output.mkdir()
        summary = {
            "status": "PASS",
            "paper_count": 1,
            "validator_sha": validator_sha,
            "manuscript_sha": manuscript_sha,
        }
        if mismatch:
            summary[mismatch] = None
        (output / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(driver.subprocess, "run", run)
    if mismatch:
        with pytest.raises(ValueError, match="revision"):
            driver.data_only_check(
                tmp_path / "trusted.py", submission, output, validator_sha, manuscript_sha
            )
    else:
        assert (
            driver.data_only_check(
                tmp_path / "trusted.py", submission, output, validator_sha, manuscript_sha
            )["status"]
            == "PASS"
        )


@pytest.mark.parametrize("sha", ["a" * 40, "HEAD", "a" * 39, "A" * 40])
def test_validator_revision_resolves_and_validates_actual_git_commit(tmp_path, monkeypatch, sha):
    def run(command, **kwargs):
        assert command == ["git", "-C", str(tmp_path), "rev-parse", "HEAD^{commit}"]
        assert kwargs["check"] is True
        return subprocess.CompletedProcess(command, 0, sha + "\n", "")

    monkeypatch.setattr(driver.subprocess, "run", run)
    if sha == "a" * 40:
        assert driver.validator_revision(tmp_path) == sha
    else:
        with pytest.raises(ValueError, match="revision"):
            driver.validator_revision(tmp_path)
