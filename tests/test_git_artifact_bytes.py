"""Git checkout must not invalidate exact-byte scientific receipt bindings."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("suffix", ["json", "lean", "tex"])
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_checkout_preserves_receipt_bound_artifact_bytes(tmp_path, suffix, newline):
    git = shutil.which("git")
    assert git, "Git is required to test release checkout integrity"
    source = tmp_path / "source"
    exported = tmp_path / "exported"
    source.mkdir()
    exported.mkdir()
    (source / ".gitattributes").write_bytes(Path(".gitattributes").read_bytes())
    expected = newline.join([b"first line", b"second line", b""])
    artifact = "fixture." + suffix
    (source / artifact).write_bytes(expected)

    def invoke(*args):
        subprocess.run(
            [git, "-c", "core.autocrlf=true", "-c", "core.safecrlf=false", *args],
            cwd=source,
            check=True,
            capture_output=True,
        )

    invoke("init", "--quiet")
    invoke("add", "--all")
    invoke("checkout-index", "--all", "--prefix=" + exported.as_posix() + "/")
    assert (exported / artifact).read_bytes() == expected
