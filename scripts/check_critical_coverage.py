"""Enforce the requested 90% statement-and-branch threshold for new boundaries."""
import json
import sys
from pathlib import Path

CRITICAL = {"integrity", "kernel", "trust", "runner", "replay"}
data = json.loads(Path(sys.argv[1]).read_text())
failures = []
seen = set()
for name, value in data["files"].items():
    if Path(name).stem in CRITICAL:
        seen.add(Path(name).stem)
        if value["summary"]["percent_covered"] < 90:
            failures.append((name, value["summary"]["percent_covered"]))
if seen != CRITICAL:
    failures.append(("Missing critical modules", sorted(CRITICAL - seen)))
if failures:
    print("Critical coverage gate not met:", failures)
    raise SystemExit(1)
print("Critical coverage gate passed for", ", ".join(sorted(seen)))
