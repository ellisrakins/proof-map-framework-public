# A counterexample to Agoh's 2026 alternating-sum factor conjecture

Mathematical status: disproof of the conjecture as printed, checked
2026-08-05. Scholarly status: priority unconfirmed. Exact-title, exact-phrase,
DOI, and journal-page searches found no correction or later resolution, but
the author and journal have not yet confirmed that literature check.

## The published problem

Takashi Agoh defines

\[
Q_n(x;f)=\sum_{i=0}^{n}(-1)^i\binom ni\frac{1}{f(x^i)}.
\]

The final conjecture of *An Intrinsic Factor of an Alternating Sum Involving
Certain Rational Functions*, INTEGERS 26 (2026), A9, says that for a nonzero
real-rooted polynomial `f`, the numerator of `Q_n(x; f)` has **at least** the
factor `(x - 1)^n` if and only if `f` is either a monomial or has only simple
roots, all different from `1`.

There is also a domain defect in that wording: if `f(1)=0`, then the `i=0`
summand is `1/f(1)` and `Q_n` is undefined. The counterexample below avoids
this issue because `f(1)=1`.

Primary source: <https://math.colgate.edu/~integers/aa9/aa9.pdf>, equation
(3.1) and the conjecture on page 9. The journal lists the paper as A9 at
<https://math.colgate.edu/~integers/vol26.html>.

## Counterexample

Take

\[
f(t)=(t-2)^2,\qquad n=2.
\]

This `f` is nonzero and real-rooted, but its root `2` has multiplicity two. It
is neither a monomial nor a polynomial having only simple roots. Nevertheless,

\[
\begin{aligned}
Q_2(x;f)
 &=1-\frac{2}{(x-2)^2}+\frac{1}{(x^2-2)^2}\\
 &=\frac{N(x)}{(x-2)^2(x^2-2)^2},
\end{aligned}
\]

where

\[
\begin{aligned}
N(x)
 &=x^6-4x^5-2x^4+16x^3-3x^2-20x+12\\
 &=(x-1)^2(x^4-2x^3-7x^2+4x+12).
\end{aligned}
\]

This is the reduced numerator. The possible denominator roots are `2` and
`±sqrt(2)`. We have `N(2) = -8`; when `x^2 = 2`, the common-numerator formula
reduces to `N(x) = (x - 2)^2`, which is nonzero at `±sqrt(2)`. Thus numerator
and denominator are coprime. Also, the denominator equals `1` at `x=1`, while
the displayed cofactor equals `8` there, so the numerator has exactly—not just
at least—multiplicity two at `1`.

This falsifies the conjecture's “only if” direction.

It is not an artifact of choosing `n=2`. For this same polynomial, put

\[
h(t)=\frac{1}{(2-e^t)^2}
    =\frac14\sum_{m\ge 0}\frac{m+1}{2^m}e^{mt}.
\]

For every `n>=1`,

\[
h^{(n)}(0)=\frac14\sum_{m\ge0}\frac{(m+1)m^n}{2^m}>0.
\]

The finite-difference calculation in the next section then shows that the
numerator has **exactly** multiplicity `n` at `x=1` for every `n`. Thus neither
an "exactly" reading nor an "all n" reading repairs the conjecture.

## Stronger theorem

In fact the proposed root classification is unnecessary.

**Theorem.** Let `f` be any real or complex polynomial with `f(1) != 0`. For
every integer `n >= 0`, the reduced numerator of `Q_n(x; f)` is divisible by
`(x - 1)^n`.

**Proof.** Near `t=0`, define the analytic function

\[
h(t)=\frac{1}{f(e^t)}.
\]

Then

\[
Q_n(e^t;f)=\sum_{i=0}^{n}(-1)^i\binom ni h(it).
\]

For a Taylor term `t^k`, the coefficient is a constant multiple of

\[
\sum_{i=0}^{n}(-1)^i\binom ni i^k.
\]

This sum is zero for every `k<n`: it is the `n`th finite difference of a
polynomial of degree below `n`. Hence `Q_n(e^t;f)=O(t^n)`. Because `e^t-1`
has a simple zero at `t=0`, `Q_n(x;f)` has a zero of order at least `n` at
`x=1`.

A common denominator is

\[
D(x)=\prod_{i=0}^{n} f(x^i),
\]

and `D(1)=f(1)^(n+1) != 0`. Multiplication by `D`, followed by cancellation to
lowest terms, therefore cannot add or remove a factor `x-1`. The reduced
numerator is divisible by `(x-1)^n`. QED.

The proof works more generally whenever `1/f` is analytic near `1`; neither
real-rootedness nor simplicity of roots is relevant.

## A corrected replacement problem

The automatic factor is universal on the natural domain `f(1) != 0`, so the
nontrivial question is to classify **excess multiplicity**. The leading
finite-difference coefficient gives the exact criterion

\[
\operatorname{ord}_{x=1} Q_n(x;f)=n
\quad\Longleftrightarrow\quad
\left.\left(t\frac{d}{dt}\right)^n\frac1{f(t)}\right|_{t=1}\ne0.
\]

When the displayed derivative vanishes, the next nonzero Taylor coefficient
determines the excess. This is a better-posed successor problem than a
classification by root simplicity.

## Reproduction and verification boundary

The included factorization receipt is a publication copy. Its file paths and
compiler command have been anonymized and its content hash recalculated. The
recorded outcome, axiom list, and hashes of the mathematical inputs and wrapper
are preserved. The copy does not attest to a new execution or carry a signature
from the original verifier.

Run the dependency-free exact-arithmetic check with:

```text
python research/agoh_2026/verify_counterexample.py
```

The script reconstructs the numerator and denominator from the definition,
checks the factorization, computes their polynomial gcd, confirms exact
multiplicity two, and checks the finite-difference identity through a stated
finite range. The general finite-difference proof above is deductive; the
finite-range check is only a regression test.

`AgohCounterexample.lean` kernel-checks the integer-polynomial factorization
and the load-bearing evaluations. The verifier receipt explicitly permits
Lean's standard `propext`, `Classical.choice`, and `Quot.sound` axioms used by
the `grind` certificate, while rejecting `sorryAx` and proof placeholders. It
does not formalize the source-text interpretation, the all-`n` analytic
theorem, or the literature/priority claim. Those boundaries remain explicit
in the associated proof map.
