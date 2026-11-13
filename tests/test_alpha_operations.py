"""Public operational boundaries; dispatch doubles never establish Lean evidence."""

import csv
import runpy
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from proofmap.cli import build_parser, main
from proofmap.examples import build_minimal_conops_map
from proofmap.integrity import artifact_digest, load_json, markdown_text
from proofmap.lean_check import LeanCheckResult
from proofmap.lean_export import render_lean_skeleton
from proofmap.model import Node, ProofMap
from proofmap.paper_reports import physical_location
from proofmap.report import render_markdown_report, write_boundary_csv

POLICY = runpy.run_path("scripts/workflow_security.py")["validate_workflow"]


@pytest.mark.parametrize("explicit", [True, False])
def test_legacy_host_mode_is_explicit_and_compatible(tmp_path, monkeypatch, capsys, explicit):
    source = tmp_path / "local.lean"
    source.write_text("theorem x : True := by trivial")
    monkeypatch.setattr("proofmap.cli.resolve_lean_executable", lambda _: "dispatch-double")
    monkeypatch.setattr(
        "proofmap.cli.check_lean_files",
        lambda *a, **k: [LeanCheckResult(source, [], 0, "", "")],
    )
    args = ["lean-check", str(source)]
    if explicit:
        args += ["--execution-mode", "trusted-host"]
    assert main(args) == 0
    assert "trusted-host" in capsys.readouterr().err
    assert "execution_mode" not in vars(
        build_parser().parse_args(["paper", "ci", str(source), "--out", str(tmp_path / "out")])
    )


@pytest.mark.parametrize(("result", "expected"), [(1, 1), (-1, 3), (None, 3), ("oserror", 3)])
def test_host_verifier_failure_exits_are_not_acceptance(tmp_path, monkeypatch, result, expected):
    source = tmp_path / "local.lean"
    source.write_text("example : False := by contradiction")
    monkeypatch.setattr(
        "proofmap.cli.resolve_lean_executable", lambda _: None if result is None else "double"
    )

    def check(*args, **kwargs):
        if result == "oserror":
            raise FileNotFoundError("compiler removed")
        return [LeanCheckResult(source, [], result, "", "synthetic failure")]

    monkeypatch.setattr("proofmap.cli.check_lean_files", check)
    assert main(["lean-check", str(source)]) == expected


@pytest.mark.parametrize("timeout", ["nan", "inf", "-1", "0"])
def test_invalid_host_timeout_is_input_error_without_execution(tmp_path, monkeypatch, timeout):
    def unexpected(*args, **kwargs):
        raise AssertionError("invalid timeout reached execution")

    monkeypatch.setattr("proofmap.cli.check_lean_files", unexpected)
    assert main(["lean-check", "unused.lean", "--timeout", timeout]) == 2


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("VERIFIED", 0),
        ("COMPILER_REJECTED", 1),
        ("POLICY_REJECTED", 1),
        ("TIMEOUT", 3),
        ("VERIFIER_ERROR", 3),
        ("VERIFIER_UNAVAILABLE", 3),
    ],
)
def test_attempt_exit_conventions_with_dispatch_double(tmp_path, monkeypatch, outcome, expected):
    from proofmap.attempts import AttemptOutcome

    # Only CLI exit dispatch is simulated here, not signing or actual execution.
    receipt = SimpleNamespace(
        to_json=lambda p: Path(p).write_text("dispatch double, not evidence"),
        attempt=SimpleNamespace(id="dispatch-double"),
        target_node_id="target",
        verified=outcome == "VERIFIED",
        verification=SimpleNamespace(
            outcome=AttemptOutcome(outcome), axioms=[], policy_issues=[], stdout="", stderr=""
        ),
    )
    monkeypatch.setattr("proofmap.cli.check_proof_attempt", lambda *a, **k: receipt)
    assert (
        main(
            [
                "attempt-check",
                "examples/attempts/nat_reflexivity_map.json",
                "examples/attempts/nat_reflexivity_obligation.json",
                "examples/attempts/nat_reflexivity_candidate.lean",
                "--producer",
                "dispatch-test",
                "--execution-mode",
                "trusted-host",
                "--out",
                str(tmp_path / "receipt.json"),
            ]
        )
        == expected
    )


def test_public_cli_invalid_records_exit_cleanly(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"title":"x","title":"duplicate"}')
    assert main(["analyze", str(bad)]) == 2
    assert "DUPLICATE_KEY" in capsys.readouterr().err
    assert main(["lean-check", str(tmp_path / "missing.lean")]) == 2


def test_safe_exports_preserve_mathematical_source(tmp_path):
    payload = "<script>x</script>[click](javascript:alert(1))|` #\nnew"
    pm = ProofMap(title=payload, description=payload)
    pm.add_node(
        Node(
            id=payload,
            label=payload,
            kind="GAP",
            status="GAP",
            layer="BOUNDARY",
            domain=payload,
            statement=payload,
            notes=payload,
            source_ids=[payload],
        )
    )
    before = deepcopy(pm.to_dict())
    rendered = render_markdown_report(pm)
    assert payload not in rendered and "<script>" not in rendered
    assert "[click](javascript:" not in rendered and markdown_text(payload) in rendered
    assert pm.to_dict() == before
    pm.nodes[payload].label = '=HYPERLINK("https://example.invalid")'
    path = tmp_path / "boundary.csv"
    write_boundary_csv(pm, path)
    row = next(csv.DictReader(path.open(encoding="utf-8", newline="")))
    assert row["label"].startswith("'=HYPERLINK")
    assert pm.nodes[payload].label.startswith("=HYPERLINK")


def test_lean_scaffold_and_sarif_url_boundaries():
    pm = build_minimal_conops_map()
    pm.title = "-/\n#eval dangerous\n/-"
    rendered = render_lean_skeleton(pm)
    assert "Generated scaffold for: - /" in rendered
    assert "proof-engineering sketch" in rendered
    with pytest.raises(ValueError, match="namespace"):
        render_lean_skeleton(pm, namespace="Good\n#eval dangerous")
    raw = "αβ".encode()
    name = "dir/a #?[x].tex"
    location = physical_location(
        {
            "format": "tex",
            "artifact": name,
            "artifact_sha256": artifact_digest(raw),
            "start": 0,
            "end": len(raw),
        },
        {name: raw},
    )
    assert unquote(location["artifactLocation"]["uri"]) == name
    assert "#" not in location["artifactLocation"]["uri"]
    assert location["region"]["endColumn"] == 3
    with pytest.raises(ValueError, match="UNSAFE_PATH"):
        physical_location({"format": "tex", "artifact": "javascript:alert(1)"}, {})


def test_all_workflows_obey_bounded_read_only_policy():
    for path in Path(".github/workflows").glob("*.yml"):
        assert POLICY(path.read_text(), path.name) == [], path.name


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        ("contents: read", "contents: write", "READ_ONLY_DEFAULT"),
        ("persist-credentials: false", "persist-credentials: true", "PERSISTED_CREDENTIALS"),
        ("timeout-minutes: 20", "timeout-minutes: 0", "UNBOUNDED_JOB:quality"),
        ("retention-days: 7", "retention-days: 90", "UNBOUNDED_ARTIFACT"),
        ("-c constraints-ci.txt", "--upgrade", "UNCONSTRAINED_PYTHON_ACQUISITION"),
        (
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
            "actions/checkout@main",
            "UNPINNED_ACTION",
        ),
    ],
)
def test_workflow_policy_rejects_individual_unsafe_step(old, new, code):
    text = Path(".github/workflows/ci.yml").read_text()
    assert old in text
    assert code in POLICY(text.replace(old, new, 1), "ci.yml")


def test_manuscript_workflow_rejects_submission_as_validator():
    text = Path(".github/workflows/paper-ci.yml").read_text()
    assert POLICY(text, "paper-ci.yml") == []
    assert "UNTRUSTED_VALIDATOR_REVISION" in POLICY(
        text.replace("github.event.pull_request.base.sha", "github.event.pull_request.head.sha"),
        "paper-ci.yml",
    )
    assert "SUBMISSION_IMPORT_PATH" in POLICY(text.replace("python -I", "python"), "paper-ci.yml")


def test_optional_hosted_features_cannot_become_required():
    text = Path(".github/workflows/codeql.yml").read_text()
    assert POLICY(text, "codeql.yml") == []
    assert "ENTITLEMENT_NOT_GATED" in POLICY(
        text.replace("vars.PROOFMAP_CODEQL_ENABLED == 'true'", "true"), "codeql.yml"
    )
    assert "OPTIONAL_NOT_MANUAL" in POLICY(
        text.replace("workflow_dispatch", "pull_request"), "codeql.yml"
    )
    assert "MANDATORY_HOSTED_ENTITLEMENT" in POLICY(text, "ci.yml")


@pytest.mark.parametrize(
    "command",
    [
        "python -m twine upload dist/*",
        "gh release create v1",
        "git push --tags",
        "gh api -X PUT repos/owner/repo/branches/main/protection",
    ],
)
def test_release_rejects_publication_and_server_mutation(command):
    text = Path(".github/workflows/release.yml").read_text()
    assert POLICY(text, "release.yml") == []
    assert "PUBLICATION_OR_SERVER_MUTATION" in POLICY(
        text + "      - run: " + command + "\n", "release.yml"
    )


def test_dependency_updates_and_release_remain_reviewable():
    updates = Path(".github/dependabot.yml").read_text()
    assert "package-ecosystem: pip" in updates and "package-ecosystem: github-actions" in updates
    assert "interval: weekly" in updates and "open-pull-requests-limit:" in updates
    assert "auto-merge" not in updates
    assert "ci-required" in Path("docs/BRANCH_PROTECTION.md").read_text()


def test_paper_exports_work_offline_without_host_fallback_or_entitlement(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline paper path attempted host Lean or network access")

    monkeypatch.setattr("proofmap.cli.resolve_lean_executable", forbidden)
    monkeypatch.setattr("proofmap.cli.check_proof_attempt", forbidden)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", forbidden)
    monkeypatch.delenv("PROOFMAP_CODEQL_ENABLED", raising=False)
    source = tmp_path / "paper.tex"
    raw = r"\begin{theorem}For every $x\in\mathbb{Z}$,\[x=x.\]\end{theorem}"
    source.write_text(raw)
    output = tmp_path / "out"
    assert (
        main(
            [
                "paper",
                "ci",
                str(source),
                "--require-formal",
                "--out",
                str(output),
                "--store",
                str(tmp_path / "store"),
            ]
        )
        == 3
    )
    assert source.read_text() == raw
    assert load_json(output / "execution_events.json") == []
    assert load_json(output / "results.sarif")["version"] == "2.1.0"
    for name in ("report.md", "report.html", "report.json", "results.sarif"):
        assert (output / name).stat().st_size > 0
