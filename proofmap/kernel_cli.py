"""Small CLI boundary for shared kernel operations."""

from __future__ import annotations

import argparse
import json
from typing import Any

from .integrity import load_json, write_json
from .kernel import POLICIES, closure, migrate, semantic_digest


def run(args: argparse.Namespace) -> int:
    g = migrate(load_json(args.input))
    code = 0
    value: Any
    if args.command == "validate":
        value = {"valid": True, "issues": [], "warnings": g.warnings}
    elif args.command == "migrate":
        value = g.to_dict()
    elif args.command == "canonicalize":
        value = g.to_dict()
        for key in ("claims", "contexts", "inferences", "evidence"):
            value[key].sort(key=lambda row: row["id"])
        for row in value["inferences"]:
            for key in ("premises", "assumptions", "evidence"):
                row[key] = sorted(set(row[key]))
    elif args.command == "digest":
        value = {"domain": "semantic-graph.v1", "sha256": semantic_digest(g)}
    else:

        def selections(values: list[str]) -> list[tuple[str, str]]:
            result = []
            for value in values:
                context, separator, claim = value.partition(":")
                if not separator or not claim:
                    raise ValueError("Selections must be context:claim")
                result.append((context, claim))
            return result

        result = closure(
            g,
            policy=args.policy,
            assumptions=selections(args.assume),
            foundations=selections(args.foundation),
        )
        value = result.to_dict()
        if args.target and args.target not in {c.id for c in g.claims}:
            raise ValueError("Unknown target")
        code = (
            0
            if (
                args.target in result.closed
                if args.target
                else not result.open and not result.conditional
            )
            else 1
        )
    if getattr(args, "out", None):
        write_json(args.out, value)
    else:
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False))
    return code


def add_commands(sub: Any) -> None:
    for name in ("validate", "migrate", "canonicalize", "digest", "closure"):
        p = sub.add_parser(name, help=f"Shared kernel: {name}")
        p.add_argument("input")
        p.add_argument("--out")
        p.add_argument("--format", choices=["json"], default="json")
        if name == "closure":
            p.add_argument("--policy", choices=sorted(POLICIES), default="deductive-strict-v1")
            p.add_argument("--target")
            p.add_argument("--assume", action="append", default=[])
            p.add_argument("--foundation", action="append", default=[])
        p.set_defaults(func=run)
