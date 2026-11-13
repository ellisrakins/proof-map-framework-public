from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .integrity import load_json, write_json
from .trust import sign, verify


def run(args: argparse.Namespace) -> int:
    if args.command == "receipt-replay":
        source = load_json(args.receipt)
        if source.get("record_type") == "ExecutionEvent":
            from .replay import replay_bound_execution

            if not all((args.binding, args.obligation, args.candidate, args.profile)):
                raise ValueError(
                    "Execution replay requires --binding --obligation --candidate --profile"
                )
            value = replay_bound_execution(
                source,
                load_json(args.binding),
                load_json(args.obligation),
                Path(args.candidate).read_bytes(),
                load_json(args.profile),
            )
            write_json(args.out, value)
            return 0 if value["event"]["outcome"] == "VERIFIED" else 3
        from .attempts import AttemptReceipt
        from .replay import replay

        receipt = AttemptReceipt.from_json(args.receipt)
        if not args.manifest or not args.image:
            write_json(
                args.out,
                {
                    "outcome": "UNAVAILABLE",
                    "reason": "Explicit portable manifest and acquired digest-pinned Linux Lean image required; historical absolute paths are inert.",
                },
            )
            return 3
        value = replay(
            receipt,
            Path(args.artifact_root),
            load_json(args.manifest),
            args.image,
            executable=args.executable,
        )
        write_json(args.out, value)
        return 0 if value["outcome"] == "VERIFIED" else 3
    if args.command == "receipt-sign":
        if Path(args.out).resolve() in {Path(args.receipt).resolve(), Path(args.key).resolve()}:
            raise ValueError("Output must not overwrite an input/key")
        value = sign(Path(args.receipt).read_bytes(), Path(args.key).read_bytes(), args.key_id)
        write_json(args.out, value)
        return 0
    try:
        value = asdict(verify(load_json(args.receipt), load_json(args.trust_store)))
    except ValueError as exc:
        import json

        print(json.dumps({"authenticated": False, "error": str(exc)}))
        return 4
    import json

    print(json.dumps(value, sort_keys=True))
    return 0


def add_commands(sub: Any) -> None:
    p = sub.add_parser(
        "receipt-replay", help="Isolated replay using explicit portable content bindings"
    )
    p.add_argument("receipt")
    p.add_argument("--artifact-root", required=True)
    p.add_argument("--manifest")
    p.add_argument("--image")
    p.add_argument("--executable", default="/usr/local/bin/lean")
    p.add_argument("--profile", help="Externally selected profile for versioned execution replay")
    p.add_argument("--binding", help="Exact formalization binding for versioned execution replay")
    p.add_argument("--obligation", help="Exact formal obligation for versioned execution replay")
    p.add_argument("--candidate", help="Bound candidate for versioned execution replay")
    p.add_argument("--out", required=True)
    p.set_defaults(func=run)
    p = sub.add_parser("receipt-sign", help="Authenticate receipt content, not execution")
    p.add_argument("receipt")
    p.add_argument("--key", required=True, help="Raw 32-byte Ed25519 private key; never logged")
    p.add_argument("--key-id", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=run)
    p = sub.add_parser(
        "receipt-verify", help="Verify DSSE content against an external scoped trust store"
    )
    p.add_argument("receipt")
    p.add_argument("--trust-store", required=True)
    p.set_defaults(func=run)
