"""Exact, dependency-free certificate for the Agoh 2026 counterexample.

Polynomials are tuples of coefficients in ascending degree order.  All
polynomial arithmetic uses Fraction, so the gcd and factor checks do not rely
on floating point or a computer-algebra system.
"""

from __future__ import annotations

from fractions import Fraction
from math import comb
import json


Polynomial = tuple[Fraction, ...]


def poly(*coefficients: int | Fraction) -> Polynomial:
    return trim(tuple(Fraction(value) for value in coefficients))


def trim(values: Polynomial) -> Polynomial:
    values = tuple(values)
    while len(values) > 1 and values[-1] == 0:
        values = values[:-1]
    return values or (Fraction(0),)


def add(left: Polynomial, right: Polynomial) -> Polynomial:
    size = max(len(left), len(right))
    return trim(
        tuple(
            (left[index] if index < len(left) else 0)
            + (right[index] if index < len(right) else 0)
            for index in range(size)
        )
    )


def scale(value: Fraction | int, polynomial: Polynomial) -> Polynomial:
    factor = Fraction(value)
    return trim(tuple(factor * coefficient for coefficient in polynomial))


def multiply(left: Polynomial, right: Polynomial) -> Polynomial:
    result = [Fraction(0)] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            result[i + j] += a * b
    return trim(tuple(result))


def power(base: Polynomial, exponent: int) -> Polynomial:
    result = poly(1)
    for _ in range(exponent):
        result = multiply(result, base)
    return result


def evaluate(polynomial: Polynomial, value: Fraction | int) -> Fraction:
    x = Fraction(value)
    result = Fraction(0)
    for coefficient in reversed(polynomial):
        result = result * x + coefficient
    return result


def derivative(polynomial: Polynomial) -> Polynomial:
    if len(polynomial) == 1:
        return poly(0)
    return trim(tuple(index * coefficient for index, coefficient in enumerate(polynomial))[1:])


def divide(dividend: Polynomial, divisor: Polynomial) -> tuple[Polynomial, Polynomial]:
    if divisor == poly(0):
        raise ZeroDivisionError("zero polynomial")
    remainder = list(dividend)
    quotient = [Fraction(0)] * max(1, len(dividend) - len(divisor) + 1)
    while len(remainder) >= len(divisor) and any(remainder):
        degree = len(remainder) - len(divisor)
        leading = remainder[-1] / divisor[-1]
        quotient[degree] += leading
        for index, coefficient in enumerate(divisor):
            remainder[degree + index] -= leading * coefficient
        remainder = list(trim(tuple(remainder)))
    return trim(tuple(quotient)), trim(tuple(remainder))


def monic(polynomial: Polynomial) -> Polynomial:
    polynomial = trim(polynomial)
    if polynomial == poly(0):
        return polynomial
    return scale(1 / polynomial[-1], polynomial)


def gcd(left: Polynomial, right: Polynomial) -> Polynomial:
    left, right = trim(left), trim(right)
    while right != poly(0):
        _, remainder = divide(left, right)
        left, right = right, remainder
    return monic(left)


def root_multiplicity(polynomial: Polynomial, root: int) -> int:
    factor = poly(-root, 1)
    multiplicity = 0
    current = polynomial
    while True:
        quotient, remainder = divide(current, factor)
        if remainder != poly(0):
            return multiplicity
        multiplicity += 1
        current = quotient


def integer_list(polynomial: Polynomial) -> list[int]:
    assert all(value.denominator == 1 for value in polynomial)
    return [int(value) for value in polynomial]


def main() -> None:
    x_minus_two = poly(-2, 1)
    f_x = power(x_minus_two, 2)
    f_x_squared = poly(4, 0, -4, 0, 1)  # (x^2 - 2)^2

    # Q_2 = 1/f(1) - 2/f(x) + 1/f(x^2), and f(1) = 1.
    denominator = multiply(f_x, f_x_squared)
    numerator = add(add(denominator, scale(-2, f_x_squared)), f_x)

    cofactor = poly(12, 4, -7, -2, 1)
    conjectured_factor = power(poly(-1, 1), 2)
    reconstructed = multiply(conjectured_factor, cofactor)

    assert f_x == poly(4, -4, 1)
    assert evaluate(f_x, 1) == 1
    assert evaluate(f_x, 2) == 0
    assert evaluate(derivative(f_x), 2) == 0
    assert evaluate(derivative(derivative(f_x)), 2) == 2
    assert sum(coefficient != 0 for coefficient in f_x) > 1  # not a monomial

    assert denominator == poly(16, -16, -12, 16, 0, -4, 1)
    assert numerator == poly(12, -20, -3, 16, -2, -4, 1)
    assert numerator == reconstructed
    assert gcd(numerator, denominator) == poly(1)
    assert evaluate(denominator, 1) == 1
    assert evaluate(cofactor, 1) == 8
    assert root_multiplicity(numerator, 1) == 2

    # Finite regression check for the identity used in the all-n proof.
    finite_difference_checked_through = 16
    for n in range(finite_difference_checked_through + 1):
        for k in range(n):
            value = sum((-1) ** i * comb(n, i) * i**k for i in range(n + 1))
            assert value == 0

    certificate = {
        "status": "verified",
        "arithmetic": "exact rational polynomial arithmetic",
        "polynomial_coefficients": "ascending degree order",
        "f": integer_list(f_x),
        "f_has_double_root_at": 2,
        "common_denominator": integer_list(denominator),
        "reduced_numerator": integer_list(numerator),
        "factor_x_minus_one_squared": integer_list(conjectured_factor),
        "cofactor": integer_list(cofactor),
        "polynomial_gcd": integer_list(gcd(numerator, denominator)),
        "denominator_at_one": int(evaluate(denominator, 1)),
        "cofactor_at_one": int(evaluate(cofactor, 1)),
        "numerator_root_multiplicity_at_one": root_multiplicity(numerator, 1),
        "finite_difference_identity_checked_through_n": finite_difference_checked_through,
    }
    print(json.dumps(certificate, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

