# Execution modes and exits

`lean-check` and `attempt-check` retain their legacy trusted local host behavior.
Pass `--execution-mode trusted-host` to name it explicitly; older invocations use
that same default and print the mode. Only use these commands on trusted local
Lean code. Their receipts do not constitute isolated paper evidence.

`paper ci` parses manuscript data without running TeX. It accepts only the admitted
isolated execution profile for verification and never falls back to host Lean.
Required verification without an available profile returns an infrastructure error,
while preserving local JSON, Markdown, HTML and SARIF diagnostics.

The verification command exit convention is:

| Exit | Meaning |
|---|---|
| 0 | Requested operation succeeded; consult the explicit assessment before interpreting a mathematical claim |
| 1 | Verification/policy rejection or required checker failure |
| 2 | Invalid arguments, malformed records or unavailable input files |
| 3 | Required verification infrastructure unavailable, verifier error or timeout |

The host unavailable/error exit changed from 2 to 3; the host timeout exit changed
from 1 to 3. Update scripts that classified all nonzero outcomes as mathematical
rejection. Argument parsing still exits 2. Optional demonstration validation keeps
its documented optional-Lean behavior and is not an evidence-acceptance command.

Workflow policy checks inspect the repository's standard YAML layout, alongside
Actionlint syntax checks. Python acquisition uses reviewed constraints, actions use
immutable commits, and container pulls use digests. These declarations do not certify
the contents of every transitive dependency: dependency audit and actual installed
isolation tests remain mandatory. CodeQL stays manual and capability-gated; local
SARIF requires no hosted entitlement. The release workflow only builds downloadable
unpublished artifacts. It does not publish, tag, or change repository protection.
