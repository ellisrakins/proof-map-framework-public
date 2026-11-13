"""Non-skipping real Lean verification and fresh Agoh reproduction."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile

from proofmap.cli import main
from proofmap.lean_check import resolve_lean_executable

lean = resolve_lean_executable()
if not lean:
    raise SystemExit("Lean required; skip is forbidden")
subprocess.run([lean, "--version"], check=True)
with tempfile.TemporaryDirectory() as temp:
    cases = [
        ("examples/attempts/nat_reflexivity_map.json", "examples/attempts/nat_reflexivity_obligation.json", "examples/attempts/nat_reflexivity_candidate.lean"),
        ("research/agoh_2026/agoh_counterexample_map.json", "research/agoh_2026/agoh_factorization_obligation.json", "research/agoh_2026/agoh_factorization_candidate.lean"),
    ]
    for index, (proof_map, obligation, candidate) in enumerate(cases):
        code = main(["attempt-check", proof_map, obligation, candidate, "--execution-mode", "trusted-host", "--producer", "real-ci",
                     "--out", str(Path(temp) / (str(index) + ".json")), "--lean", lean])
        if code:
            raise SystemExit(code)
    result = subprocess.run([sys.executable, "research/agoh_2026/verify_counterexample.py"], check=True, capture_output=True)
    assert json.loads(result.stdout) == json.loads(Path("research/agoh_2026/certificate.json").read_text())
