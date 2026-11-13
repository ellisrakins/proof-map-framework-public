"""Private bounded parser subprocess; never executes manuscript build instructions."""

from __future__ import annotations

import base64
import sys
from typing import Any

from .integrity import canonical_bytes, strict_loads
from .paper_sources import MAX_BYTES, MAX_PARSE_OUTPUT, InputManifest, _parse_in_worker


def main() -> None:
    try:
        import resource
    except ImportError:
        pass  # Windows uses the parent's enforced wall deadline and source/output bounds.
    else:
        posix_resource: Any = resource
        posix_resource.setrlimit(posix_resource.RLIMIT_AS, (768_000_000, 768_000_000))
        posix_resource.setrlimit(posix_resource.RLIMIT_CPU, (60, 60))
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES * 2 + 1)
        if len(raw) > MAX_BYTES * 2:
            raise ValueError("RESOURCE_LIMIT: parser input")
        request = strict_loads(raw)
        manifest = InputManifest(**request["manifest"])
        sources = {
            name: base64.b64decode(value, validate=True) for name, value in request["files"].items()
        }
        response: dict[str, Any] = {"ir": _parse_in_worker(manifest, sources, request["parser"])}
    except Exception as exc:
        response = {"error": str(exc)[:500], "type": type(exc).__name__}
    output = canonical_bytes(response)
    if len(output) > MAX_PARSE_OUTPUT:
        output = canonical_bytes({"error": "RESOURCE_LIMIT: parser output"})
    sys.stdout.buffer.write(output)


if __name__ == "__main__":
    main()
