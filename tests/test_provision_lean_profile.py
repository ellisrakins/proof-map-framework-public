"""Pinned acquisition contracts; tiny archive/process doubles are not Lean evidence."""

import io
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from proofmap.integrity import artifact_digest, load_json, write_json
from scripts import provision_lean_profile as provision

OFFICIAL_LOCK = Path(__file__).resolve().parents[1] / "scripts" / "lean-release-lock.json"
ARCHIVE = b"bounded acquisition test bytes, not a real Lean archive"


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    lock = deepcopy(load_json(OFFICIAL_LOCK))
    for asset in lock["assets"].values():
        asset["size"] = len(ARCHIVE)
        asset["digest"] = "sha256:" + artifact_digest(ARCHIVE)
    path = tmp_path / "test-release-lock.json"
    write_json(path, lock)
    monkeypatch.setattr(provision, "LOCK_PATH", path)
    monkeypatch.setattr(provision.platform, "system", lambda: "Linux")
    monkeypatch.setattr(provision.platform, "machine", lambda: "x86_64")
    downloads, commands = [], []

    def download(url, **kwargs):
        assert isinstance(url, str) and url.startswith(
            "https://github.com/leanprover/lean4/releases/download/"
        )
        assert kwargs == {"timeout": 120}
        downloads.append(url)
        return io.BytesIO(ARCHIVE)

    def run(command, **kwargs):
        commands.append(command)
        assert command[0] == "tar"
        assert kwargs["check"] is True
        name = Path(command[3]).name.removesuffix(".tar.zst")
        return SimpleNamespace(stdout=name + "/\n" + name + "/bin/lean\n")

    monkeypatch.setattr(provision.urllib.request, "urlopen", download)
    monkeypatch.setattr(provision.subprocess, "run", run)
    return lock, path, downloads, commands


def test_checked_in_lock_preserves_reviewed_official_metadata():
    lock, checksum = provision.read_release_lock(OFFICIAL_LOCK)
    assert checksum == artifact_digest(OFFICIAL_LOCK.read_bytes())
    assert lock["release_id"] == 329471000
    assert lock["published_at"] == "2026-05-26T14:45:52Z"
    assert lock["provenance"] == "REVIEWED_OFFICIAL_RELEASE_METADATA"
    expected = {
        "linux/amd64": (
            430245352,
            529208534,
            "4dad74141c2c119ca1aa626656be83b8e14238afba97271fd7bf1eb3f081b319",
        ),
        "linux/arm64": (
            430245351,
            529256235,
            "c99c6f0edd446956d4758c59d4383e8e6411ff6cc71a01f9caabe5eba454121d",
        ),
    }
    for platform, (identity, size, digest) in expected.items():
        asset = lock["assets"][platform]
        assert (asset["id"], asset["size"], asset["digest"]) == (identity, size, "sha256:" + digest)


@pytest.mark.parametrize(
    ("machine", "architecture"), [("x86_64", "linux/amd64"), ("aarch64", "linux/arm64")]
)
def test_acquire_uses_archive_only_and_binds_pinned_provenance(
    tmp_path, monkeypatch, prepared, machine, architecture
):
    lock, path, downloads, commands = prepared
    monkeypatch.setattr(provision.platform, "machine", lambda: machine)
    root, manifest = provision.acquire(tmp_path / "toolchain")
    asset = lock["assets"][architecture]
    assert downloads == [asset["url"]]  # No metadata API request or authentication.
    assert root.name == asset["name"].removesuffix(".tar.zst")
    assert [command[2] for command in commands] == ["-tf", "-xf"]
    assert manifest["archive_sha256"] == artifact_digest(ARCHIVE)
    assert manifest["archive_size"] == str(len(ARCHIVE))
    assert manifest["asset_id"] == str(asset["id"])
    assert manifest["release_id"] == str(lock["release_id"])
    assert manifest["release_api"] == provision.API
    assert manifest["release_lock_sha256"] == artifact_digest(path.read_bytes())
    assert manifest["metadata_provenance"] == "PINNED_REVIEWED_SNAPSHOT_NOT_FETCHED_DURING_RUN"


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_field",
        "missing_field",
        "schema",
        "repository",
        "tag",
        "api",
        "provenance",
        "release_id",
        "release_bool",
        "date",
        "asset_fields",
        "missing_platform",
        "duplicate_id",
        "id_bool",
        "name",
        "url",
        "digest",
        "digest_uppercase",
        "size_bool",
        "size_negative",
        "size_limit",
    ],
)
def test_invalid_lock_fails_before_download_or_extraction(tmp_path, prepared, mutation):
    lock, path, downloads, commands = prepared
    asset = lock["assets"]["linux/amd64"]
    if mutation == "unknown_field":
        lock["override"] = True
    elif mutation == "missing_field":
        lock.pop("published_at")
    elif mutation == "schema":
        lock["schema_version"] = "2.0"
    elif mutation == "repository":
        lock["repository"] = "untrusted/lean4"
    elif mutation == "tag":
        lock["tag"] = "v4.30.1"
    elif mutation == "api":
        lock["metadata_source"] = "https://example.invalid/metadata"
    elif mutation == "provenance":
        lock["provenance"] = "FRESH_API_LOOKUP"
    elif mutation == "release_id":
        lock["release_id"] = -1
    elif mutation == "release_bool":
        lock["release_id"] = True
    elif mutation == "date":
        lock["published_at"] = "2026-02-30T00:00:00Z"
    elif mutation == "asset_fields":
        asset["extra"] = "field"
    elif mutation == "missing_platform":
        lock["assets"].pop("linux/arm64")
    elif mutation == "duplicate_id":
        asset["id"] = lock["assets"]["linux/arm64"]["id"]
    elif mutation == "id_bool":
        asset["id"] = True
    elif mutation == "name":
        asset["name"] = "../toolchain.tar.zst"
    elif mutation == "url":
        asset["url"] += "?override=1"
    elif mutation == "digest":
        asset["digest"] = ""
    elif mutation == "digest_uppercase":
        asset["digest"] = "sha256:" + "A" * 64
    elif mutation == "size_bool":
        asset["size"] = True
    elif mutation == "size_negative":
        asset["size"] = -1
    else:
        asset["size"] = provision.MAX_ARCHIVE_BYTES + 1
    write_json(path, lock)
    with pytest.raises(ValueError):
        provision.acquire(tmp_path / "toolchain")
    assert downloads == commands == []


@pytest.mark.parametrize(
    "raw",
    [b'{"schema_version":"1.0","schema_version":"1.0"}', b" " * 16_385, b"not JSON"],
    ids=["duplicate-key", "oversized", "non-json"],
)
def test_malformed_or_oversized_lock_is_not_silently_parsed(tmp_path, prepared, raw):
    _, path, downloads, commands = prepared
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        provision.acquire(tmp_path / "toolchain")
    assert downloads == commands == []


@pytest.mark.parametrize("mutation", ["digest", "truncated", "excess", "limit"])
def test_archive_bytes_must_match_pin_before_tar(tmp_path, monkeypatch, prepared, mutation):
    lock, path, _, commands = prepared
    raw = ARCHIVE
    if mutation == "digest":
        raw = b"x" * len(ARCHIVE)
    elif mutation == "truncated":
        raw = raw[:-1]
    elif mutation == "excess":
        raw += b"x"
    else:
        monkeypatch.setattr(provision, "MAX_ARCHIVE_BYTES", len(ARCHIVE))
        raw += b"x"
    monkeypatch.setattr(provision.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(raw))
    with pytest.raises(ValueError, match="checksum|size|limit"):
        provision.acquire(tmp_path / "toolchain")
    assert commands == []


@pytest.mark.parametrize(
    "entry", ["../escape", "/absolute", "other/root", "lean-4.30.0-linux/../../escape", ""]
)
def test_unsafe_or_empty_archive_listing_cannot_reach_extraction(
    tmp_path, monkeypatch, prepared, entry
):
    _, _, _, commands = prepared

    def listing(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(stdout=entry)

    monkeypatch.setattr(provision.subprocess, "run", listing)
    with pytest.raises(ValueError, match="unexpected paths"):
        provision.acquire(tmp_path / "toolchain")
    assert len(commands) == 1 and commands[0][2] == "-tf"


@pytest.mark.parametrize(("system", "machine"), [("Windows", "x86_64"), ("Linux", "armv7l")])
def test_unsupported_host_never_selects_another_archive(
    tmp_path, monkeypatch, prepared, system, machine
):
    _, _, downloads, commands = prepared
    monkeypatch.setattr(provision.platform, "system", lambda: system)
    monkeypatch.setattr(provision.platform, "machine", lambda: machine)
    with pytest.raises(ValueError, match="requires Linux"):
        provision.acquire(tmp_path / "toolchain")
    assert downloads == commands == []


def test_download_failure_does_not_fall_back_or_retry_metadata(tmp_path, monkeypatch, prepared):
    _, _, downloads, commands = prepared

    def fail(url, **kwargs):
        downloads.append(url)
        raise HTTPError(url, 403, "denied", {}, None)

    monkeypatch.setattr(provision.urllib.request, "urlopen", fail)
    with pytest.raises(HTTPError):
        provision.acquire(tmp_path / "toolchain")
    assert len(downloads) == 1 and downloads[0].startswith(
        "https://github.com/leanprover/lean4/releases/download/"
    )
    assert commands == []


def test_wrong_compiler_version_is_still_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "acquire", lambda path: (path, {}))
    monkeypatch.setattr(
        provision.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="Lean (version 4.29.0, synthetic)"),
    )
    monkeypatch.setattr(
        "sys.argv", ["provision", "--host-dir", str(tmp_path), "--out", str(tmp_path / "out.json")]
    )
    with pytest.raises(ValueError, match="Resolved Lean release version mismatch"):
        provision.main()
    assert not (tmp_path / "out.json").exists()
