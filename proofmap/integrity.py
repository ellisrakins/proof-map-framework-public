"""Strict, offline data boundaries. Hashes are identities, not trust decisions."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from itertools import repeat
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str
    severity: str = "ERROR"
    remediation: str = "Correct the input; do not bypass validation."

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def finite_number(value: Any, name: str, *, minimum: float | None = None) -> None:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"NONFINITE_OR_TYPE {name}: expected finite number, not bool")
    if minimum is not None and value < minimum:
        raise ValueError(f"RANGE {name}: must be >= {minimum}")


def json_value(value: Any) -> None:
    """Reject non-JSON values, non-string keys and nonfinite nested metadata."""
    stack = [(value, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > 128 or count > 1_000_000:
            raise ValueError("RESOURCE_LIMIT: JSON depth/item limit")
        item_kind = type(item)
        if item is None or item_kind is str or item_kind is int or item_kind is bool:
            continue
        if isinstance(item, dict):
            if not all(map(isinstance, item, repeat(str))):
                raise ValueError("TYPE: JSON keys must be strings")
            stack.extend(zip(item.values(), repeat(depth + 1)))
        elif isinstance(item, (list, tuple)):
            stack.extend(zip(item, repeat(depth + 1)))
        elif isinstance(item, float):
            finite_number(item, "JSON number")
        elif item is not None and not isinstance(item, (str, int, bool)):
            raise ValueError("TYPE: unsupported JSON value")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"DUPLICATE_KEY: {key}")
        out[key] = value
    return out


def strict_loads(text: str | bytes) -> Any:
    if len(text) > 32_000_000:
        raise ValueError("RESOURCE_LIMIT: JSON larger than 32 MB")
    try:
        value = json.loads(text, object_pairs_hook=_pairs)
        json_value(value)
        return value
    except RecursionError as exc:
        raise ValueError("RESOURCE_LIMIT: JSON nesting") from exc


def load_json(path_or_text: str | Path) -> Any:
    if isinstance(path_or_text, Path):
        return strict_loads(path_or_text.read_bytes())
    if path_or_text.lstrip().startswith(("{", "[")):
        return strict_loads(path_or_text)
    return strict_loads(Path(path_or_text).read_bytes())


def canonical_bytes(value: Any) -> bytes:
    json_value(value)
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def digest(domain: str, value: Any) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9.-]+", domain):
        raise ValueError("Invalid digest domain")
    return hashlib.sha256(
        b"proofmap\x00" + domain.encode("ascii") + b"\x00" + canonical_bytes(value)
    ).hexdigest()


def artifact_digest(data: bytes) -> str:
    """Conventional raw SHA-256, explicitly distinguished from structured hashes."""
    return hashlib.sha256(data).hexdigest()


def require_digest(value: Any) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("DIGEST: expected lowercase SHA-256")


def atomic_write(path: str | Path, data: str | bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError("UNSAFE_PATH: symlink output")
    fd, name = tempfile.mkstemp(prefix=".proofmap-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data.encode("utf-8") if isinstance(data, str) else data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path: str | Path, value: Any) -> None:
    atomic_write(path, canonical_bytes(value) + b"\n")


def relative_path(name: str) -> str:
    """Portable root-relative path; reject Windows aliases even on POSIX."""
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("UNSAFE_PATH: not a portable relative path")
    parts = name.split("/")
    if any(
        part in ("", ".", "..")
        or part.endswith((".", " "))
        or re.match(r"(?i)^(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)", part)
        or any(ord(c) < 32 for c in part)
        for part in parts
    ):
        raise ValueError("UNSAFE_PATH: path traversal or platform alias")
    if PurePosixPath(name).is_absolute():
        raise ValueError("UNSAFE_PATH: absolute path")
    return name


def rooted_path(root: Path, name: str) -> Path:
    relative_path(name)
    base = root.resolve(strict=True)
    current = base
    for part in name.split("/"):
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise ValueError("UNSAFE_PATH: link/junction")
    if not current.resolve().is_relative_to(base):
        raise ValueError("UNSAFE_PATH: root escape")
    return current


def html_json(value: Any) -> str:
    return (
        canonical_bytes(value)
        .decode("utf-8")
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def csv_cell(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


_MARKDOWN_TRANSLATION = str.maketrans(
    {
        **{char: f"&#{ord(char)};" for char in "|`[]()!*_#"},
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#x27;",
        "\r": " ",
        "\n": " ",
    }
)


def markdown_text(value: Any) -> str:
    # Escape each original character once; subsequent replacements must not
    # escape '#' inside an entity we just generated (which breaks readability).
    return str(value).translate(_MARKDOWN_TRANSLATION)
