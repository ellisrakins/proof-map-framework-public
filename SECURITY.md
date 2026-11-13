# Security boundaries and reporting

Do not run untrusted Lean/TeX on the host. Legacy attempt-check and lean-check are
trusted-local compatibility functions, not hostile-code sandboxes. Paper CI never
executes TeX hooks or arbitrary source code. Isolated execution refuses to run
without an explicitly acquired digest-pinned Linux image.

Authentication is not truth: content signatures do not establish execution,
statement fidelity or novelty. The graph cannot nominate its own trust roots.
Review attribution is not an authenticated reviewer identity.

Do not include private manuscripts, model responses, keys, tokens or exploit
payloads containing secrets in public issues. Send only a minimal non-sensitive
description to a repository maintainer and arrange a private channel before
sending sensitive details. A private vulnerability-reporting feature has not
been verified enabled. No response-time guarantee is implied.

Known incomplete assurance gates are listed in docs/advancement/IMPLEMENTATION_REPORT.md.
