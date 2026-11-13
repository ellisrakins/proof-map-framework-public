from pathlib import Path

from proofmap.cli import main


def test_existing_cli_workflows_keep_working(tmp_path: Path):
    examples = tmp_path / "examples"
    output = tmp_path / "reports"
    assert main(["examples", "--out", str(examples)]) == 0
    pm = str(examples / "minimal_conops.json")
    assert main(["analyze", pm]) == 0
    assert main(["surface", pm, "--out", str(output)]) == 0
    assert main(["report", pm, "--out", str(output)]) == 0
    assert main(["demo", "--out", str(tmp_path / "demo")]) == 0
    assert (
        main(
            [
                "hypothesis-search",
                pm,
                "examples/hypotheses/minimal_conops_hypotheses.json",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    catalog = "examples/theories/physics_theory_catalog.json"
    sources = "examples/sources/physics_theory_sources.json"
    for args in (
        ["theory-list", catalog],
        ["theory-list", catalog, "--json"],
        [
            "theory-validate",
            catalog,
            "--sources",
            sources,
            "--map",
            "examples/current_physics_backbone.json",
            "--report",
            str(output / "theories.md"),
        ],
        ["theory-scaffold", catalog, "loop_quantum_gravity", "--out", str(output / "lqg.json")],
        [
            "theory-slice",
            "examples/current_physics_backbone.json",
            "standard_model",
            "--out",
            str(output / "slice.json"),
        ],
    ):
        assert main(args) == 0
    assert main(["lean-check", str(tmp_path / "missing.lean")]) == 2


def test_validation_cli_reports_results(tmp_path: Path, monkeypatch):
    # These CLI branches test optional-tool reporting, not real kernel coverage.
    import proofmap.conops as conops
    import proofmap.current_validation as current

    monkeypatch.setattr(conops, "resolve_lean_executable", lambda _: None)
    monkeypatch.setattr(current, "resolve_lean_executable", lambda _: None)
    assert main(["validate-conops", "--out", str(tmp_path / "conops")]) == 0
    assert main(["validate-current-physics", "--out", str(tmp_path / "physics")]) == 0
