import os
from pathlib import Path

import pytest

from proofmap.runner import Limits, command, run

IMAGE = "python@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9"


def test_runner_requires_pin_and_never_falls_back(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        command("python:latest", tmp_path, ("python",), "test", Limits())
    monkeypatch.setattr("proofmap.runner.shutil.which", lambda _: None)
    assert run(IMAGE, tmp_path, ("python", "--version")).execution_status == "UNAVAILABLE"
    argv = command(IMAGE, tmp_path, ("python", "--version"), "test", Limits())
    for option in (
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pull=never",
    ):
        assert option in argv


@pytest.mark.skipif(
    os.environ.get("PROOFMAP_SANDBOX_TEST") != "1",
    reason="Requires acquired pinned image and Linux Docker",
)
def test_real_linux_isolation_and_limits(tmp_path: Path):
    tmp_path.chmod(0o755)
    source = """
import os, socket
assert os.getuid() != 0
assert 'PROOFMAP_SECRET_SENTINEL' not in os.environ
assert not os.path.exists('/var/run/docker.sock')
for path in ('/src/escape', '/escape'):
    try:
        open(path,'w').write('bad')
    except OSError:
        pass
    else:
        raise AssertionError('writable protected mount')
s=socket.socket(); s.settimeout(1)
assert s.connect_ex(('1.1.1.1',443)) != 0
print('isolated')
"""
    result = run(IMAGE, tmp_path, ("python", "-c", source))
    assert result.execution_status == "PASS", result
    assert "isolated" in result.stdout
    assert (
        run(
            IMAGE, tmp_path, ("python", "-c", "while True: pass"), Limits(seconds=2)
        ).execution_status
        == "TIMEOUT"
    )
    assert (
        run(
            IMAGE, tmp_path, ("python", "-c", "print('x'*1000000)"), Limits(output_bytes=100)
        ).execution_status
        == "ERROR"
    )
