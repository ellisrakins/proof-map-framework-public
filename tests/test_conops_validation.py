import json
from pathlib import Path

from proofmap.conops import EXPECTED_GAP_ID, run_conops_validation


def test_conops_validation_writes_artifacts_and_summary(tmp_path: Path):
    result = run_conops_validation(tmp_path)
    assert result.ok
    assert result.summary_path.exists()
    assert result.metrics["gap_count"] == 1
    assert EXPECTED_GAP_ID in result.defect_ids

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert summary["metrics"]["node_count"] == 5
    assert summary["artifact_paths"]["lean"].endswith("_LeanSketch.lean")
    for path in summary["artifact_paths"].values():
        assert Path(path).exists()
