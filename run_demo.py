#!/usr/bin/env python3
"""Generate proof-map boundary-analysis demo outputs."""

from proofmap.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["demo", "--out", "."]))
