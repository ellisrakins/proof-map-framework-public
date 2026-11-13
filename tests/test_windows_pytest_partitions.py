"""Partition evidence contracts; synthetic coverage is never qualification evidence."""

from copy import deepcopy

import pytest
from coverage import CoverageData
from test_alpha_acceptance import IDENTITY, contract
from test_alpha_evidence import run_pytest
from test_alpha_evidence import source as source

from proofmap.integrity import artifact_digest, load_json, write_json
from scripts import check_alpha_acceptance as checker
from scripts import windows_pytest_partitions as partitions
from scripts.alpha_evidence import _envelope


@pytest.fixture
def recorded_parts(tmp_path):
    root = tmp_path / "coverage-source"
    (root / "proofmap").mkdir(parents=True)
    # Small explicitly synthetic branch databases exercise artifact reconstruction.
    for name in sorted(partitions.CRITICAL):
        (root / "proofmap" / (name + ".py")).write_text("value = 1\n")
    (root / "schema").mkdir()
    for name in ("alpha_evidence", "alpha_acceptance"):
        (root / "schema" / (name + ".schema.json")).write_bytes(
            (checker.ROOT / "schema" / (name + ".schema.json")).read_bytes()
        )
    folder = tmp_path / "artifacts"
    folder.mkdir()
    full = [f"tests/test_example.py::test_{i:03d}" for i in range(32)]
    env = {
        "platform": "win32",
        "python": [3, 12, 14],
        "machine": "AMD64",
        "packages": {
            "pytest": "9.1.1",
            "pytest-cov": "7.1.0",
            "coverage": "7.16.1",
            "proof-map-boundary-analysis": IDENTITY["package_version"],
        },
    }
    records = []
    for index in range(4):
        part = folder / "parts" / str(index)
        part.mkdir(parents=True)
        chosen = partitions.selected(full, index)
        write_json(
            part / "collection.json",
            {"inventory": full, "selected": chosen, "index": index, "config": partitions.CONFIG},
        )
        report = _envelope(
            IDENTITY,
            "python-tests",
            partitions.PROFILE,
            "pytest",
            0,
            True,
            [{"nodeid": node, "outcome": "passed"} for node in chosen],
            [],
        )
        write_json(part / "pytest-report.json", report)
        data = CoverageData(basename=str(part / "coverage.data"))
        data.add_arcs(
            {
                f"C:/qualification/proofmap/{name}.py": [(-1, 1), (1, -1)]
                for name in sorted(partitions.CRITICAL)
            }
        )
        data.write()
        record = {
            "schema_version": "1.0",
            "identity": IDENTITY,
            "index": index,
            "config": partitions.CONFIG,
            "environment": env,
            "source_root": "C:/qualification",
            "exit_code": 0,
            "collection": partitions.descriptor(part / "collection.json"),
            "pytest": partitions.descriptor(part / "pytest-report.json"),
            "coverage": partitions.descriptor(part / "coverage.data"),
        }
        write_json(part / "partition.json", record)
        records.append(
            {
                "path": f"parts/{index}/partition.json",
                "sha256": artifact_digest((part / "partition.json").read_bytes()),
            }
        )
    parsed = [partitions.read_partition(folder / item["path"], IDENTITY) for item in records]
    report = partitions.combined_report(parsed, IDENTITY)
    partitions.coverage_report(parsed, root, folder / "coverage.json")
    write_json(
        folder / "full-collection.json",
        {"inventory": full, "selected": full, "index": None, "config": partitions.CONFIG},
    )
    write_json(
        folder / "inventory-run.json",
        {
            "identity": IDENTITY,
            "environment": env,
            "exit_code": 0,
            "command": [
                "C:/Python312/python.exe",
                "-m",
                "pytest",
                "-p",
                "scripts.windows_pytest_partitions",
                "--windows-inventory-only",
                "--windows-partition-collection",
                "C:/out/full-collection.json",
                "--rootdir",
                "C:/qualification",
                "-c",
                "C:/qualification/pyproject.toml",
                "--collect-only",
                "-q",
            ],
            "collection": partitions.descriptor(folder / "full-collection.json"),
        },
    )
    value = {
        "schema_version": "1.0",
        "kind": "windows-partitioned-regression",
        "identity": IDENTITY,
        "config": partitions.CONFIG,
        "partitions": records,
        "pytest_evidence": report,
        "coverage": partitions.descriptor(folder / "coverage.json"),
        "inventory_run": partitions.descriptor(folder / "inventory-run.json"),
    }
    return root, folder, value


def rehash_part(folder, value, index):
    part = folder / "parts" / str(index)
    record = load_json(part / "partition.json")
    for key, name in (
        ("collection", "collection.json"),
        ("pytest", "pytest-report.json"),
        ("coverage", "coverage.data"),
    ):
        record[key] = partitions.descriptor(part / name)
    write_json(part / "partition.json", record)
    value["partitions"][index]["sha256"] = artifact_digest((part / "partition.json").read_bytes())


def test_complete_synthetic_partitions_reconstruct_exact_outcomes_and_branch_coverage(
    recorded_parts,
):
    root, folder, value = recorded_parts
    report = partitions.validate_outcomes(value, folder, IDENTITY, root)
    assert report == value["pytest_evidence"] and len(report["tests"]) == 32
    coverage = load_json(folder / "coverage.json")
    assert coverage["meta"]["branch_coverage"] is True
    assert coverage["totals"]["percent_covered"] == 100


def test_real_miniature_pytest_and_branch_data_aggregate(recorded_parts, source, monkeypatch):
    """Real subprocess measurements with explicitly synthetic profile metadata."""
    toy_root, folder, value = recorded_parts
    (source / "proofmap").mkdir()
    for path in (toy_root / "proofmap").glob("*.py"):
        (source / "proofmap" / path.name).write_bytes(path.read_bytes())
    project = source / "pyproject.toml"
    project.write_text(project.read_text().replace("1.2.3", IDENTITY["package_version"]))
    code = "from pathlib import Path\n"
    code += "\n".join(
        f"def test_{i:03d}():\n"
        "    for path in (Path(__file__).parent / 'proofmap').glob('*.py'):\n"
        "        exec(compile(path.read_bytes(), str(path), 'exec'), {})\n"
        for i in range(24)
    )
    for index in range(4):
        part = folder / "parts" / str(index)
        (part / "coverage.data").unlink()
        monkeypatch.setenv("COVERAGE_FILE", str(part / "coverage.data"))
        result, report = run_pytest(
            source,
            code,
            "-p",
            "scripts.windows_pytest_partitions",
            "-p",
            "pytest_cov",
            "--alpha-job",
            "python-tests",
            "--alpha-profile",
            partitions.PROFILE,
            "--rootdir",
            str(source),
            "-c",
            str(source / "pyproject.toml"),
            "--alpha-source-root",
            str(source),
            "--windows-partition-index",
            str(index),
            "--windows-partition-collection",
            str(part / "collection.json"),
            "--cov=" + str(source / "proofmap"),
            "--cov-branch",
            "--cov-fail-under=0",
            "--cov-report=",
        )
        assert result.returncode == 0 and report["status"] == "PASS"
        write_json(part / "pytest-report.json", report)
        record = load_json(part / "partition.json")
        record.update(identity=report["identity"], source_root=str(source))
        write_json(part / "partition.json", record)
        rehash_part(folder, value, index)
    expected = report["identity"]
    parsed = [
        partitions.read_partition(folder / item["path"], expected) for item in value["partitions"]
    ]
    value["identity"] = expected
    value["pytest_evidence"] = partitions.combined_report(parsed, expected)
    partitions.coverage_report(parsed, source, folder / "coverage.json")
    value["coverage"] = partitions.descriptor(folder / "coverage.json")
    result, _ = run_pytest(
        source,
        code,
        "-p",
        "scripts.windows_pytest_partitions",
        "--windows-inventory-only",
        "--windows-partition-collection",
        str(folder / "full-collection.json"),
        "--rootdir",
        str(source),
        "-c",
        str(source / "pyproject.toml"),
        "--alpha-source-root",
        str(source),
        "--collect-only",
    )
    assert result.returncode == 0
    run_record = load_json(folder / "inventory-run.json")
    run_record.update(
        identity=expected, collection=partitions.descriptor(folder / "full-collection.json")
    )
    write_json(folder / "inventory-run.json", run_record)
    value["inventory_run"] = partitions.descriptor(folder / "inventory-run.json")
    checked = partitions.validate_outcomes(value, folder, expected, source)
    assert len(checked["tests"]) == 24 and checked["status"] == "PASS"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "index-bool",
        "mixed-source",
        "mixed-run",
        "mixed-version",
        "environment",
        "selection",
        "missing-outcome",
        "extra-outcome",
        "failed",
        "error",
        "exit",
        "overlap",
        "coverage-bytes",
        "coverage-claim",
        "statement-only",
        "foreign-path",
        "inventories",
        "all-inventories",
        "final-outcome",
        "inventory-run",
        "filter-command",
    ],
)
def test_rehashed_malformed_partition_material_cannot_qualify(recorded_parts, mutation):
    root, folder, value = recorded_parts
    part = folder / "parts/0"
    record = load_json(part / "partition.json")
    collection = load_json(part / "collection.json")
    report = load_json(part / "pytest-report.json")
    if mutation == "missing":
        value["partitions"].pop()
    elif mutation == "duplicate":
        value["partitions"][1] = deepcopy(value["partitions"][0])
    elif mutation == "index-bool":
        record["index"] = False
    elif mutation.startswith("mixed-"):
        key = {
            "mixed-source": "source_fingerprint",
            "mixed-run": "run_attempt",
            "mixed-version": "package_version",
        }[mutation]
        record["identity"][key] = "wrong"
    elif mutation == "environment":
        record["environment"]["python"] = [3, 14, 0]
    elif mutation == "selection":
        collection["selected"].pop()
    elif mutation == "missing-outcome":
        report["tests"].pop()
    elif mutation == "extra-outcome":
        report["tests"].append({"nodeid": "uncollected", "outcome": "passed"})
    elif mutation in {"failed", "error"}:
        report["tests"][0]["outcome"] = mutation
    elif mutation == "exit":
        record["exit_code"] = 1
    elif mutation == "overlap":
        report["tests"].append(deepcopy(report["tests"][0]))
    elif mutation == "coverage-bytes":
        (part / "coverage.data").write_bytes(b"not a coverage database")
    elif mutation == "coverage-claim":
        coverage = load_json(folder / "coverage.json")
        coverage["totals"]["covered_lines"] += 1
        write_json(folder / "coverage.json", coverage)
        value["coverage"] = partitions.descriptor(folder / "coverage.json")
    elif mutation in {"statement-only", "foreign-path"}:
        path = part / "coverage.data"
        path.unlink()
        data = CoverageData(basename=str(path))
        if mutation == "statement-only":
            data.add_lines({"C:/qualification/proofmap/integrity.py": [1]})
        else:
            data.add_arcs({"C:/another-source/proofmap/integrity.py": [(-1, 1), (1, -1)]})
        data.write()
    elif mutation == "inventories":
        collection["inventory"].append("zzz")
    elif mutation == "all-inventories":
        removed = collection["inventory"][0]
        for index in range(4):
            directory = folder / "parts" / str(index)
            item = load_json(directory / "collection.json")
            item["inventory"].remove(removed)
            item["selected"] = partitions.selected(item["inventory"], index)
            write_json(directory / "collection.json", item)
            result = load_json(directory / "pytest-report.json")
            result["tests"] = [t for t in result["tests"] if t["nodeid"] != removed]
            write_json(directory / "pytest-report.json", result)
            rehash_part(folder, value, index)
        value["pytest_evidence"]["tests"] = [
            t for t in value["pytest_evidence"]["tests"] if t["nodeid"] != removed
        ]
        with pytest.raises(ValueError, match="independent inventory mismatch"):
            partitions.validate_outcomes(value, folder, IDENTITY, root)
        return
    elif mutation == "final-outcome":
        value["pytest_evidence"]["tests"][0]["outcome"] = "skipped"
    else:
        run_record = load_json(folder / "inventory-run.json")
        if mutation == "inventory-run":
            run_record["exit_code"] = 2
        else:
            run_record["command"] += ["-k", "selected"]
        write_json(folder / "inventory-run.json", run_record)
        value["inventory_run"] = partitions.descriptor(folder / "inventory-run.json")
    write_json(part / "partition.json", record)
    write_json(part / "collection.json", collection)
    write_json(part / "pytest-report.json", report)
    if mutation not in {"missing", "duplicate"}:
        rehash_part(folder, value, 0)
    with pytest.raises(ValueError):
        partitions.validate_outcomes(value, folder, IDENTITY, root)


def test_real_pytest_partition_hooks_preserve_complete_inventory_and_exact_union(source):
    code = "\n".join(f"def test_{index:03d}(): pass" for index in range(24))
    reports, inventories = [], []
    for index in range(4):
        path = source / ".work" / f"collection-{index}.json"
        result, report = run_pytest(
            source,
            code,
            "-p",
            "scripts.windows_pytest_partitions",
            "--windows-partition-index",
            str(index),
            "--windows-partition-collection",
            str(path),
        )
        assert result.returncode == 0 and report["status"] == "PASS"
        collection = load_json(path)
        assert [test["nodeid"] for test in report["tests"]] == collection["selected"]
        reports.extend(test["nodeid"] for test in report["tests"])
        inventories.append(collection["inventory"])
    assert all(full == inventories[0] for full in inventories)
    assert sorted(reports) == inventories[0] and len(reports) == 24


@pytest.mark.parametrize("boundary", ["overall", "critical"])
def test_reconstructed_coverage_keeps_overall_and_critical_thresholds(recorded_parts, boundary):
    root, folder, value = recorded_parts
    extra = root / "proofmap" / "extra.py"
    extra.write_text("value = 1\n" * 20)
    if boundary == "critical":
        (root / "proofmap" / "integrity.py").write_text("value = 1\nvalue = 2\n")
        data = CoverageData(basename=str(folder / "parts/0/coverage.data"))
        data.read()
        data.add_arcs(
            {
                "C:/qualification/proofmap/extra.py": [
                    (-1, 1),
                    *[(line, line + 1) for line in range(1, 20)],
                    (20, -1),
                ]
            }
        )
        data.write()
        rehash_part(folder, value, 0)
    parts = [
        partitions.read_partition(folder / item["path"], IDENTITY) for item in value["partitions"]
    ]
    with pytest.raises(ValueError, match=boundary + " coverage below"):
        partitions.coverage_report(parts, root, folder / "failed-coverage.json")


@pytest.mark.parametrize(
    "options", [["-k", "test_000"], ["--ignore", "absent.py"], ["--collect-only"]]
)
def test_partition_hooks_refuse_filtering_or_nonexecution(source, options):
    code = "\n".join(f"def test_{index:03d}(): pass" for index in range(24))
    with pytest.raises(AssertionError):
        # Configuration fails before capture creates an envelope; absence is failure.
        run_pytest(
            source,
            code,
            "-p",
            "scripts.windows_pytest_partitions",
            "--windows-partition-index",
            "0",
            "--windows-partition-collection",
            str(source / ".work/collection.json"),
            *options,
        )


@pytest.mark.parametrize("missing", [False, True])
def test_readiness_requires_exact_companion_for_windows_profile(
    recorded_parts, monkeypatch, missing
):
    root, folder, value = recorded_parts
    monkeypatch.setattr(checker, "ROOT", root)
    write_json(folder / "outcomes.json", value)
    manifest, baseline = contract()
    selectors = [test["nodeid"] for test in value["pytest_evidence"]["tests"][:2]]
    for group in ("requirements", "fixture_categories", "scenarios"):
        for row in manifest[group]:
            row["positive_tests"], row["negative_tests"] = selectors[:1], selectors[1:]
            row["required_profiles"] = [partitions.PROFILE]
    reports = [value["pytest_evidence"]]
    if not missing:
        reports.append(
            _envelope(
                IDENTITY,
                "windows-regression",
                "partitioned-regression",
                "command",
                0,
                True,
                [],
                [
                    {
                        "name": "partitioned-regression-outcomes",
                        **partitions.descriptor(folder / "outcomes.json"),
                    }
                ],
            )
        )
    result = checker.evaluate(manifest, baseline, reports, IDENTITY, [folder] * len(reports))
    assert result["ready"] is (not missing)
    if missing:
        assert "WINDOWS_PARTITION_REPORT_MISSING_OR_DIFFERENT" in result["errors"]
