# Bounded source scopes and macro bindings

The source layer records which supported declaration is active at each macro
use, separately from discourse and mathematical context. These exact dependencies
support review, restricted formal translation and revision invalidation. The
parser does not execute TeX or accept mathematical claims.

## Supported source behavior

Lexical declaration frames follow brace groups, math groups and environments. A
supported static declaration inside a local frame can shadow an outer declaration;
leaving that frame restores the outer binding. Local included files are parsed in
the calling lexical context, so their declarations follow the containing frame's
lifetime.

Section, subsection and subsubsection records describe a separate discourse
hierarchy. A heading does not by itself create a TeX declaration frame. Keeping
the two scopes separate avoids treating a section boundary as the end of a macro
definition's lifetime.

The bounded declaration handling covers static forms of `\newcommand`,
`\renewcommand`, `\providecommand` and `\DeclareMathOperator`. Declaration forms
that the parser cannot safely interpret retain explicit unresolved findings.
Dynamic definitions and TeX execution hooks remain unsupported and are never run.
Unsupported dynamic constructs make affected bindings unresolved. A local effect
can be confined to its frame, but global dynamic effects and unresolved or dynamic
replacement invocations also taint ancestor frames. Leaving a group cannot restore
certainty that was lost in an ancestor.
Unavailable or repeated includes and deferred `\aftergroup` effects likewise
leave ancestor bindings unresolved, because their effects may escape a group.

Macro uses are recognized as complete control-sequence tokens in prose and math,
with exact source anchors and the active declaration as a dependency. For
example, `\pmvalueextra` is not a use of a declaration named `\pmvalue`. The declaration
and the use keep their own source locators; a use is not assigned the entire math
expression's span.

For example, in this source the three `\pmvalue` uses bind respectively to the
outer, inner and restored outer declaration:

```tex
\newcommand{\pmvalue}{x}
$\pmvalue + 1$
{\renewcommand{\pmvalue}{y} $\pmvalue + 1$}
$\pmvalue + 1$
```

Those bindings identify source declarations. They do not prove that either
expression has the author's intended mathematical meaning.

## Document IR records

`lexical_scopes` records `ROOT`, `GROUP` and `ENVIRONMENT` frames; math creates a
`GROUP` frame. Each TeX element has a `lexical_scope` reference separately from its
discourse `scope`.

A `MACRO_DEFINITION` element has a `declaration` record containing the command,
symbol, parameter count, optional default, replacement text and replacement
tokens. Its binding status records whether the declaration was `DEFINED`,
`REDEFINED`, `PRESERVED`, `INVALID` or `UNSUPPORTED`, with the previous definition
and resolution information where applicable. Replacement tokens are checked at
use time for cycles and dynamic constructs, but the parser does not execute or
expand them. The separate restricted formal translator can expand supported
zero-argument integer-literal declarations while preserving the original anchors.
Parameterized macro calls record the direct declaration binding, then taint the
calling context and its ancestors because argument and optional-default
substitution is not evaluated. These records do
not claim a complete semantic dependency graph.

A `SYMBOL_OCCURRENCE` identifies one exact source token. Its `binding_status` is
`RESOLVED` or `UNRESOLVED`, with a binding reason and the active `definition` when
resolved. Known built-in commands do not receive extra macro-occurrence records
when their context remains resolved.

## Bounded mathematical context and author structure

`mathematical_context` records anchored variable binders, theorem antecedents,
local proof hypotheses, author definitions, research assumptions and imported
claims. These typed records preserve source meaning for review; arbitrary prose
hypotheses and definitions remain unresolved for formal translation. The
[formal profile](PAPER_FORMAL_PROFILE.md) supports one explicit linear equality
antecedent under its fully consumed integer-polynomial grammar.

Local `.bib` and `bibitem` citation targets remain source metadata. Proof
associations record whether an explicit title/reference or adjacency justifies a
unique target, multiple targets remain ambiguous, or a referenced proof is external
or unresolved. Only a uniquely justified target receives `proof_for`. References
in proof headers carry `PROOF_ASSOCIATION` purpose and are not premise edges.

Explicit source wording such as `By \ref{a} and \ref{b}. Alternatively, by
\ref{c}.` creates separate author-asserted inference alternatives: the first needs
both premises, and the second needs the alternative premise. Citation presence,
proximity and graph reachability alone do not establish deductive support.

## Remaining boundaries

Macro bodies are not evaluated. Unsupported dynamic syntax, ambiguous or invalid
declarations and unresolved uses remain visible for review. Structural command
and environment-hook redefinitions taint affected frames. General mathematical
discourse, arbitrary macro substitution, package execution and remote bibliography
retrieval are unsupported. Typed source records and resolved citations do not
establish deductive support or discharge hypotheses.

Formalization keeps its conservative source-scope checks. A resolved declaration
binding alone does not authorize a macro-bearing expression: the restricted
translator also validates its zero-argument integer-literal replacement and
surrounding context. Extracted assertions, generated formal
subjects, authenticated verification evidence and policy acceptance remain
distinct states.

Dependency-aware revision planning invalidates changed and unresolved dependents
and can preserve eligible independent work. Reusing historical execution still
requires matching formal/environment identities and current authority checks.
Current source bindings, fidelity decisions and policy assessments are required;
no historical acceptance verdict is inherited.

## Acceptance and verification

Focused coverage lives in `tests/test_paper_source_scopes.py`,
`tests/test_paper_scope_validation.py` and `tests/test_source_semantics.py`, alongside source, formalization,
pipeline and parser-boundary regressions. It exercises
lexical restoration, included declarations, discourse hierarchy, exact token
anchors and conservative handling of unsupported constructs. Test-result claims
must refer to the actual current-source execution evidence; this guide does not
substitute for that evidence.

The current status of R027, R031, C03 and F02/F03 is recorded in
[the acceptance ledger](../acceptance/paper_ci_alpha.json), including independently
labelled category coverage and required-profile qualification. Candidate
implementation is separate from final source/package readiness; this guide makes
no hosted qualification or scholarly acceptance claim.
