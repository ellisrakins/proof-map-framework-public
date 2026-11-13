"""Capture observed alpha execution; a report is evidence, never a manifest verdict.

Use ``pytest -p scripts.alpha_evidence --alpha-evidence .work/job/evidence.json
--alpha-job JOB --alpha-profile PROFILE`` or the ``command`` subcommand. Keep
outputs in ignored directories or outside the checkout. The source fingerprint
includes uncommitted and untracked nonignored files, including new test files.
Local capture and readiness checks require the same explicit ALPHA_RUN_ID; use
a fresh ID per qualification. GitHub runs use GITHUB_RUN_ID automatically.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

from proofmap.integrity import (
    artifact_digest,
    canonical_bytes,
    load_json,
    relative_path,
    rooted_path,
    write_json,
)


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def _git_root(path: Path) -> Path:
    return Path(os.fsdecode(_git(path, "rev-parse", "--show-toplevel")).strip()).resolve()


def _sha(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{40}", value):
        raise ValueError("Expected lowercase immutable Git SHA")
    return value


def _source_fingerprint(root: Path) -> str:
    names = set(
        _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0")
    )
    files: list[dict[str, Any]] = []
    for raw_name in sorted(names):
        if not raw_name:
            continue
        name = os.fsdecode(raw_name)
        path = root / name
        if path.is_symlink():
            files.append(
                {
                    "path": name,
                    "kind": "symlink",
                    "sha256": artifact_digest(os.fsencode(os.readlink(path))),
                }
            )
        elif not path.exists():
            files.append({"path": name, "kind": "missing"})
        elif path.is_file():
            files.append(
                {"path": name, "kind": "file", "sha256": artifact_digest(path.read_bytes())}
            )
        else:
            raise ValueError(f"Unsupported source entry (including submodule): {name}")
    return artifact_digest(canonical_bytes(files))


def _package_version(root: Path) -> str:
    # This deliberately accepts a literal static version only, including on Python
    # 3.10 (no tomllib). Dynamic versions cannot be silently inferred from an
    # installed package that may differ from this source checkout.
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    project = re.search(r"(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)", text)
    version = re.search(
        r"(?m)^version\s*=\s*([\"'][^\n]+?[\"'])\s*(?:#.*)?$", project[1] if project else ""
    )
    if not version:
        raise ValueError("Missing static project version in pyproject.toml")
    value = ast.literal_eval(version[1])
    if not isinstance(value, str) or not value:
        raise ValueError("Invalid static project version")
    return value


def identity(root: Path, manifest: Path) -> dict[str, Any]:
    """Bind observed execution to actual source bytes, Git identity, and run."""
    root = root.resolve(strict=True)
    run_id = os.environ.get("ALPHA_RUN_ID", os.environ.get("GITHUB_RUN_ID"))
    if not run_id or not run_id.strip():
        raise ValueError(
            "Set ALPHA_RUN_ID to a fresh local qualification ID (or use GITHUB_RUN_ID)"
        )
    pr_head = os.environ.get("ALPHA_PR_HEAD")
    if pr_head is None and os.environ.get("GITHUB_EVENT_PATH"):
        event = load_json(Path(os.environ["GITHUB_EVENT_PATH"]))
        if not isinstance(event, dict):
            raise ValueError("GitHub event must be an object")
        pull_request = event.get("pull_request")
        if pull_request is not None:
            if not isinstance(pull_request, dict) or not isinstance(pull_request.get("head"), dict):
                raise ValueError("Malformed pull request source identity")
            pr_head = pull_request["head"].get("sha")
            if not isinstance(pr_head, str):
                raise ValueError("Missing pull request head SHA")
    return {
        "tested_commit": _sha(_git(root, "rev-parse", "HEAD").decode("ascii").strip()),
        "git_tree": _sha(_git(root, "rev-parse", "HEAD^{tree}").decode("ascii").strip()),
        "source_fingerprint": _source_fingerprint(root),
        "pr_head": _sha(pr_head) if pr_head is not None else None,
        "run_id": run_id,
        "run_attempt": os.environ.get(
            "ALPHA_RUN_ATTEMPT", os.environ.get("GITHUB_RUN_ATTEMPT", "1")
        ),
        "package_version": _package_version(root),
        "manifest_sha256": artifact_digest(manifest.read_bytes()),
    }


def _final_identity_diagnostic(
    root: Path, manifest: Path, started: dict[str, Any]
) -> dict[str, Any]:
    """Retain the final check without exposing exception payloads or subprocess output."""
    try:
        final = identity(root, manifest)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # Exception messages can contain paths, command arguments, or child output.
        # A fixed message and bounded class name identify the failure safely.
        name = type(exc).__name__
        return {
            "identity_unchanged": False,
            "final_identity": None,
            "differing_identity_fields": [],
            "identity_error": {
                "type": name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", name) else "Error",
                "message": "Final source identity could not be read.",
            },
        }
    return {
        "identity_unchanged": final == started,
        "final_identity": final,
        "differing_identity_fields": sorted(
            key for key in set(started) | set(final) if started.get(key) != final.get(key)
        ),
        "identity_error": None,
    }


def _identity_diagnostic_path(output: Path) -> Path:
    # This does not end in "evidence.json", so readiness discovery cannot mistake
    # the diagnostic for an authority-bearing evidence envelope.
    return output.with_name(output.name + ".identity.json")


def _unchanged(root: Path, manifest: Path, started: dict[str, Any]) -> bool:
    """Preserve the final-check interface used by the original Windows driver."""
    return _final_identity_diagnostic(root, manifest, started)["identity_unchanged"] is True


def _write_identity_diagnostic(output: Path, diagnostic: dict[str, Any]) -> bool:
    try:
        write_json(
            _identity_diagnostic_path(output),
            {"schema_version": "1.0", "kind": "capture-identity-diagnostic", **diagnostic},
        )
    except (OSError, ValueError):
        print("Alpha final identity diagnostic could not be retained.", file=sys.stderr)
        return False
    return True


def _envelope(
    started: dict[str, Any],
    job: str,
    profile: str,
    kind: str,
    exit_code: int,
    passed: bool,
    tests: list[dict[str, str]],
    artifacts: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "identity": started,
        "job": job,
        "profile": profile,
        "kind": kind,
        "status": "PASS" if passed else "FAIL",
        "exit_code": exit_code,
        "tests": tests,
        "artifacts": artifacts,
    }


# Import pytest only when pytest invokes these hooks. Command capture also runs
# in installed-wheel environments without optional test dependencies.
def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("alpha evidence")
    group.addoption("--alpha-evidence", help="Write an observed alpha evidence JSON envelope")
    group.addoption("--alpha-job", help="CI job producing this evidence")
    group.addoption("--alpha-profile", help="Execution profile (not inferred from test names)")
    group.addoption("--alpha-manifest", default="acceptance/paper_ci_alpha.json")
    group.addoption(
        "--alpha-source-root",
        help="Trusted original checkout for installed-wheel tests; the installed driver validates staged inputs separately",
    )


def pytest_configure(config: Any) -> None:
    output = config.getoption("alpha_evidence")
    if not output:
        return
    import pytest

    job, profile = config.getoption("alpha_job"), config.getoption("alpha_profile")
    if not job or not profile:
        raise pytest.UsageError("--alpha-evidence requires --alpha-job and --alpha-profile")
    source = config.getoption("alpha_source_root")
    root = _git_root(Path(source) if source else Path(config.rootpath))
    manifest = root / config.getoption("alpha_manifest")
    # Outermost wrapper observes finalization failures from plugins such as
    # pytest-cov. Decorate here to keep command capture independent of pytest.
    pytest.hookimpl(wrapper=True, tryfirst=True)(_PytestEvidence.pytest_sessionfinish)
    config.pluginmanager.register(_PytestEvidence(root, manifest, Path(output), job, profile))


class _PytestEvidence:
    def __init__(self, root: Path, manifest: Path, output: Path, job: str, profile: str) -> None:
        self.root, self.manifest, self.output = root, manifest, output
        self.job, self.profile = job, profile
        self.started: dict[str, Any] = {}
        self.nodeids: list[str] = []
        self.outcomes: dict[str, str] = {}
        self.duplicate_ids = False

    def pytest_sessionstart(self, session: Any) -> None:
        self.started = identity(self.root, self.manifest)

    def pytest_collection_finish(self, session: Any) -> None:
        self.nodeids = [item.nodeid for item in session.items]
        self.duplicate_ids = len(self.nodeids) != len(set(self.nodeids))

    def pytest_collectreport(self, report: Any) -> None:
        if report.failed:
            self.outcomes[report.nodeid] = "error"

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.failed and report.when != "call":
            outcome = "error"
        elif getattr(report, "wasxfail", None) is not None:
            outcome = "xfailed" if report.skipped else "xpassed"
        elif report.failed and "[XPASS(strict)]" in report.longreprtext:
            outcome = "xpassed"
        elif report.failed:
            outcome = "failed"
        elif report.skipped:
            outcome = "skipped"
        elif report.when == "call" and report.passed:
            outcome = "passed"
        else:
            return
        # Teardown/setup errors override a successful call, never the reverse.
        severity = {"passed": 0, "skipped": 1, "xfailed": 2, "xpassed": 3, "failed": 4, "error": 5}
        previous = self.outcomes.get(report.nodeid, "passed")
        if severity[outcome] >= severity[previous]:
            self.outcomes[report.nodeid] = outcome

    def pytest_sessionfinish(self, session: Any, exitstatus: int) -> Generator[None, None, None]:
        yield
        diagnostic = _final_identity_diagnostic(self.root, self.manifest, self.started)
        diagnostic.update(
            {
                "capture_kind": "pytest",
                "exit_code_before_identity_check": int(session.exitstatus),
                "duplicate_collected_ids": self.duplicate_ids,
            }
        )
        retained = _write_identity_diagnostic(self.output, diagnostic)
        unchanged = diagnostic["identity_unchanged"] is True
        if not unchanged or not retained or self.duplicate_ids:
            session.exitstatus = 1
        code = int(session.exitstatus)
        # Interrupted/maxfail/collect-only cases retain every collected node,
        # with unexecuted nodes marked error rather than silently disappearing.
        nodeids = sorted(set(self.nodeids) | set(self.outcomes))
        tests = [
            {"nodeid": nodeid, "outcome": self.outcomes.get(nodeid, "error")} for nodeid in nodeids
        ]
        passed = code == 0 and bool(self.nodeids) and unchanged and not self.duplicate_ids
        if any(test["outcome"] in {"failed", "error"} for test in tests):
            passed = False
        write_json(
            self.output,
            _envelope(self.started, self.job, self.profile, "pytest", code, passed, tests, []),
        )


def _artifact_path(output: Path, raw: str) -> tuple[str, Path]:
    path = Path(raw).absolute()
    parent = output.absolute().parent
    try:
        name = relative_path(path.relative_to(parent).as_posix())
    except ValueError as exc:
        raise ValueError("Artifact must be below the evidence envelope directory") from exc
    safe = rooted_path(parent, name)
    if safe == output.resolve():
        raise ValueError("Evidence envelope cannot be its own artifact")
    if safe == _identity_diagnostic_path(output).resolve():
        raise ValueError("Final identity diagnostic cannot be a child artifact")
    return name, safe


def _artifact_snapshot(path: Path) -> tuple[int, int, int, str] | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("Artifact is not a regular file")
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino, artifact_digest(path.read_bytes())


def command(
    root: Path,
    manifest: Path,
    output: Path,
    job: str,
    profile: str,
    artifacts: list[str],
    argv: list[str],
) -> int:
    """Run a command once and bind its exit/output bytes to this source identity."""
    if not argv or not job or not profile:
        raise ValueError("Command, job, and profile are required")
    output.parent.mkdir(parents=True, exist_ok=True)
    expected: dict[str, tuple[str, Path, tuple[int, int, int, str] | None]] = {}
    for spec in artifacts:
        name, separator, raw = spec.partition("=")
        if not separator or not name or name in expected:
            raise ValueError("Artifact must have a unique NAME=PATH")
        relative, path = _artifact_path(output, raw)
        expected[name] = (relative, path, _artifact_snapshot(path))
    started = identity(root, manifest)
    try:
        code = subprocess.run(argv, check=False).returncode
    except OSError as exc:
        print(f"Alpha command could not start: {exc}", file=sys.stderr)
        code = 1
    captured: list[dict[str, str]] = []
    valid = True
    for name, (relative, path, before) in expected.items():
        try:
            # Recheck links after execution, since the child may replace paths.
            _, safe = _artifact_path(output, str(path))
            after = _artifact_snapshot(safe)
            if after is None or after == before:
                raise ValueError(f"Missing or unchanged preexisting artifact: {name}")
            captured.append({"name": name, "path": relative, "sha256": after[3]})
        except (OSError, ValueError) as exc:
            print(f"Alpha artifact rejected: {exc}", file=sys.stderr)
            valid = False
    diagnostic = _final_identity_diagnostic(root, manifest, started)
    diagnostic.update(
        {"capture_kind": "command", "child_exit_code": code, "artifacts_valid": valid}
    )
    retained = _write_identity_diagnostic(output, diagnostic)
    passed = code == 0 and valid and diagnostic["identity_unchanged"] is True and retained
    if not passed and code == 0:
        code = 1
    write_json(output, _envelope(started, job, profile, "command", code, passed, [], captured))
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True).add_parser("command")
    sub.add_argument("--root", type=Path, default=Path.cwd())
    sub.add_argument("--manifest", type=Path, default=Path("acceptance/paper_ci_alpha.json"))
    sub.add_argument("--job", required=True)
    sub.add_argument("--profile", required=True)
    sub.add_argument("--out", type=Path, required=True)
    sub.add_argument("--artifact", action="append", default=[])
    sub.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    args.argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    root = _git_root(args.root)
    return command(
        root, root / args.manifest, args.out, args.job, args.profile, args.artifact, args.argv
    )


if __name__ == "__main__":
    raise SystemExit(main())
