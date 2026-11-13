# Bounded paper formalization profile

`integer-polynomial-v2` translates source syntax at runtime. It has no fixture,
filename, theorem-label or manuscript-hash lookup. The result is a candidate
encoding and a source binding; it is not a source-fidelity decision.

The accepted theorem body is fully consumed. Whitespace may vary and one optional
`\label{...}` may precede the binder. The environment must have a known theorem,
lemma, proposition, corollary or conjecture role.

```tex
\begin{theorem}\label{optional}
For every $x\in\mathbb{Z}$,
\[
(x+1)^2=x^2+2x+1.
\]
\end{theorem}
```

`For all` is also accepted. The variable is exactly one ASCII lowercase letter;
the domain is explicitly `\mathbb{Z}`. Exactly one conclusion equality is required.
Its optional sentence-ending period may appear inside or after the display. No
unparsed prefix, suffix, implicit hypothesis, second conclusion or other domain
is admitted. One optional explicit antecedent is supported:

```tex
\begin{theorem}
For every $x\in\mathbb{Z}$, if $x=2$, then
\[
x^2=4.
\]
\end{theorem}
```

The antecedent must be a nonzero linear equality in the same variable, with
exactly one integer root whose absolute value is at most 1,000,000. Nonlinear,
inequality, nonintegral, underdetermined and prose antecedents are unsupported.
The complete implication is emitted to Lean. The exact conditional checker
evaluates the conclusion at that explicit root; a counterexample is evidence
about this candidate encoding, pending source fidelity.

Expressions support integer literals from 0 to 1,000,000, the bound variable,
parentheses, unary `+` and `-`, binary addition/subtraction, `*`, `\cdot`, `\times`,
and juxtaposition such as `2x`, `x(x+1)` or `(x+1)(x-1)`. Powers accept a literal
exponent 0-8, with optional TeX braces. Exponentiation binds tighter than unary
minus. Fractions, functions, decimal numbers, extra variables, identifiers,
subscripts and implicit hypotheses are unsupported. Active zero-argument macros
with no optional default and a signed integer-literal replacement can be expanded
for this profile. Nonliteral, parameterized, unresolved and dynamic macro uses
remain unsupported.

The entire theorem is limited to 8,000 UTF-8 bytes; each side is limited to 1,024
bytes, 256 tokens, 96 AST nodes and a bounded recursion depth. The exact polynomial
checker additionally limits resulting degree to 64 and coefficient size.
Oversized statements remain indexed and receive an unsupported/resource finding;
no part of a formula is silently removed.

The translator records the variable, integer domain, universal quantifier, both
expression trees and exact UTF-8 source ranges for the binder, equation and each
side. Expanded expressions retain raw equation, use and definition anchors;
AST offsets are labelled `expanded-expression-characters`. Only AST constructors
print Lean syntax. The generated proposition has form
`∀ (x : Int), <left> = <right>` or
`∀ (x : Int), <antecedent> → <left> = <right>` and imports `Std`. The candidate is
`by grind`, with the approved axiom set `propext`, `Classical.choice` and
`Quot.sound`. The actual isolated executor must still check it; generation and
exact coefficient comparison confer no formal-execution authority. A failed Lean
candidate does not establish a source theorem's falsity.

Lean's documented algebraic solver handles polynomial equalities over integers:
[Lean grind algebraic solver](https://lean-lang.org/doc/reference/latest/The--grind--tactic/Algebraic-Solver-_LPAR_Commutative-Rings___-Fields_RPAR_/).
Historical v1 compatibility was exercised with the pinned Lean 4.30.0 compiler:
10 source-derived corpus obligations, nine successful identities and one correctly
rejected false identity. This was a host compiler compatibility check, not isolated
paper evidence. `tests/test_paper_fragment_lean.py` repeats it when `PROOFMAP_LEAN`
explicitly names that compiler. The mandatory isolated job is a separate check;
current v2 qualification must refer to its actual source-bound execution evidence.

## Roles and context

The syntax IR preserves its historical `ASSERTION` kind and adds a role:
theorem/lemma/proposition/corollary/conjecture, definition, assumption, example,
remark or unresolved. Custom `\newtheorem` declarations are retained, but unknown
aliases have `UNRESOLVED` role. Definitions, examples and remarks are excluded
from the theorem-like formal-coverage denominator.

The source layer records lexical declaration frames separately from discourse
scopes, and records variable binders, theorem antecedents, local proof hypotheses,
author definitions, research assumptions and imported claims with source anchors.
These records describe authored context; general discourse reasoning is not
implemented. Arbitrary surrounding prose assumptions, mathematical definitions,
unparsed source, dynamic macros and structural command/environment hooks keep
formalization conservative. A parsed context record alone does not discharge it.

Formal context identities include relevant source dependencies and supported
static macro declarations. Revision planning can preserve eligible independent
work while changes to used declarations or hypotheses invalidate dependents.
Historical execution reuse requires exact formal/environment matching and current
authority checks; changed revisions receive new source bindings and never inherit
old fidelity or acceptance. See [paper CI](PAPER_CI.md) for workflow rules.
Cached supported formalizations are validated by recomputing their bounded exact
arithmetic certificate. This integrity check is distinct from rerunning the
formalization producer or the isolated Lean worker and grants no proof authority.

## Extraction and source validation

Configured model extraction splits inputs deterministically into requests of at
most 256 complete source elements and 64,000 serialized element bytes. Parser
ownership and scope keep a theorem, its mathematical expressions and its attached
proof together. Section boundaries are preferred; explicit reference targets bring
their complete source group as context when it fits, without duplicate IDs within
a request. An oversized element or theorem/proof group is reported and excluded
whole while independent chunks continue. Externally selected budgets default to
64 requests, 4 MB total request bytes, 65,536 reserved output tokens and 120 seconds.
They may be lowered. Missing provider usage remains null. The model cannot supply
tools, arbitrary source ranges or proof evidence. Conflicting classifications are
rejected. Decomposition candidates have generated identities and validated source
anchors; they remain separate from the original source syntax.

Successful chunk records retain exact prompts, raw responses, schema/config/source
identities and parser context. Pure-stage replay revalidates the exact stored
response and dependencies; a mutable provider model name does not identify an
immutable model build. Model classifications, decomposed statements and dependency
alternatives are advisory candidates. Independent candidate-fidelity checks remain
advisory and cannot substitute for authenticated human fidelity decisions.

Parser entry points run in a subprocess with a default 45-second wall deadline
(externally bounded to 60 seconds), bounded inputs and outputs, and POSIX CPU/address
space limits when available. Windows enforces the parent wall deadline and byte
bounds; an OS memory job-object limit is not implemented. Timeout results retain the
source revision and explicitly report partial/unavailable parsing.

PDF extraction remains pypdf 6.19.0 plain text reconstruction with strict parsing,
at most 100 pages, and no OCR or theorem reconstruction. A locator declares a page
and a half-open Unicode-character range in reconstructed page text, with parser
version. PDF byte `start`/`end` fields remain null. Validation independently
reconstructs the exact PDF in the bounded parser worker and compares the range and
excerpt. A validation session caches that reconstruction once per source digest.
Historical page-only locators are read as full reconstructed-page references.

## Regression corpus

`tests/fixtures/papers/golden.json` records original labelled manuscript cases and
their train/held-out/category metadata. Cases include polynomial identities and
false claims, scoped macros, explicit antecedents, citation/proof associations,
ambiguous claims, interpretation overrides and long manuscripts. Labels describe
independently intended source structure; malformed/security fixtures remain
separate. Consult the actual benchmark artifact for counts and measured coverage.

`proofmap paper benchmark` reports labelled roles, source anchors, explicit edges,
theorem-like counts and selected formalizations. Its parser/formalization pass does
not run Lean or a model: verification is `NOT_RUN`, and unmeasured model fidelity
or dependency quality stays unknown. Separate evaluation records measure executed
model, replay, revision and review scenarios against independent labels; they do
not substitute golden expected values for observed outcomes. This bounded original
regression corpus does not measure general mathematical comprehension. Final
required-profile qualification is governed by [the acceptance contract](ALPHA_ACCEPTANCE.md).
