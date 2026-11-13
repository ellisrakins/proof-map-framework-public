"""Network-enabled preparation, separate from strictly offline paper verification.

Download only the official pinned Lean release and validate its release-asset
SHA-256 against reviewed published metadata retained in the release lock. No
metadata API lookup, token, guessed hash, floating toolchain or image tag is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from proofmap.evidence_records import VerifierProfile
from proofmap.execution import CHECKER_DIGEST
from proofmap.integrity import artifact_digest, digest, strict_loads, write_json
from proofmap.lean_worker import tree_digest

VERSION = "4.30.0"
BASE_IMAGE = "python@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9"
API = "https://api.github.com/repos/leanprover/lean4/releases/tags/v" + VERSION
LOCK_PATH = Path(__file__).with_name("lean-release-lock.json")
MAX_ARCHIVE_BYTES = 2_000_000_000
PLATFORMS = {"x86_64": ("linux/amd64", "linux"), "aarch64": ("linux/arm64", "linux_aarch64")}


def read_release_lock(path: Path) -> tuple[dict[str, Any], str]:
    """Read fixed reviewed acquisition inputs, never manuscript-selected metadata."""
    with path.open("rb") as stream:
        raw = stream.read(16_385)
    if len(raw) > 16_384:
        raise ValueError("Lean release lock exceeds size limit")
    value = strict_loads(raw)
    fields = {
        "schema_version",
        "repository",
        "tag",
        "release_id",
        "published_at",
        "metadata_source",
        "provenance",
        "assets",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Invalid Lean release lock fields")
    expected = {
        "schema_version": "1.0",
        "repository": "leanprover/lean4",
        "tag": "v" + VERSION,
        "metadata_source": API,
        "provenance": "REVIEWED_OFFICIAL_RELEASE_METADATA",
    }
    if any(value[name] != item for name, item in expected.items()):
        raise ValueError("Lean release lock identity mismatch")
    if type(value["release_id"]) is not int or value["release_id"] <= 0:
        raise ValueError("Invalid Lean release ID")
    from datetime import datetime

    published = value["published_at"]
    if not isinstance(published, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", published
    ):
        raise ValueError("Invalid Lean release publication time")
    datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ")
    assets = value["assets"]
    if not isinstance(assets, dict) or set(assets) != {row[0] for row in PLATFORMS.values()}:
        raise ValueError("Invalid Lean release platforms")
    ids = set()
    for architecture, suffix in PLATFORMS.values():
        asset = assets[architecture]
        if not isinstance(asset, dict) or set(asset) != {"id", "name", "size", "digest", "url"}:
            raise ValueError("Invalid Lean release asset fields")
        name = "lean-" + VERSION + "-" + suffix + ".tar.zst"
        url = "https://github.com/leanprover/lean4/releases/download/v" + VERSION + "/" + name
        if asset["name"] != name or asset["url"] != url:
            raise ValueError("Unexpected release asset name or download URL")
        if type(asset["id"]) is not int or asset["id"] <= 0 or asset["id"] in ids:
            raise ValueError("Invalid or duplicate Lean release asset ID")
        ids.add(asset["id"])
        if type(asset["size"]) is not int or not 0 < asset["size"] <= MAX_ARCHIVE_BYTES:
            raise ValueError("Invalid Lean release archive size")
        if not isinstance(asset["digest"], str) or not re.fullmatch(
            r"sha256:[a-f0-9]{64}", asset["digest"]
        ):
            raise ValueError(
                "Official release asset has no usable SHA-256 digest; refusing acquisition"
            )
    return value, artifact_digest(raw)


def acquire(destination: Path) -> tuple[Path, dict[str, str]]:
    machine = platform.machine()
    if platform.system() != "Linux" or machine not in PLATFORMS:
        raise ValueError("This preparation path requires Linux amd64/arm64 and tar with zstd")
    architecture, suffix = PLATFORMS[machine]
    name = "lean-" + VERSION + "-" + suffix
    release, lock_digest = read_release_lock(LOCK_PATH)
    asset = release["assets"][architecture]
    expected, url = asset["digest"], asset["url"]
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / (name + ".tar.zst")
    checksum = hashlib.sha256()
    count = 0
    with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as stream:  # nosec B310 exact official URL
        while block := response.read(1024 * 1024):
            count += len(block)
            if count > MAX_ARCHIVE_BYTES:
                raise ValueError("Release archive exceeds acquisition limit")
            if count > asset["size"]:
                raise ValueError("Official release archive size mismatch")
            checksum.update(block)
            stream.write(block)
    if count != asset["size"]:
        raise ValueError("Official release archive size mismatch")
    if "sha256:" + checksum.hexdigest() != expected:
        raise ValueError("Official release archive checksum mismatch")
    listing = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout.splitlines()
    if not listing or any(
        not item.startswith(name + "/") or ".." in item.split("/") for item in listing
    ):
        raise ValueError("Release archive contains unexpected paths")
    subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], check=True, timeout=300
    )
    root = destination / name
    manifest = {
        "release": "v" + VERSION,
        "archive_sha256": checksum.hexdigest(),
        "asset_url": url,
        "asset_id": str(asset["id"]),
        "release_api": API,
        "release_id": str(release["release_id"]),
        "published_at": release["published_at"],
        "archive_size": str(count),
        "release_lock_sha256": lock_digest,
        "metadata_provenance": "PINNED_REVIEWED_SNAPSHOT_NOT_FETCHED_DURING_RUN",
    }
    return root, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", required=True, help="Write the external profile or host acquisition manifest"
    )
    parser.add_argument(
        "--host-dir",
        help="Acquire resolved host compatibility toolchain here; do not build an image",
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="proofmap-lean-prepare-") as folder:
        work = Path(folder)
        root, acquisition = acquire(Path(args.host_dir).resolve() if args.host_dir else work)
        executable = root / "bin" / "lean"
        version = subprocess.run(
            [str(executable), "--version"], capture_output=True, text=True, check=True, timeout=30
        ).stdout.strip()
        if "version 4.30.0," not in version:
            raise ValueError("Resolved Lean release version mismatch")
        if args.host_dir:
            write_json(
                args.out,
                {
                    **acquisition,
                    "executable": str(executable),
                    "version": version,
                    "lean_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                },
            )
            return 0
        if shutil.which("docker") is None:
            raise ValueError("Docker required to prepare mandatory isolated Lean profile")
        # Network is available only in preparation, never runner.run evaluation.
        subprocess.run(["docker", "pull", BASE_IMAGE], check=True, timeout=300)
        (work / "Dockerfile").write_text(
            "FROM " + BASE_IMAGE + "\nCOPY " + root.name + " /opt/lean\n"
            "ENV PATH=/opt/lean/bin:/usr/local/bin:/usr/bin:/bin\nUSER 65534:65534\n",
            encoding="utf-8",
        )
        image_id = work / "image-id.txt"
        subprocess.run(
            [
                "docker",
                "build",
                "--network=none",
                "--pull=false",
                "--iidfile",
                str(image_id),
                str(work),
            ],
            check=True,
            timeout=600,
        )
        image = image_id.read_text(encoding="utf-8").strip()
        resolved = json.loads(
            subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            ).stdout
        )[0]
        if resolved["Id"] != image or resolved["Os"] != "linux":
            raise ValueError("Built image identity mismatch")
        profile = VerifierProfile.create(
            image=image,
            platform="linux/" + resolved["Architecture"],
            lean_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
            library_digest=tree_digest(root / "lib" / "lean"),
            checker_digest=CHECKER_DIGEST,
            acquisition_digest=digest("lean-acquisition.v1", acquisition),
        )
        write_json(args.out, profile.to_dict())
        write_json(str(args.out) + ".acquisition.json", acquisition)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
