import Std.Tactic

/-!
Kernel-checkable algebraic certificate for the n = 2 counterexample described
in `research/agoh_2026/README.md`.

This file verifies the polynomial identity and the evaluations that make the
factor load-bearing. Source fidelity, reduced-fraction coprimality, the general
analytic theorem, and novelty are separate obligations.
-/

namespace AgohCounterexample

def commonNumerator (x : Int) : Int :=
  (x - 2) ^ 2 * (x ^ 2 - 2) ^ 2 - 2 * (x ^ 2 - 2) ^ 2 + (x - 2) ^ 2

def cofactor (x : Int) : Int :=
  x ^ 4 - 2 * x ^ 3 - 7 * x ^ 2 + 4 * x + 12

theorem commonNumerator_factorization (x : Int) :
    commonNumerator x = (x - 1) ^ 2 * cofactor x := by
  unfold commonNumerator cofactor
  grind

theorem commonDenominator_at_one :
    (((1 : Int) - 2) ^ 2 * (((1 : Int) ^ 2 - 2) ^ 2)) = 1 := by
  grind

theorem cofactor_at_one : cofactor 1 = 8 := by
  unfold cofactor
  grind

theorem numerator_at_denominator_root_two : commonNumerator 2 = -8 := by
  unfold commonNumerator
  grind

end AgohCounterexample

