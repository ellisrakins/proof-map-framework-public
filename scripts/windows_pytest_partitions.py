"""Four observed Windows pytest partitions, with complete-inventory qualification.

Only the aggregation creates the ordinary Windows profile envelope. Raw records
remain available and are checked again by alpha-readiness; no verdict is cached.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path, PureWindowsPath
from typing import Any, cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proofmap.integrity import (
    artifact_digest,
    canonical_bytes,
    load_json,
    relative_path,
    rooted_path,
    write_json,
)
from scripts.alpha_evidence import _envelope, _unchanged, identity

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "python-windows-3.12"
RULE = "sha256-utf8-nodeid-modulo-four.v1"
COUNT = 4
MAX_BYTES = 64_000_000
CRITICAL = {"integrity", "kernel", "trust", "runner", "replay"}
CONFIG = {
    "rule": RULE,
    "count": COUNT,
    "profile": PROFILE,
    "coverage_source": "proofmap",
    "branch": True,
    "overall_minimum": 85,
    "critical_minimum": 90,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError("WINDOWS_PARTITION: " + message)


def selected(inventory: list[str], index: int) -> list[str]:
    require(type(index) is int and 0 <= index < COUNT, "index")
    return [node for node in inventory if int(artifact_digest(node.encode()), 16) % COUNT == index]


def inventory_ids(value: Any) -> list[str]:
    require(isinstance(value, list) and 0 < len(value) <= 100_000, "inventory shape")
    require(
        all(isinstance(node, str) and 0 < len(node) <= 4096 for node in value), "inventory node"
    )
    require(value == sorted(set(value)), "inventory duplicate/order")
    return cast(list[str], value)


def environment() -> dict[str, Any]:
    return {
        "platform": sys.platform,
        "python": list(sys.version_info[:3]),
        "machine": platform.machine(),
        "packages": {
            name: version(name)
            for name in ("pytest", "pytest-cov", "coverage", "proof-map-boundary-analysis")
        },
    }


def validate_environment(value: Any, expected: dict[str, Any]) -> None:
    require(isinstance(value, dict), "environment")
    require(set(value) == {"platform", "python", "machine", "packages"}, "environment fields")
    require(value["platform"] == "win32", "Windows execution required")
    python = value["python"]
    require(
        isinstance(python, list)
        and len(python) == 3
        and all(type(part) is int and part >= 0 for part in python)
        and python[:2] == [3, 12],
        "Python 3.12 execution required",
    )
    require(isinstance(value["machine"], str) and bool(value["machine"]), "machine")
    packages = value["packages"]
    require(
        isinstance(packages, dict)
        and set(packages) == {"pytest", "pytest-cov", "coverage", "proof-map-boundary-analysis"}
        and all(isinstance(v, str) and bool(v) for v in packages.values())
        and packages["proof-map-boundary-analysis"] == expected["package_version"],
        "package versions",
    )


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("Windows qualification partition")
    group.addoption("--windows-partition-index", type=int, default=None)
    group.addoption("--windows-partition-collection", default=None)
    group.addoption("--windows-inventory-only", action="store_true", default=False)


def pytest_configure(config: Any) -> None:
    index = config.getoption("windows_partition_index")
    inventory_only = config.getoption("windows_inventory_only")
    if index is None and not inventory_only:
        return
    import pytest

    require((index is None) == inventory_only, "inventory/index modes")
    if index is not None:
        require(type(index) is int and 0 <= index < COUNT, "index")
    path = config.getoption("windows_partition_collection")
    require(bool(path), "collection output missing")
    require(not config.option.keyword and not config.option.markexpr, "test filtering forbidden")
    require(not config.getoption("deselect", default=[]), "deselection forbidden")
    require(bool(config.option.collectonly) == inventory_only, "collect-only mode")
    require(
        not os.environ.get("PYTEST_ADDOPTS") and not config.getini("addopts"), "addopts forbidden"
    )
    require(not config.getini("testpaths"), "testpaths filtering forbidden")
    require(
        not config.getoption("ignore", default=[])
        and not config.getoption("ignore_glob", default=[]),
        "ignored paths forbidden",
    )
    # Observe the complete collection before any selection hook, and enforce that
    # the selected set survives every subsequent hook without being reduced.
    pytest.hookimpl(wrapper=True, tryfirst=True)(_Partition.pytest_collection_modifyitems)
    config.pluginmanager.register(_Partition(index, Path(path)))


class _Partition:
    def __init__(self, index: int | None, path: Path) -> None:
        self.index, self.path = index, path

    def pytest_collection_modifyitems(self, session: Any, config: Any, items: list[Any]) -> Any:
        full = inventory_ids(sorted(item.nodeid for item in items))
        chosen = full if self.index is None else selected(full, self.index)
        require(bool(chosen), "empty partition")
        yield
        require(sorted(item.nodeid for item in items) == full, "collection was filtered")
        chosen_set = set(chosen)
        removed = [item for item in items if item.nodeid not in chosen_set]
        items[:] = [item for item in items if item.nodeid in chosen_set]
        config.hook.pytest_deselected(items=removed)
        write_json(
            self.path,
            {"inventory": full, "selected": chosen, "index": self.index, "config": CONFIG},
        )


def descriptor(path: Path) -> dict[str, str]:
    require(path.is_file() and not path.is_symlink(), "missing/linked artifact")
    require(path.stat().st_size <= MAX_BYTES, "artifact size")
    return {"path": path.name, "sha256": artifact_digest(path.read_bytes())}


def material_path(folder: Path, entry: Any) -> Path:
    require(isinstance(entry, dict) and set(entry) == {"path", "sha256"}, "artifact descriptor")
    require(isinstance(entry["path"], str), "artifact path")
    path = rooted_path(folder, relative_path(entry["path"]))
    require(path.is_file() and path.stat().st_size <= MAX_BYTES, "artifact missing/size")
    require(artifact_digest(path.read_bytes()) == entry["sha256"], "artifact digest")
    return path


def run(index: int, out: Path) -> int:
    from scripts.test_installed_wheel import run_process_tree

    started = identity(ROOT, ROOT / "acceptance/paper_ci_alpha.json")
    observed = environment()
    validate_environment(observed, started)
    selected(["index-validation"], index)
    require(not os.environ.get("PYTEST_ADDOPTS"), "PYTEST_ADDOPTS forbidden")
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "scripts.alpha_evidence",
        "-p",
        "scripts.windows_pytest_partitions",
        "--alpha-evidence",
        str(out / "pytest-report.json"),
        "--alpha-job",
        "python-tests",
        "--alpha-profile",
        PROFILE,
        "--alpha-source-root",
        str(ROOT),
        "--rootdir",
        str(ROOT),
        "-c",
        str(ROOT / "pyproject.toml"),
        "--windows-partition-index",
        str(index),
        "--windows-partition-collection",
        str(out / "collection.json"),
        "-q",
        "--durations=10",
        "--cov=proofmap",
        "--cov-branch",
        "--cov-fail-under=0",
        "--cov-report=",
        "--basetemp",
        str(out / "tmp"),
    ]
    env = {**os.environ, "COVERAGE_FILE": str(out / "coverage.data")}
    code = run_process_tree(command, cwd=ROOT, env=env, timeout=1080)
    require(_unchanged(ROOT, ROOT / "acceptance/paper_ci_alpha.json", started), "source changed")
    write_json(
        out / "partition.json",
        {
            "schema_version": "1.0",
            "identity": started,
            "index": index,
            "config": CONFIG,
            "environment": observed,
            "source_root": str(ROOT),
            "exit_code": code,
            "collection": descriptor(out / "collection.json"),
            "pytest": descriptor(out / "pytest-report.json"),
            "coverage": descriptor(out / "coverage.data"),
        },
    )
    return code


def read_partition(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    from scripts.check_alpha_acceptance import validate_report

    require(path.is_file() and path.stat().st_size <= MAX_BYTES, "partition missing/size")
    value = load_json(path)
    require(
        isinstance(value, dict)
        and set(value)
        == {
            "schema_version",
            "identity",
            "index",
            "config",
            "environment",
            "source_root",
            "exit_code",
            "collection",
            "pytest",
            "coverage",
        },
        "partition fields",
    )
    require(
        value["schema_version"] == "1.0" and value["identity"] == expected, "partition identity"
    )
    require(canonical_bytes(value["config"]) == canonical_bytes(CONFIG), "partition configuration")
    validate_environment(value["environment"], expected)
    require(
        type(value["exit_code"]) is int and value["exit_code"] == 0, "partition execution failed"
    )
    index = value["index"]
    selected(["index-validation"], index)
    collection = load_json(material_path(path.parent, value["collection"]))
    require(
        isinstance(collection, dict)
        and set(collection) == {"inventory", "selected", "index", "config"},
        "collection fields",
    )
    full = inventory_ids(collection["inventory"])
    chosen = selected(full, index)
    require(
        bool(chosen)
        and type(collection["index"]) is int
        and collection["index"] == index
        and canonical_bytes(collection["config"]) == canonical_bytes(CONFIG)
        and collection["selected"] == chosen,
        "partition selection",
    )
    report = load_json(material_path(path.parent, value["pytest"]))
    require(not validate_report(report, expected, None), "pytest envelope")
    require(
        report["job"] == "python-tests"
        and report["profile"] == PROFILE
        and report["kind"] == "pytest"
        and report["status"] == "PASS"
        and report["exit_code"] == 0
        and not report["artifacts"],
        "pytest execution failed",
    )
    require(
        sorted(test["nodeid"] for test in report["tests"]) == chosen, "pytest outcomes incomplete"
    )
    require(
        all(test["outcome"] not in {"failed", "error"} for test in report["tests"]),
        "pytest failure",
    )
    coverage = material_path(path.parent, value["coverage"])
    require(isinstance(value["source_root"], str) and bool(value["source_root"]), "source root")
    return {"record": value, "inventory": full, "report": report, "coverage": coverage}


def combined_report(parts: list[dict[str, Any]], expected: dict[str, Any]) -> dict[str, Any]:
    require(len(parts) == COUNT, "exactly four partitions required")
    require(
        {part["record"]["index"] for part in parts} == set(range(COUNT)),
        "missing/duplicate partition",
    )
    full = parts[0]["inventory"]
    require(all(part["inventory"] == full for part in parts), "mixed inventories")
    require(
        all(part["record"]["environment"] == parts[0]["record"]["environment"] for part in parts),
        "mixed environments",
    )
    tests = [test for part in parts for test in part["report"]["tests"]]
    require(
        sorted(test["nodeid"] for test in tests) == full, "outcomes overlap or incomplete union"
    )
    return _envelope(
        expected,
        "python-tests",
        PROFILE,
        "pytest",
        0,
        True,
        sorted(tests, key=lambda test: test["nodeid"]),
        [],
    )


def _source_name(raw: str, source_root: str) -> str:
    path, prefix = raw.replace("\\", "/"), source_root.replace("\\", "/").rstrip("/") + "/"
    require(path.casefold().startswith(prefix.casefold()), "foreign coverage root")
    name = relative_path(path[len(prefix) :])
    require(name.startswith("proofmap/") and name.endswith(".py"), "foreign coverage source")
    return name


def _coverage_report(parts: list[dict[str, Any]], root: Path, output: Path) -> dict[str, Any]:
    from coverage import Coverage, CoverageData

    # Include unmeasured modules in the denominator, as --cov=proofmap does in
    # the original complete run. Loading only observed arcs could inflate totals.
    arcs: dict[str, set[tuple[int, int]]] = {
        str(rooted_path(root, path.relative_to(root).as_posix())): set()
        for path in (root / "proofmap").rglob("*.py")
    }
    require(bool(arcs), "coverage source inventory empty")
    for part in parts:
        data = CoverageData(basename=str(part["coverage"]))
        data.read()
        require(data.has_arcs() and bool(data.measured_files()), "branch coverage missing")
        for raw in data.measured_files():
            name = _source_name(raw, part["record"]["source_root"])
            source = rooted_path(root, name)
            require(source.is_file(), "coverage source missing")
            arcs.setdefault(str(source), set()).update(data.arcs(raw) or [])
    cov = Coverage(data_file=None, config_file=False, source=[str(root / "proofmap")], branch=True)
    cov.get_data().add_arcs({name: sorted(values) for name, values in arcs.items()})
    cov.get_data().touch_files(list(arcs))
    cov.json_report(outfile=str(output))
    result = load_json(output)
    require(result["meta"]["branch_coverage"] is True, "combined branch coverage missing")
    require(result["totals"]["percent_covered"] >= 85, "overall coverage below 85")
    seen = set()
    for name, value in result["files"].items():
        stem = Path(name).stem
        if stem in CRITICAL:
            seen.add(stem)
            require(
                value["summary"]["percent_covered"] >= 90, "critical coverage below 90: " + stem
            )
    require(seen == CRITICAL, "critical coverage modules missing")
    return cast(dict[str, Any], result)


def coverage_report(parts: list[dict[str, Any]], root: Path, output: Path) -> dict[str, Any]:
    from coverage.exceptions import CoverageException

    try:
        return _coverage_report(parts, root, output)
    except CoverageException as exc:
        raise ValueError("WINDOWS_PARTITION: invalid coverage data: " + str(exc)) from exc


def coverage_material(value: dict[str, Any]) -> dict[str, Any]:
    # Timestamp and host-specific path prefixes are not measured coverage.
    files = {}
    for name, material in value["files"].items():
        name = name.replace("\\", "/")
        marker = name.rfind("proofmap/")
        require(marker >= 0, "coverage JSON source")
        relative = relative_path(name[marker:])
        require(relative not in files, "duplicate coverage JSON source")
        files[relative] = material
    return {"branch": value["meta"]["branch_coverage"], "totals": value["totals"], "files": files}


def validate_outcomes(
    value: Any, directory: Path, expected: dict[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    require(
        isinstance(value, dict)
        and set(value)
        == {
            "schema_version",
            "kind",
            "identity",
            "config",
            "partitions",
            "pytest_evidence",
            "coverage",
            "inventory_run",
        },
        "aggregation fields",
    )
    require(
        value["schema_version"] == "1.0" and value["kind"] == "windows-partitioned-regression",
        "aggregation kind",
    )
    require(
        value["identity"] == expected
        and canonical_bytes(value["config"]) == canonical_bytes(CONFIG),
        "aggregation identity/config",
    )
    require(
        isinstance(value["partitions"], list) and len(value["partitions"]) == COUNT,
        "aggregation partitions",
    )
    parts = [
        read_partition(material_path(directory, item), expected) for item in value["partitions"]
    ]
    report = combined_report(parts, expected)
    run_record = load_json(material_path(directory, value["inventory_run"]))
    require(
        isinstance(run_record, dict)
        and set(run_record)
        == {
            "identity",
            "environment",
            "exit_code",
            "command",
            "collection",
        },
        "inventory execution fields",
    )
    require(
        run_record["identity"] == expected
        and type(run_record["exit_code"]) is int
        and run_record["exit_code"] == 0,
        "inventory execution identity/status",
    )
    require(run_record["environment"] == parts[0]["record"]["environment"], "inventory environment")
    command = run_record["command"]
    require(
        isinstance(command, list)
        and len(command) == 14
        and all(isinstance(arg, str) for arg in command)
        and PureWindowsPath(command[0]).is_absolute()
        and PureWindowsPath(command[0]).name.lower() == "python.exe"
        and command[1:7]
        == [
            "-m",
            "pytest",
            "-p",
            "scripts.windows_pytest_partitions",
            "--windows-inventory-only",
            "--windows-partition-collection",
        ]
        and PureWindowsPath(command[7]).name == "full-collection.json"
        and command[8] == "--rootdir"
        and PureWindowsPath(command[9]).is_absolute()
        and command[10] == "-c"
        and PureWindowsPath(command[11]) == PureWindowsPath(command[9]) / "pyproject.toml"
        and command[12:] == ["--collect-only", "-q"],
        "inventory command",
    )
    collection = load_json(material_path(directory, run_record["collection"]))
    require(
        isinstance(collection, dict)
        and set(collection) == {"inventory", "selected", "index", "config"}
        and collection["index"] is None
        and collection["inventory"] == parts[0]["inventory"]
        and collection["selected"] == collection["inventory"]
        and canonical_bytes(collection["config"]) == canonical_bytes(CONFIG),
        "independent inventory mismatch",
    )
    require(
        canonical_bytes(value["pytest_evidence"]) == canonical_bytes(report),
        "aggregate pytest mismatch",
    )
    saved = load_json(material_path(directory, value["coverage"]))
    with tempfile.TemporaryDirectory(prefix="proofmap-partition-coverage-") as temporary:
        checked = coverage_report(parts, root, Path(temporary) / "coverage.json")
    require(
        canonical_bytes(coverage_material(saved)) == canonical_bytes(coverage_material(checked)),
        "aggregate coverage mismatch",
    )
    return report


def aggregate(parts_root: Path, out: Path) -> int:
    from scripts.test_installed_wheel import run_process_tree

    expected = identity(ROOT, ROOT / "acceptance/paper_ci_alpha.json")
    validate_environment(environment(), expected)
    paths = sorted(parts_root.rglob("partition.json"))
    require(len(paths) == COUNT, "exactly four partition files required")
    parts = [read_partition(path, expected) for path in paths]
    report = combined_report(parts, expected)
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    require(not os.environ.get("PYTEST_ADDOPTS"), "PYTEST_ADDOPTS forbidden")
    inventory_command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "scripts.windows_pytest_partitions",
        "--windows-inventory-only",
        "--windows-partition-collection",
        str(out / "full-collection.json"),
        "--rootdir",
        str(ROOT),
        "-c",
        str(ROOT / "pyproject.toml"),
        "--collect-only",
        "-q",
    ]
    code = run_process_tree(inventory_command, cwd=ROOT, env=dict(os.environ), timeout=120)
    require(code == 0, "independent collection failed")
    collection = load_json(out / "full-collection.json")
    require(collection["inventory"] == parts[0]["inventory"], "independent inventory mismatch")
    write_json(
        out / "inventory-run.json",
        {
            "identity": expected,
            "environment": environment(),
            "exit_code": code,
            "command": inventory_command,
            "collection": descriptor(out / "full-collection.json"),
        },
    )
    records = []
    for path, part in zip(paths, parts, strict=True):
        folder = out / "parts" / str(part["record"]["index"])
        folder.mkdir(parents=True)
        for key in ("collection", "pytest", "coverage"):
            source = material_path(path.parent, part["record"][key])
            shutil.copyfile(source, folder / source.name)
        write_json(folder / "partition.json", part["record"])
        records.append(
            {
                "path": (folder / "partition.json").relative_to(out).as_posix(),
                "sha256": artifact_digest((folder / "partition.json").read_bytes()),
            }
        )
    coverage_report(parts, ROOT, out / "coverage.json")
    value = {
        "schema_version": "1.0",
        "kind": "windows-partitioned-regression",
        "identity": expected,
        "config": CONFIG,
        "partitions": records,
        "pytest_evidence": report,
        "coverage": descriptor(out / "coverage.json"),
        "inventory_run": descriptor(out / "inventory-run.json"),
    }
    validate_outcomes(value, out, expected)
    require(
        _unchanged(ROOT, ROOT / "acceptance/paper_ci_alpha.json", expected),
        "aggregation source changed",
    )
    write_json(out / "outcomes.json", value)
    write_json(out / "pytest-evidence.json", report)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--index", type=int, choices=range(COUNT), required=True)
    run_parser.add_argument("--out", type=Path, required=True)
    aggregate_parser = sub.add_parser("aggregate")
    aggregate_parser.add_argument("--parts", type=Path, required=True)
    aggregate_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(args.index, args.out) if args.mode == "run" else aggregate(args.parts, args.out)
    except Exception as exc:
        print(f"Windows partition qualification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
