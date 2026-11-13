"""Run public campaign CLI from the candidate wheel outside the checkout."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proofmap.integrity import load_json, write_json
from scripts.alpha_evidence import identity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--profile", choices=("offline", "isolated"), required=True)
    parser.add_argument("--execution-profile", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    root, wheel, out = (
        args.source_root.resolve(strict=True),
        args.wheel.resolve(strict=True),
        args.out.resolve(),
    )
    candidate = identity(root, root / "acceptance/paper_ci_alpha.json")
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "candidate-identity.json", candidate)
    if args.profile == "isolated" and args.execution_profile is None:
        parser.error("isolated requires --execution-profile")
    with tempfile.TemporaryDirectory(prefix="proofmap-campaign-installed-") as directory:
        temporary = Path(directory)
        environment = temporary / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run(
            [
                str(python),
                "-I",
                "-m",
                "pip",
                "install",
                "-c",
                str(root / "constraints-ci.txt"),
                str(wheel) + "[paper,trust]",
            ],
            cwd=temporary,
            check=True,
            timeout=300,
        )
        fixtures = temporary / "fixtures"
        shutil.copytree(root / "tests/fixtures/campaign/operational", fixtures)
        command = [
            str(python),
            "-I",
            "-m",
            "proofmap.cli",
            "validate-research-conops",
            "--profile",
            args.profile,
            "--fixtures",
            str(fixtures),
            "--wheel",
            str(wheel),
            "--identity",
            str(out / "candidate-identity.json"),
            "--out",
            str(out),
        ]
        if args.execution_profile is not None:
            command.extend(
                ["--execution-profile", str(args.execution_profile.resolve(strict=True))]
            )
        process = subprocess.run(
            command, cwd=temporary, capture_output=True, text=True, encoding="utf-8", timeout=600
        )
        (out / "cli.stdout.txt").write_text(process.stdout, encoding="utf-8")
        (out / "cli.stderr.txt").write_text(process.stderr, encoding="utf-8")
        if process.returncode:
            raise RuntimeError("Installed public campaign CLI failed: " + process.stderr)
        value = load_json(out / "campaign-outcomes.json")
        if (
            not value["material"]["installed"]
            or value["candidate_identity"] != candidate
            or value["validation"] != "PASS"
        ):
            raise ValueError("Installed candidate material or outcomes did not qualify")
    print("Installed campaign", args.profile, "PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
