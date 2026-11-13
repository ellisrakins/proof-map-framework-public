"""Trusted-base entry point: never execute files from the manuscript checkout."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from proofmap.integrity import write_json
from proofmap.paper import ci


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--validator-sha")
    parser.add_argument("--manuscript-sha")
    args = parser.parse_args()
    identities = {"validator_sha": args.validator_sha, "manuscript_sha": args.manuscript_sha}
    for value in identities.values():
        if value is not None and not re.fullmatch(r"[a-f0-9]{40}", value):
            raise ValueError("Expected immutable Git SHA")
    source, output = args.source.resolve(), args.output.resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError("Reports must be outside manuscript tree")
    output.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        write_json(
            output / "summary.json",
            {
                "status": "NOT_APPLICABLE",
                "reason": "No papers directory",
                "proof": False,
                **identities,
            },
        )
        return 0
    if args.source.is_symlink():
        raise ValueError("Manuscript root must not be a symlink")
    inputs = [
        p
        for p in sorted(source.iterdir())
        if p.is_dir() or p.suffix in {".tex", ".pdf", ".zip", ".tar"}
    ]
    codes = []
    for index, path in enumerate(inputs):
        try:
            if path.is_symlink():
                raise ValueError("Manuscript input must not be a symlink")
            _, code = ci(path, output / str(index), output / "store", extractor="none")
        except (OSError, ValueError) as exc:
            write_json(
                output / (str(index) + "-error.json"),
                {
                    "status": "INVALID_INPUT",
                    "error": type(exc).__name__,
                },
            )
            code = 2
        codes.append(code)
    write_json(
        output / "summary.json",
        {
            "status": "PASS" if codes and not any(codes) else "FAIL" if codes else "NOT_APPLICABLE",
            "paper_count": len(inputs),
            "proof": False,
            **identities,
        },
    )
    return max(codes, default=0)


if __name__ == "__main__":
    raise SystemExit(main())
