"""Install the built wheel in an isolated venv and work away from the checkout."""

import argparse
import os
import shutil
import subprocess
import tempfile
import venv
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--audit-wheel", type=Path, help="Copy the wheel only after its smoke checks pass"
)
parser.add_argument(
    "--offline-outcomes",
    type=Path,
    default=Path(".work/alpha-offline-outcomes.json"),
    help="Write actual installed-wheel scenario C/D outcomes after all assertions pass",
)
args = parser.parse_args()

wheels = list(Path("dist").glob("*.whl"))
assert len(wheels) == 1
wheel = wheels[0].resolve()
fixture = Path("tests/fixtures/papers/train/basic.tex").resolve()
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    venv.EnvBuilder(with_pip=True).create(root / "env")
    python = root / "env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "-c",
            str(Path("constraints-ci.txt").resolve()),
            str(wheel),
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(
        [
            str(python),
            "-c",
            "from proofmap.schema import schema; assert schema('kernel')['$id']=='urn:proofmap:kernel:1'; from proofmap.kernel import KernelMap, closure; assert not closure(KernelMap()).closed",
        ],
        cwd=root,
        check=True,
    )

    subprocess.run([str(python), "-m", "proofmap.cli", "--help"], cwd=root, check=True)
    # Now install the declared optional dependencies, not the source checkout.
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "-c",
            str(Path("constraints-ci.txt").resolve()),
            str(wheel) + "[paper,trust]",
        ],
        cwd=root,
        check=True,
    )
    shutil.copyfile(fixture, root / "paper.tex")
    subprocess.run(
        [
            str(python),
            "-m",
            "proofmap.cli",
            "paper",
            "ci",
            "paper.tex",
            "--out",
            "result",
            "--store",
            "store",
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(
        [str(python), "-m", "proofmap.cli", "paper", "list", "--store", "store"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        [str(python), "-m", "proofmap.cli", "paper", "assess", "result"], cwd=root, check=True
    )
    subprocess.run(
        [
            str(python),
            "-c",
            "from pathlib import Path; from proofmap.paper import load_bundle; from proofmap.schema import validate; b=load_bundle(Path('result')); assert not validate('kernel', b['argument_map']); assert not b['assessment']['closure']['closed']; assert b['assertions']",
        ],
        cwd=root,
        check=True,
    )
    (root / "identity.tex").write_text(
        r"\documentclass{article}\begin{document}\begin{theorem}"
        r"For every $q\in\mathbb{Z}$, \[(q+2)^2=q^2+4q+4\]."
        r"\end{theorem}\end{document}",
        encoding="utf-8",
    )
    subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            "from pathlib import Path; from importlib.resources import files; from proofmap.paper import ci; from proofmap.evidence_records import FormalizationBinding; b,c=ci(Path('identity.tex'),Path('identity-out'),Path('store'),require_formal=True); assert c==3; assert b['formalizations'][0]['status']=='SUPPORTED'; FormalizationBinding.from_dict(b['formalizations'][0]['binding']); assert b['assessment']['outcomes']['formal_compilation']=='UNAVAILABLE'; assert not b['execution_events']; assert all(files('proofmap.resources').joinpath(n+'.schema.json').is_file() for n in ('stage-result','formalization-binding','verifier-profile','environment-manifest','execution-event','review-decision','acceptance-record')); r,c=ci(Path('identity.tex'),Path('identity-resume'),Path('store'),require_formal=True,resume=True); assert c==3 and r['run_manifest']['cache_provenance']['reused_stages']",
        ],
        cwd=root,
        check=True,
    )

    # The copied driver imports only the installed package, with original source fixtures as data.
    driver = root / "paper_alpha_offline.py"
    shutil.copyfile(Path("scripts/paper_alpha_offline.py"), driver)
    shutil.copytree(Path("tests/fixtures/papers"), root / "scenario-fixtures")
    scenario_wheel = root / wheel.name
    shutil.copyfile(wheel, scenario_wheel)
    subprocess.run(
        [
            str(python),
            "-I",
            str(driver),
            "--fixtures",
            str(root / "scenario-fixtures"),
            "--work",
            str(root / "offline-scenarios"),
            "--out",
            str(root / "offline-outcomes.json"),
            "--wheel",
            str(scenario_wheel),
        ],
        cwd=root,
        check=True,
        timeout=600,
    )
    args.offline_outcomes.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "offline-outcomes.json", args.offline_outcomes)

if args.audit_wheel is not None:
    args.audit_wheel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(wheel, args.audit_wheel)
