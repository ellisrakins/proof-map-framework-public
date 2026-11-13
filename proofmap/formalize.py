"""A fully consumed, bounded source grammar for quantified Int polynomial identities.

This translator emits candidate formal statements, not fidelity decisions or proof
evidence. No model output, manuscript name or theorem label selects a proof.
"""

from __future__ import annotations

import re
from copy import deepcopy
from fractions import Fraction
from typing import Any

from .attempts import FormalObligation
from .exact_check import polynomial
from .integrity import artifact_digest, canonical_bytes, digest, relative_path

THEOREM_ROLES = frozenset({"THEOREM", "LEMMA", "PROPOSITION", "COROLLARY", "CONJECTURE"})
METHOD = "integer-polynomial-v2"
MAX_STATEMENT_BYTES = 8_000
MAX_EXPRESSION_BYTES = 1_024
MAX_NODES = 96
MAX_POWER = 8
MAX_LITERAL = 1_000_000
_TOKEN = re.compile(r"\s+|\\(?:cdot|times)\b|[0-9]+|[a-z]|[()+*^{}-]")
_BODY = re.compile(
    r"\s*(?:\\label\{[^{}\r\n]{1,128}\}\s*)?"
    r"(?:For every|For all)\s+"
    r"(?P<binder>\$\s*(?P<variable>[a-z])\s*\\in\s*\\mathbb\s*\{Z\}\s*\$)"
    r"\s*,\s*(?:(?:if|If)\s+(?P<antecedent>\$(?P<condition>[^$]+)\$)\s*,\s*then\s*)?"
    r"\\\[(?P<equation>[^\[\]]+)\\\]\s*[.]?\s*",
    re.DOTALL,
)


class ExpressionParser:
    """Recursive descent with explicit arity, precedence and resource limits."""

    def __init__(self, text: str, variable: str) -> None:
        if len(text.encode("utf-8")) > MAX_EXPRESSION_BYTES:
            raise ValueError("EXPRESSION_BYTE_LIMIT")
        self.tokens: list[tuple[str, int, int]] = []
        position = 0
        for match in _TOKEN.finditer(text):
            if match.start() != position:
                raise ValueError("UNSUPPORTED_EXPRESSION_TOKEN")
            position = match.end()
            if not match[0].isspace():
                self.tokens.append((match[0], match.start(), match.end()))
        if position != len(text) or not self.tokens or len(self.tokens) > 256:
            raise ValueError("UNSUPPORTED_OR_OVERSIZED_EXPRESSION")
        self.index = 0
        self.nodes = 0
        self.variable = variable

    def peek(self) -> str:
        return self.tokens[self.index][0] if self.index < len(self.tokens) else ""

    def take(self) -> tuple[str, int, int]:
        if self.index >= len(self.tokens):
            raise ValueError("INCOMPLETE_EXPRESSION")
        token = self.tokens[self.index]
        self.index += 1
        return token

    def node(self, op: str, start: int, end: int, **data: Any) -> dict[str, Any]:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ValueError("EXPRESSION_NODE_LIMIT")
        return {"op": op, "start": start, "end": end, **data}

    def parse(self) -> dict[str, Any]:
        result = self.sum(0)
        if self.peek():
            raise ValueError("UNCONSUMED_EXPRESSION")
        return result

    def sum(self, depth: int) -> dict[str, Any]:
        left = self.product(depth + 1)
        while self.peek() in {"+", "-"}:
            op = self.take()[0]
            right = self.product(depth + 1)
            left = self.node(
                "add" if op == "+" else "sub", left["start"], right["end"], left=left, right=right
            )
        return left

    def product(self, depth: int) -> dict[str, Any]:
        left = self.unary(depth + 1)
        while self.peek():
            token = self.peek()
            if token in {"*", r"\cdot", r"\times"}:
                self.take()
            elif token == "(" or token == self.variable:
                pass  # TeX juxtaposition: 2x, x(x+1), (x+1)(x-1).
            else:
                break
            right = self.unary(depth + 1)
            left = self.node("mul", left["start"], right["end"], left=left, right=right)
        return left

    def unary(self, depth: int) -> dict[str, Any]:
        if depth > 32:
            raise ValueError("EXPRESSION_DEPTH_LIMIT")
        if self.peek() in {"+", "-"}:
            token, start, _ = self.take()
            child = self.unary(depth + 1)
            return self.node("neg" if token == "-" else "pos", start, child["end"], child=child)
        child = self.atom(depth + 1)
        if self.peek() == "^":
            self.take()
            braces = self.peek() == "{"
            if braces:
                self.take()
            exponent, _, end = self.take()
            if (
                not exponent.isascii()
                or not exponent.isdigit()
                or len(exponent) > 2
                or int(exponent) > MAX_POWER
            ):
                raise ValueError("EXPONENT_LIMIT_OR_SYNTAX")
            if braces:
                close, _, end = self.take()
                if close != "}":
                    raise ValueError("EXPONENT_BRACE_MISMATCH")
            child = self.node("pow", child["start"], end, child=child, exponent=int(exponent))
        return child

    def atom(self, depth: int) -> dict[str, Any]:
        token, start, end = self.take()
        if token == "(":
            child = self.sum(depth + 1)
            close, _, end = self.take()
            if close != ")":
                raise ValueError("PARENTHESIS_MISMATCH")
            return self.node("group", start, end, child=child)
        if token == self.variable:
            return self.node("var", start, end, name=token)
        if token.isascii() and token.isdigit() and len(token) <= 7 and int(token) <= MAX_LITERAL:
            return self.node("int", start, end, value=int(token))
        raise ValueError("VARIABLE_LITERAL_OR_ATOM_REJECTED")


def encode_expression(node: dict[str, Any], *, exact: bool = False) -> str:
    """Print only constructor-controlled syntax from our parsed AST."""
    op = node["op"]
    if op == "int":
        return str(node["value"])
    if op == "var":
        return "x" if exact else node["name"]
    if op in {"group", "neg", "pos"}:
        sign = {"group": "", "neg": "-", "pos": "+"}[op]
        return "(" + sign + encode_expression(node["child"], exact=exact) + ")"
    if op == "pow":
        return (
            "("
            + encode_expression(node["child"], exact=exact)
            + ("**" if exact else " ^ ")
            + str(node["exponent"])
            + ")"
        )
    operator = {"add": " + ", "sub": " - ", "mul": " * "}[op]
    return (
        "("
        + encode_expression(node["left"], exact=exact)
        + operator
        + encode_expression(node["right"], exact=exact)
        + ")"
    )


def definition_context(ir: dict[str, Any], element: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return explicit dependencies and unresolved discourse for one source claim.

    Only zero-argument integer-literal macros have a supported interpretation.
    An unrelated declaration does not become a hidden premise of every theorem.
    Unknown prose, research assumptions, and dynamic scope remain conservative.
    """
    by_id = {el["id"]: el for el in ir["elements"]}
    scope_parents = {s["id"]: s.get("parent") for s in ir["scopes"]}
    lexical = {scope["id"]: scope for scope in ir.get("lexical_scopes", [])}
    ancestors: set[str] = set()
    lexical_ancestors: set[str] = set()
    if element is not None:
        scope = element["scope"]
        while scope is not None and scope not in ancestors:
            ancestors.add(scope)
            scope = scope_parents.get(scope)
        lexical_scope = element.get("lexical_scope")
        while lexical_scope is not None and lexical_scope not in lexical_ancestors:
            lexical_ancestors.add(lexical_scope)
            lexical_scope = lexical.get(lexical_scope, {}).get("parent")

    def contained(el: dict[str, Any]) -> bool:
        if element is None:
            return True
        a, b = element["locator"], el["locator"]
        return (
            a["artifact"] == b["artifact"]
            and type(a.get("start")) is int
            and type(b.get("start")) is int
            and a["start"] <= b["start"]
            and b["end"] <= a["end"]
        )

    uses = [el for el in ir["elements"] if el["kind"] == "SYMBOL_OCCURRENCE" and contained(el)]
    dependencies = []
    for identifier in sorted({u["definition"] for u in uses if u.get("definition")}):
        declaration = by_id.get(identifier)
        if declaration is not None:
            dependencies.append(
                {
                    "id": declaration["id"],
                    "kind": declaration["kind"],
                    "text": declaration["text"],
                    "scope": declaration["scope"],
                    "symbol": declaration.get("declaration", {}).get("symbol"),
                    "declaration": declaration.get("declaration"),
                }
            )

    def relevant(el: dict[str, Any]) -> bool:
        return (
            element is None
            or contained(el)
            or (
                el["scope"] in ancestors
                and (not lexical_ancestors or el.get("lexical_scope") in lexical_ancestors)
            )
        )

    entries = [
        {"id": el["id"], "kind": el["kind"], "text": el["text"], "scope": el["scope"]}
        for el in ir["elements"]
        if relevant(el)
        and (
            el["kind"]
            in {
                "UNPARSED_SOURCE",
                "UNSUPPORTED_MACRO",
                "UNSUPPORTED_ENVIRONMENT",
            }
            or el.get("role") in {"DEFINITION", "ASSUMPTION"}
            # Arbitrary surrounding discourse may restrict the scope even when it
            # avoids familiar words such as 'assume'. Do not guess its semantics.
            or el["kind"] == "PROSE"
        )
    ]
    entries.extend(
        {"id": use["id"], "kind": use["kind"], "text": use["text"], "scope": use["scope"]}
        for use in uses
        if use.get("binding_status") != "RESOLVED"
    )
    if (
        element is not None
        and lexical.get(element.get("lexical_scope"), {}).get("resolution") == "UNRESOLVED"
    ):
        entries.append(
            {
                "id": element["id"],
                "kind": "UNRESOLVED_LEXICAL_SCOPE",
                "text": "",
                "scope": element["scope"],
            }
        )
    for dep in dependencies:
        declaration = dep["declaration"] or {}
        replacement = declaration.get("replacement")
        if (
            declaration.get("resolution") != "RESOLVED"
            or declaration.get("parameter_count") != 0
            or declaration.get("optional_default") is not None
            or not isinstance(replacement, str)
            or re.fullmatch(r"\s*-?[0-9]{1,7}\s*", replacement) is None
            or abs(int(replacement)) > MAX_LITERAL
        ):
            entries.append({k: dep[k] for k in ("id", "kind", "text", "scope")})
    return {
        "revision": ir["revision"],
        "entries": entries,
        "dependencies": dependencies,
        "resolution": "UNRESOLVED"
        if entries
        else "RESOLVED"
        if dependencies
        else "SELF_CONTAINED_FRAGMENT",
    }


def formalize_assertion(ir: dict[str, Any], element: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(element, str):
        identifier = element
        element = next(el for el in ir["elements"] if el["id"] == identifier)
    if not isinstance(element, dict):
        raise ValueError("INVALID_FORMALIZATION_SOURCE")
    context = definition_context(ir, element)
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "assertion_id": element["id"],
        "revision": ir["revision"],
        "method": METHOD,
        "status": "UNSUPPORTED",
        "reason": "UNSUPPORTED_SOURCE_GRAMMAR",
        "context_digest": digest("paper-statement-context.v1", context),
        "definition_digest": digest("paper-definition-context.v1", context),
        "source_locators": [element["locator"]],
        "fidelity": "NOT_REVIEWED",
    }
    if context["entries"]:
        result["reason"] = "UNRESOLVED_DEFINITION_CONTEXT"
        return result
    if element.get("role", element.get("environment", "").upper()) not in THEOREM_ROLES:
        result["reason"] = "NOT_A_SUPPORTED_CLAIM_ROLE"
        return result
    text = element["text"]
    if len(text.encode("utf-8")) > MAX_STATEMENT_BYTES:
        result["reason"] = "STATEMENT_BYTE_LIMIT"
        return result
    env = element.get("environment", "")
    prefix, suffix = r"\begin{" + env + "}", r"\end{" + env + "}"
    if not text.startswith(prefix) or not text.endswith(suffix):
        return result
    body = text[len(prefix) : -len(suffix)]
    match = _BODY.fullmatch(body)
    if match is None:
        return result
    variable = match["variable"]
    if any(dep["symbol"] in {"in", "mathbb", "begin", "end"} for dep in context["dependencies"]):
        result["reason"] = "UNSUPPORTED_BINDER_MACRO_REDEFINITION"
        return result
    equation = match["equation"]
    trimmed = equation.rstrip()
    if trimmed.endswith("."):
        equation = trimmed[:-1]
    if equation.count("=") != 1:
        return result
    left_text, right_text = equation.split("=")
    replacements = {
        dep["symbol"]: dep["declaration"]["replacement"].strip() for dep in context["dependencies"]
    }

    def expand(expression: str) -> str:
        def replace(match: re.Match[str]) -> str:
            symbol = match[1]
            return "(" + replacements[symbol] + ")" if symbol in replacements else match[0]

        expanded = re.sub(r"\\([A-Za-z]+|[^A-Za-z\s])", replace, expression)
        if len(expanded.encode("utf-8")) > MAX_EXPRESSION_BYTES:
            raise ValueError("EXPANDED_EXPRESSION_BYTE_LIMIT")
        return expanded

    hypotheses: list[dict[str, Any]] = []
    antecedent_value = None
    try:
        left = ExpressionParser(expand(left_text), variable).parse()
        right = ExpressionParser(expand(right_text), variable).parse()
        left_coeffs = polynomial(encode_expression(left, exact=True))
        right_coeffs = polynomial(encode_expression(right, exact=True))
        if match["condition"] is not None:
            condition = match["condition"]
            if condition.count("=") != 1:
                raise ValueError("UNSUPPORTED_ANTECEDENT")
            condition_left, condition_right = condition.split("=")
            hleft = ExpressionParser(expand(condition_left), variable).parse()
            hright = ExpressionParser(expand(condition_right), variable).parse()
            hp_left = polynomial(encode_expression(hleft, exact=True))
            hp_right = polynomial(encode_expression(hright, exact=True))
            delta = {
                k: hp_left.get(k, Fraction(0)) - hp_right.get(k, Fraction(0))
                for k in set(hp_left) | set(hp_right)
            }
            delta = {k: v for k, v in delta.items() if v}
            # A nonzero linear equality fixes exactly one integer. This bounded
            # check neither assumes the antecedent globally nor guesses roots.
            if any(k > 1 for k in delta) or not delta.get(1):
                raise ValueError("UNSUPPORTED_ANTECEDENT")
            root = -delta.get(0, Fraction(0)) / delta[1]
            if root.denominator != 1 or abs(root.numerator) > MAX_LITERAL:
                raise ValueError("UNSUPPORTED_ANTECEDENT")
            antecedent_value = int(root)
            hypotheses.append({"kind": "EQUALITY_ANTECEDENT", "left": hleft, "right": hright})
    except (ValueError, SyntaxError, RecursionError) as exc:
        result["reason"] = str(exc)[:160]
        return result
    conclusion = f"{encode_expression(left)} = {encode_expression(right)}"
    implication = (
        ""
        if not hypotheses
        else f"{encode_expression(hypotheses[0]['left'])} = {encode_expression(hypotheses[0]['right'])} → "
    )
    statement = f"∀ ({variable} : Int), {implication}{conclusion}"
    obligation = FormalObligation(
        id="paper-polynomial:" + element["id"],
        target_node_id=element["id"],
        statement=statement,
        declaration_name="ProofMapPolynomial",
        toolchain="leanprover/lean4:v4.30.0",
        imports=("Std",),
        allowed_axioms=("Classical.choice", "Quot.sound", "propext"),
        metadata={
            "method": METHOD,
            "revision": ir["revision"],
            "context_digest": result["context_digest"],
        },
    )

    def span(start: int, end: int) -> dict[str, Any]:
        # UTF-8 byte coordinates into the exact source artifact, not normalized TeX.
        offset = len(prefix)
        lo, hi = offset + start, offset + end
        return {
            "artifact": element["locator"]["artifact"],
            "start": element["locator"]["start"] + len(text[:lo].encode("utf-8")),
            "end": element["locator"]["start"] + len(text[:hi].encode("utf-8")),
            "excerpt_sha256": artifact_digest(text[lo:hi].encode("utf-8")),
            "offsets": "utf8-bytes-half-open",
        }

    eq_start = match.start("equation")
    result.update(
        status="SUPPORTED",
        reason=None,
        source_ast={
            "quantifier": "forall",
            "variable": variable,
            "domain": "Int",
            "expression_offsets": "expanded-expression-characters",
            "left": left,
            "right": right,
        },
        source_spans={
            "binder": span(match.start("binder"), match.end("binder")),
            "equation": span(eq_start, eq_start + len(equation)),
            "left": span(eq_start, eq_start + len(left_text)),
            "right": span(eq_start + len(left_text) + 1, eq_start + len(equation)),
        },
        obligation=obligation.to_dict(),
        candidate="by\n  grind\n",
        exact_check={
            "mode": "EXACT_COMPUTATION",
            "equal": left_coeffs == right_coeffs,
            "left_coefficients": {str(k): str(v) for k, v in sorted(left_coeffs.items())},
            "right_coefficients": {str(k): str(v) for k, v in sorted(right_coeffs.items())},
            "authority": "LOCAL_ANALYSIS_NOT_FORMAL_EVIDENCE",
        },
    )
    if hypotheses:
        result["source_ast"]["hypotheses"] = hypotheses
        result["source_spans"]["hypotheses"] = [
            span(match.start("antecedent"), match.end("antecedent"))
        ]
        assert antecedent_value is not None
        left_value = sum(v * antecedent_value**k for k, v in left_coeffs.items())
        right_value = sum(v * antecedent_value**k for k, v in right_coeffs.items())
        result["exact_check"].update(
            equal=left_value == right_value,
            condition_value=antecedent_value,
            scope="IMPLICATION_UNDER_EXPLICIT_EQUALITY",
        )
        if left_value != right_value:
            result["exact_check"]["counterexample"] = {variable: antecedent_value}
    if replacements:
        dependencies = {dep["id"] for dep in context["dependencies"]}
        result["expansions"] = [
            {
                "symbol": use["symbol"],
                "definition": use["definition"],
                "replacement": replacements[use["symbol"]],
                "use_locator": use["locator"],
                "definition_locator": next(
                    el["locator"] for el in ir["elements"] if el["id"] == use["definition"]
                ),
            }
            for use in ir["elements"]
            if use["kind"] == "SYMBOL_OCCURRENCE"
            and use.get("definition") in dependencies
            and use["locator"]["artifact"] == element["locator"]["artifact"]
            and element["locator"]["start"] <= use["locator"]["start"] < element["locator"]["end"]
        ]
        result["source_locators"].extend(
            next(el["locator"] for el in ir["elements"] if el["id"] == dep["id"])
            for dep in context["dependencies"]
        )
    return result


def formalize_document(ir: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        formalize_assertion(ir, el)
        for el in ir["elements"]
        if el["kind"] == "ASSERTION"
        and el.get("role", el.get("environment", "").upper()) in THEOREM_ROLES
    ]


def rebind_formalization(
    prior: dict[str, Any],
    old_ir: dict[str, Any],
    new_ir: dict[str, Any],
    new_element: dict[str, Any],
) -> dict[str, Any]:
    """Reanchor a pure checked translation, never transplant execution or review.

    The caller separately validates the stage dependency/environment fingerprint.
    This helper additionally checks exact raw statement and admitted definitions;
    it does not invoke the polynomial checker or accept a proposed equivalence.
    """
    old_element = next(
        (el for el in old_ir["elements"] if el["id"] == prior.get("assertion_id")), None
    )
    if (
        old_element is None
        or old_element["text"] != new_element["text"]
        or prior.get("status") != "SUPPORTED"
        or prior.get("method") != METHOD
    ):
        raise ValueError("FORMALIZATION_REBIND_REQUIRES_EXACT_SOURCE")
    old_context = definition_context(old_ir, old_element)
    new_context = definition_context(new_ir, new_element)

    def semantic(context: dict[str, Any]) -> list[tuple[str, str, Any]]:
        return sorted(
            (dep["symbol"], dep["text"], dep["declaration"]["parameter_count"])
            for dep in context["dependencies"]
        )

    if (
        old_context["entries"]
        or new_context["entries"]
        or semantic(old_context) != semantic(new_context)
    ):
        raise ValueError("FORMALIZATION_REBIND_CONTEXT_CHANGED")
    row = deepcopy(prior)
    for key in (
        "binding",
        "execution",
        "verification",
        "acceptance",
        "reused_from",
        "execution_event",
        "resolution",
        "historical_execution",
    ):
        row.pop(key, None)
    row["assertion_id"] = new_element["id"]
    row["revision"] = new_ir["revision"]
    row["context_digest"] = digest("paper-statement-context.v1", new_context)
    row["definition_digest"] = digest("paper-definition-context.v1", new_context)
    row["fidelity"] = "NOT_REVIEWED"
    by_id = {el["id"]: el for el in new_ir["elements"]}
    row["source_locators"] = [
        new_element["locator"],
        *[by_id[dep["id"]]["locator"] for dep in new_context["dependencies"]],
    ]
    delta = new_element["locator"]["start"] - old_element["locator"]["start"]

    def relocate(value: Any) -> None:
        if isinstance(value, list):
            for child in value:
                relocate(child)
        elif isinstance(value, dict):
            if {"artifact", "start", "end", "excerpt_sha256"} <= set(value):
                value["artifact"] = new_element["locator"]["artifact"]
                value["start"] += delta
                value["end"] += delta
            else:
                for child in value.values():
                    relocate(child)

    relocate(row["source_spans"])
    if "expansions" in row:
        uses = {
            el["locator"]["start"]: el
            for el in new_ir["elements"]
            if el["kind"] == "SYMBOL_OCCURRENCE"
            and el["locator"]["artifact"] == new_element["locator"]["artifact"]
        }
        for expansion in row["expansions"]:
            use = uses.get(expansion["use_locator"]["start"] + delta)
            if (
                use is None
                or use.get("binding_status") != "RESOLVED"
                or use["symbol"] != expansion["symbol"]
            ):
                raise ValueError("FORMALIZATION_REBIND_SOURCE_ANCHOR")
            expansion["definition"] = use["definition"]
            expansion["use_locator"] = use["locator"]
            expansion["definition_locator"] = by_id[use["definition"]]["locator"]
    obligation = row["obligation"]
    obligation["id"] = "paper-polynomial:" + new_element["id"]
    obligation["target_node_id"] = new_element["id"]
    obligation["metadata"]["revision"] = new_ir["revision"]
    obligation["metadata"]["context_digest"] = row["context_digest"]
    row["obligation"] = FormalObligation.from_dict(obligation).to_dict()
    return row


def validate_formalization(row: dict[str, Any]) -> None:
    """Validate a finite translation record; cached results confer no authority."""
    from .evidence_records import ExecutionEvent, FormalizationBinding, obligation_identity
    from .execution import render_wrapper
    from .schema import validate

    if validate("formalization-result", row):
        raise ValueError("INVALID_FORMALIZATION_RESULT_SCHEMA")
    for locator in row["source_locators"]:
        relative_path(locator["artifact"])
        if (
            type(locator["start"]) is not int
            or type(locator["end"]) is not int
            or locator["end"] < locator["start"]
        ):
            raise ValueError("INVALID_FORMALIZATION_LOCATOR")
    if row["status"] != "SUPPORTED":
        return
    ast = row["source_ast"]

    def node(value: dict[str, Any], depth: int = 0) -> int:
        if depth > 32 or value["end"] < value["start"]:
            raise ValueError("INVALID_FORMALIZATION_AST_LIMIT")
        op = value["op"]
        fields = {"op", "start", "end"} | (
            {"value"}
            if op == "int"
            else {"name"}
            if op == "var"
            else {"child", "exponent"}
            if op == "pow"
            else {"child"}
            if op in {"group", "neg", "pos"}
            else {"left", "right"}
        )
        if set(value) != fields or (op == "var" and value["name"] != ast["variable"]):
            raise ValueError("INVALID_FORMALIZATION_AST_FIELDS")
        count = 1 + sum(
            node(value[key], depth + 1) for key in ("child", "left", "right") if key in value
        )
        if count > MAX_NODES:
            raise ValueError("INVALID_FORMALIZATION_AST_LIMIT")
        return count

    for expression in [
        ast["left"],
        ast["right"],
        *[h[key] for h in ast.get("hypotheses", []) for key in ("left", "right")],
    ]:
        node(expression)
    implication = (
        ""
        if not ast.get("hypotheses")
        else (
            encode_expression(ast["hypotheses"][0]["left"])
            + " = "
            + encode_expression(ast["hypotheses"][0]["right"])
            + " → "
        )
    )
    expected = f"∀ ({ast['variable']} : Int), {implication}{encode_expression(ast['left'])} = {encode_expression(ast['right'])}"
    obligation = FormalObligation.from_dict(row["obligation"])
    if obligation.statement != expected or obligation.target_node_id != row["assertion_id"]:
        raise ValueError("FORMALIZATION_STATEMENT_AST_MISMATCH")
    if (
        obligation.metadata.get("revision") != row["revision"]
        or obligation.metadata.get("context_digest") != row["context_digest"]
    ):
        raise ValueError("FORMALIZATION_OBLIGATION_CONTEXT_MISMATCH")
    render_wrapper(obligation, row["candidate"].encode("utf-8"))
    spans = row["source_spans"]
    if bool(ast.get("hypotheses")) != bool(spans.get("hypotheses")):
        raise ValueError("FORMALIZATION_HYPOTHESIS_SPAN_MISMATCH")
    for span in [spans[key] for key in ("binder", "equation", "left", "right")] + spans.get(
        "hypotheses", []
    ):
        owner = row["source_locators"][0]
        if (
            span["artifact"] != owner["artifact"]
            or not owner["start"] <= span["start"] <= span["end"] <= owner["end"]
        ):
            raise ValueError("FORMALIZATION_SOURCE_SPAN_OUTSIDE_SUBJECT")
    if bool(ast.get("hypotheses")) != ("condition_value" in row["exact_check"]):
        raise ValueError("FORMALIZATION_CONDITION_CHECK_MISMATCH")
    # A correctly hashed cache is still untrusted input. Recheck its bounded
    # computational certificate independently of the recorded answer; this
    # validates analysis data and never supplies formal execution authority.
    try:
        left_coeffs = polynomial(encode_expression(ast["left"], exact=True))
        right_coeffs = polynomial(encode_expression(ast["right"], exact=True))
        expected_exact: dict[str, Any] = {
            "mode": "EXACT_COMPUTATION",
            "equal": left_coeffs == right_coeffs,
            "left_coefficients": {str(k): str(v) for k, v in sorted(left_coeffs.items())},
            "right_coefficients": {str(k): str(v) for k, v in sorted(right_coeffs.items())},
            "authority": "LOCAL_ANALYSIS_NOT_FORMAL_EVIDENCE",
        }
        if ast.get("hypotheses"):
            hypothesis = ast["hypotheses"][0]
            hp_left = polynomial(encode_expression(hypothesis["left"], exact=True))
            hp_right = polynomial(encode_expression(hypothesis["right"], exact=True))
            delta = {
                k: hp_left.get(k, Fraction(0)) - hp_right.get(k, Fraction(0))
                for k in set(hp_left) | set(hp_right)
            }
            delta = {k: v for k, v in delta.items() if v}
            if any(k > 1 for k in delta) or not delta.get(1):
                raise ValueError("UNSUPPORTED_ANTECEDENT")
            root = -delta.get(0, Fraction(0)) / delta[1]
            if root.denominator != 1 or abs(root.numerator) > MAX_LITERAL:
                raise ValueError("UNSUPPORTED_ANTECEDENT")
            condition_value = int(root)
            equal = sum(v * condition_value**k for k, v in left_coeffs.items()) == sum(
                v * condition_value**k for k, v in right_coeffs.items()
            )
            expected_exact.update(
                equal=equal,
                condition_value=condition_value,
                scope="IMPLICATION_UNDER_EXPLICIT_EQUALITY",
            )
            if not equal:
                expected_exact["counterexample"] = {ast["variable"]: condition_value}
    except (ValueError, SyntaxError, RecursionError) as exc:
        raise ValueError("FORMALIZATION_EXACT_CHECK_UNSUPPORTED_AST") from exc
    if canonical_bytes(row["exact_check"]) != canonical_bytes(expected_exact):
        raise ValueError("FORMALIZATION_EXACT_CHECK_AST_MISMATCH")
    if "binding" in row:
        binding = FormalizationBinding.from_dict(row["binding"])
        if (
            binding.assertion_id != row["assertion_id"]
            or binding.revision_id != row["revision"]
            or binding.obligation_digest != obligation_identity(obligation)
            or binding.context_digest != row["context_digest"]
            or binding.definition_digest != row["definition_digest"]
            or binding.to_dict()["source_locators"] != row["source_locators"]
            or binding.candidate_digest != artifact_digest(row["candidate"].encode("utf-8"))
        ):
            raise ValueError("FORMALIZATION_BINDING_MISMATCH")
    if "historical_execution" in row:
        history = row["historical_execution"]
        old_binding = FormalizationBinding.from_dict(history["binding"])
        old_obligation = FormalObligation.from_dict(history["obligation"])
        event = ExecutionEvent.from_dict(history["execution"]["event"])
        if (
            history["parent_revision"] != old_binding.revision_id
            or event.binding_digest != old_binding.digest
            or event.obligation_digest != obligation_identity(old_obligation)
            or old_obligation.statement != obligation.statement
            or old_binding.candidate_digest != artifact_digest(row["candidate"].encode())
        ):
            raise ValueError("FORMALIZATION_HISTORICAL_BINDING_MISMATCH")
        if history["execution"]["envelope"] is not None:
            from .trust import authenticated_record

            if authenticated_record(history["execution"]["envelope"]) != event.to_dict():
                raise ValueError("FORMALIZATION_HISTORICAL_ENVELOPE_MISMATCH")
    if "resolution" in row:
        resolution = row["resolution"]
        if resolution["accepted"] != resolution["formal_verified"]:
            raise ValueError("FORMALIZATION_RESOLUTION_DIMENSIONS")
        if resolution["formal_verified"]:
            from .kernel import KernelMap, closure

            if not {"graph", "closure", "artifact"} <= set(resolution):
                raise ValueError("FORMALIZATION_RESOLUTION_FIELDS")
            graph = KernelMap.from_dict(resolution["graph"])
            if canonical_bytes(
                closure(graph, trusted_evidence=resolution["trusted_evidence"]).to_dict()
            ) != canonical_bytes(resolution["closure"]):
                raise ValueError("FORMALIZATION_RESOLUTION_CLOSURE")
        elif resolution["trusted_evidence"] or resolution["execution_digest"] is not None:
            raise ValueError("FORMALIZATION_UNVERIFIED_RESOLUTION")
