"""Restricted rational polynomial equality checker; AST only, never eval/exec."""

from __future__ import annotations

import ast
from fractions import Fraction

Polynomial = dict[int, Fraction]


def polynomial(text: str) -> Polynomial:
    if len(text) > 1024:
        raise ValueError("Exact expression size limit")
    tree = ast.parse(text, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 128:
        raise ValueError("Exact AST limit")

    def add(a: Polynomial, b: Polynomial) -> Polynomial:
        out = dict(a)
        for power, coefficient in b.items():
            out[power] = out.get(power, Fraction(0)) + coefficient
        return {p: c for p, c in out.items() if c}

    def multiply(a: Polynomial, b: Polynomial) -> Polynomial:
        out: Polynomial = {}
        for p, c in a.items():
            for q, d in b.items():
                if p + q > 64:
                    raise ValueError("Polynomial degree limit")
                out[p + q] = out.get(p + q, Fraction(0)) + c * d
        if any(
            c.numerator.bit_length() > 4096 or c.denominator.bit_length() > 4096
            for c in out.values()
        ):
            raise ValueError("Rational size limit")
        return {p: c for p, c in out.items() if c}

    def walk(node: ast.AST) -> Polynomial:
        if (
            isinstance(node, ast.Constant)
            and type(node.value) is int
            and abs(node.value) <= 1_000_000
        ):
            return {0: Fraction(node.value)} if node.value else {}
        if isinstance(node, ast.Name) and node.id == "x":
            return {1: Fraction(1)}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return {
                p: (-c if isinstance(node.op, ast.USub) else c)
                for p, c in walk(node.operand).items()
            }
        if isinstance(node, ast.BinOp):
            left = walk(node.left)
            if isinstance(node.op, ast.Pow):
                if (
                    not isinstance(node.right, ast.Constant)
                    or type(node.right.value) is not int
                    or not 0 <= node.right.value <= 8
                ):
                    raise ValueError("Power limit")
                value = {0: Fraction(1)}
                for _ in range(node.right.value):
                    value = multiply(value, left)
                return value
            right = walk(node.right)
            if isinstance(node.op, ast.Add):
                return add(left, right)
            if isinstance(node.op, ast.Sub):
                return add(left, {p: -c for p, c in right.items()})
            if isinstance(node.op, ast.Mult):
                return multiply(left, right)
            if isinstance(node.op, ast.Div) and set(right) == {0}:
                return {p: c / right[0] for p, c in left.items()}
        raise ValueError("Unsupported exact expression syntax")

    return walk(tree.body)


def equality(left: str, right: str) -> bool:
    return polynomial(left) == polynomial(right)
