"""Bounded, source-anchored author structure; no assertion is proof authority."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .integrity import artifact_digest, digest


def bibliography_elements(
    revision: str,
    artifact: str,
    raw: bytes,
    scope: str,
    lexical_scope: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read literal local BibTeX records without executing strings or TeX."""
    text = raw.decode("utf-8")
    elements: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    def finding(code: str, detail: str) -> None:
        findings.append(
            {
                "code": code,
                "source": artifact,
                "detail": detail,
                "classification": "REVIEW_REQUIRED",
                "blocking_eligible": False,
            }
        )

    cursor = 0
    for_match = re.compile(r"@([A-Za-z]+)\s*([({])")
    while match := for_match.search(text, cursor):
        line_start = text.rfind("\n", 0, match.start()) + 1
        if re.search(r"(?<!\\)%", text[line_start : match.start()]):
            cursor = match.end()
            continue
        if len(elements) >= 2000:
            raise ValueError("RESOURCE_LIMIT: bibliography entries")
        begin = match.start()
        opening, closing = match[2], "}" if match[2] == "{" else ")"
        depth, braces, quoted, escaped = 1, 0, False, False
        end = match.end()
        while end < len(text) and depth:
            char = text[end]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"' and depth == 1:
                quoted = not quoted
            elif not quoted:
                if opening == "(" and char == "{":
                    braces += 1
                elif opening == "(" and char == "}" and braces:
                    braces -= 1
                elif char == opening and not braces:
                    depth += 1
                    if depth > 64:
                        raise ValueError("RESOURCE_LIMIT: bibliography nesting")
                elif char == closing and not braces:
                    depth -= 1
            end += 1
        if depth:
            finding("BIBLIOGRAPHY_PARSE_ERROR", "Unclosed entry retained in source artifact")
            break
        cursor = end
        if match[1].lower() in {"comment", "preamble", "string"}:
            if match[1].lower() != "comment":
                finding("UNEXPANDED_BIBLIOGRAPHY_DIRECTIVE", match[1])
            continue
        inner = text[match.end() : end - 1]
        key = inner.split(",", 1)[0].strip()
        if "," not in inner or re.fullmatch(r"[A-Za-z0-9_.:+/-]{1,128}", key) is None:
            finding("BIBLIOGRAPHY_PARSE_ERROR", "Invalid or missing literal bibliography key")
            continue
        excerpt = text[begin:end]
        locator = {
            "artifact": artifact,
            "artifact_sha256": artifact_digest(raw),
            "format": "tex",
            "start": len(text[:begin].encode("utf-8")),
            "end": len(text[:end].encode("utf-8")),
            "page": None,
            "excerpt_sha256": artifact_digest(excerpt.encode("utf-8")),
            "offsets": "utf8-bytes-half-open",
            "text_start": None,
            "text_end": None,
            "parser_version": None,
        }
        kind = "BIBLIOGRAPHIC_REFERENCE"
        elements.append(
            {
                "id": digest(
                    "source-element.v1", {"revision": revision, "locator": locator, "kind": kind}
                ),
                "revision": revision,
                "kind": kind,
                "scope": scope,
                "lexical_scope": lexical_scope,
                "text": excerpt,
                "locator": locator,
                "labels": [],
                "references": [],
                "citations": [],
                "proof_for": None,
                "quality": "SYNTAX_ONLY",
                "math_ast": None,
                "key": key,
            }
        )
    return elements, findings


def _sub_locator(element: dict[str, Any], start: int, end: int) -> dict[str, Any]:
    locator = dict(element["locator"])
    locator["start"] += len(element["text"][:start].encode("utf-8"))
    locator["end"] = element["locator"]["start"] + len(element["text"][:end].encode("utf-8"))
    locator["excerpt_sha256"] = artifact_digest(element["text"][start:end].encode("utf-8"))
    return locator


def enrich_source_semantics(ir: dict[str, Any]) -> None:
    """Record explicit binders, author hypotheses and justified premise groups.

    Natural-language interpretations remain candidates. A proof's adjacent
    citations alone never establish a conjunctive or alternative derivation.
    """
    from .formalize import _BODY

    contexts: list[dict[str, Any]] = []
    inferences: list[dict[str, Any]] = []
    body_scopes = {
        scope.get("element"): scope["id"] for scope in ir["scopes"] if scope.get("element")
    }
    labels: dict[str, list[str]] = {}
    for element in ir["elements"]:
        if element["kind"] == "ASSERTION":
            for label in element["labels"]:
                labels.setdefault(label, []).append(element["id"])

    def record(
        kind: str,
        element: dict[str, Any],
        start: int,
        end: int,
        *,
        variable: str | None = None,
        domain: str | None = None,
        parsed: bool = False,
    ) -> None:
        loc = _sub_locator(element, start, end)
        value = {
            "revision": ir["revision"],
            "kind": kind,
            "owner": element["id"],
            "scope": body_scopes.get(element["id"], element["scope"]),
            "source_locators": [loc],
            "text": element["text"][start:end],
            "status": "SOURCE_PARSED" if parsed else "CANDIDATE",
            "variable": variable,
            "domain": domain,
        }
        contexts.append({"id": digest("source-mathematical-context.v1", value), **value})

    for element in ir["elements"]:
        if element["kind"] == "ASSERTION":
            env = element.get("environment", "")
            prefix, suffix = r"\begin{" + env + "}", r"\end{" + env + "}"
            body = element["text"][len(prefix) : -len(suffix)]
            match = _BODY.fullmatch(body)
            if match:
                record(
                    "VARIABLE_BINDER",
                    element,
                    len(prefix) + match.start("binder"),
                    len(prefix) + match.end("binder"),
                    variable=match["variable"],
                    domain="Int",
                    parsed=True,
                )
                if match["antecedent"]:
                    record(
                        "THEOREM_ANTECEDENT",
                        element,
                        len(prefix) + match.start("antecedent"),
                        len(prefix) + match.end("antecedent"),
                        variable=match["variable"],
                        domain="Int",
                        parsed=True,
                    )
            if element.get("role") in {"DEFINITION", "ASSUMPTION"}:
                record(
                    "AUTHOR_DEFINITION"
                    if element["role"] == "DEFINITION"
                    else "RESEARCH_ASSUMPTION",
                    element,
                    0,
                    len(element["text"]),
                )
        elif element["kind"] == "PROOF":
            for match in re.finditer(r"\b(?:Assume|Suppose|Let)\s+\$[^$]+\$", element["text"]):
                record("LOCAL_PROOF_HYPOTHESIS", element, match.start(), match.end())
            if element.get("proof_for") is None:
                continue
            # Each explicitly introduced 'By ...' group is a separate authored
            # derivation. Multiple references within one group require 'and'.
            groups: list[tuple[re.Match[str], list[str]]] = []
            for match in re.finditer(
                r"(?:\bBy|\bFrom|\bAlternatively,\s+by)\s+((?:\\(?:ref|cref|Cref)\{[^{}]+\})(?:\s+and\s+\\(?:ref|cref|Cref)\{[^{}]+\})*)[.,]",
                element["text"],
            ):
                if groups and not match[0].startswith("Alternatively"):
                    continue
                keys = re.findall(r"\\(?:ref|cref|Cref)\{([^{}]+)\}", match[1])
                if any(len(labels.get(key, [])) != 1 for key in keys):
                    continue
                groups.append((match, [labels[key][0] for key in keys]))
            for match, premises in groups:
                if element["proof_for"] in premises:
                    continue
                value = {
                    "revision": ir["revision"],
                    "conclusion": element["proof_for"],
                    "premises": list(dict.fromkeys(premises)),
                    "alternative_group": element["id"],
                    "source_ids": [element["id"]],
                    "source_locators": [_sub_locator(element, match.start(), match.end())],
                    "status": "AUTHOR_ASSERTED_UNVERIFIED",
                }
                inferences.append({"id": digest("source-inference.v1", value), **value})
        elif element["kind"] == "CITATION":
            record("IMPORTED_CLAIM", element, 0, len(element["text"]))
    ir["mathematical_context"] = contexts
    ir["source_inferences"] = inferences


def validate_source_semantics(ir: dict[str, Any]) -> None:
    """Check emitted semantic records against current source IDs and raw anchors."""
    by_id = {element["id"]: element for element in ir["elements"]}
    seen: set[str] = set()
    for record in ir.get("mathematical_context", []):
        if (
            record["id"] in seen
            or record["revision"] != ir["revision"]
            or record["owner"] not in by_id
        ):
            raise ValueError("INVALID_SOURCE_CONTEXT_BINDING")
        seen.add(record["id"])
        if record["id"] != digest(
            "source-mathematical-context.v1", {k: v for k, v in record.items() if k != "id"}
        ):
            raise ValueError("INVALID_SOURCE_CONTEXT_ID")
        owner = by_id[record["owner"]]
        for locator in record["source_locators"]:
            if (
                locator["artifact"] != owner["locator"]["artifact"]
                or not owner["locator"]["start"]
                <= locator["start"]
                <= locator["end"]
                <= owner["locator"]["end"]
            ):
                raise ValueError("INVALID_SOURCE_CONTEXT_ANCHOR")
            relative = locator["start"] - owner["locator"]["start"]
            raw = owner["text"].encode("utf-8")[
                relative : relative + locator["end"] - locator["start"]
            ]
            if (
                artifact_digest(raw) != locator["excerpt_sha256"]
                or raw.decode("utf-8") != record["text"]
            ):
                raise ValueError("INVALID_SOURCE_CONTEXT_EXCERPT")
    for record in ir.get("source_inferences", []):
        if record["id"] in seen or record["revision"] != ir["revision"]:
            raise ValueError("INVALID_SOURCE_INFERENCE_BINDING")
        seen.add(record["id"])
        if record["id"] != digest(
            "source-inference.v1", {k: v for k, v in record.items() if k != "id"}
        ):
            raise ValueError("INVALID_SOURCE_INFERENCE_ID")
        if any(
            identifier not in by_id or by_id[identifier]["kind"] != "ASSERTION"
            for identifier in [record["conclusion"], *record["premises"]]
        ):
            raise ValueError("INVALID_SOURCE_INFERENCE_ENDPOINT")
        if record["conclusion"] in record["premises"] or any(
            identifier not in by_id for identifier in record["source_ids"]
        ):
            raise ValueError("INVALID_SOURCE_INFERENCE_SOURCE")
    # Reconstruct the bounded extraction from current raw elements. Rehashing a
    # forged role/group is not a substitute for the explicit source structure.
    if "mathematical_context" in ir or "source_inferences" in ir:
        reconstructed = deepcopy(ir)
        enrich_source_semantics(reconstructed)
        if any(
            ir.get(name) != reconstructed[name]
            for name in ("mathematical_context", "source_inferences")
        ):
            raise ValueError("SOURCE_SEMANTICS_DO_NOT_MATCH_SOURCE")
    labels: dict[str, list[str]] = {}
    for element in ir["elements"]:
        if element["kind"] == "ASSERTION":
            for label in element["labels"]:
                labels.setdefault(label, []).append(element["id"])
    for index, proof in enumerate(ir["elements"]):
        association = proof.get("proof_association")
        if proof["kind"] != "PROOF" or association is None:
            continue
        targets = association["candidate_targets"]
        if any(target not in by_id or by_id[target]["kind"] != "ASSERTION" for target in targets):
            raise ValueError("INVALID_PROOF_ASSOCIATION_TARGET")
        if association["method"] == "EXPLICIT":
            header = re.match(r"\\begin\{proof\}(?:\[([^\]]*)\])?", proof["text"])
            title = header[1] if header and header[1] else ""
            keys = [
                key.strip()
                for match in re.finditer(r"\\(?:ref|eqref|cref|Cref)\{([^{}]+)\}", title)
                for key in match[1].split(",")
            ]
            expected = list(dict.fromkeys(target for key in keys for target in labels.get(key, [])))
            if association["reference_keys"] != keys or targets != expected:
                raise ValueError("INVALID_EXPLICIT_PROOF_ASSOCIATION")
        elif association["method"] == "ADJACENT":
            preceding = [
                element
                for element in ir["elements"][:index]
                if element["scope"] == proof["scope"]
                and element["kind"]
                in {"ASSERTION", "PROOF", "PROSE", "SECTION", "UNSUPPORTED_ENVIRONMENT"}
            ]
            if (
                not preceding
                or preceding[-1]["kind"] != "ASSERTION"
                or targets != [preceding[-1]["id"]]
            ):
                raise ValueError("INVALID_ADJACENT_PROOF_ASSOCIATION")
        if association["status"] == "RESOLVED":
            if len(targets) != 1 or proof["proof_for"] != targets[0]:
                raise ValueError("INVALID_RESOLVED_PROOF_ASSOCIATION")
        elif proof["proof_for"] is not None:
            raise ValueError("UNRESOLVED_PROOF_HAS_TARGET")
