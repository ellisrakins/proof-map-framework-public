# Baseline audit — 2026-09-23

This is a historical development summary, not a qualification of this source export.
- Baseline is already committed, including the Agoh case; older status prose was stale.
- Python 3.12.14, Windows; repository-local `.venv`; package 0.6.0.
- Lean: direct installed 4.30.0 executable, not a downloaded or mocked compiler.
- Fresh baseline: 48 passed, no skips, 27.12 seconds; statement coverage
  2916/3466 = 84.13%. Pytest cache access warning, not a test failure.
- Command: `.venv/Scripts/python -m pytest -q --cov=proofmap --cov-report=term
  --cov-report=json:.baseline-coverage.json`, with `PROOFMAP_LEAN` explicitly set.
- Development prerequisites varied by environment; the recorded results belong
  only to that historical development revision.

## Confirmed findings

| ID | Finding | Evidence |
|---|---|---|
| F01 | Reachability used as derivability | metrics.analyze, shortest_distances_from_core |
| F02 | Status-weighted closure and simulated promotion | metrics, optimizer, hypothesis |
| F03 | Nonfinite/bool numeric input and duplicate-key acceptance | model, JSON loaders |
| F04 | Array insertion order affects semantic digest | attempts.canonical_sha256(map.to_dict()) |
| F05 | Reload accepts verified=null, false returncode, empty receipt digest | attempts |
| F06 | Host compiler process is not a sandbox; incomplete dependency capture | lean_check |
| F07 | Inline JSON and innerHTML allow stored script injection | surface_visualize |
| F08 | No tracked GitHub workflows | initial file inventory |
| F09 | No manuscript pipeline/store | initial file inventory |
| F10 | No evidence for paid security entitlement or newest Python compatibility | environment |

Baseline components and legacy schemas were inspected; historical receipts will not
be rewritten. Scientific validity, source fidelity, authentication and novelty are
separate gates.
