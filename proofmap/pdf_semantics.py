"""Offline, source-grounded PDF statement candidates, never verified claims.

Offsets address reconstructed PDF page text, not original PDF byte positions.
This intentionally conservative extractor requires numbered statement headings.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from typing import Any

MAX_NODES = 2000
MAX_EDGES = 8000
MAX_SPAN_CHARS = 12000
MAX_TOTAL_SPAN_CHARS = 1_000_000
MAX_REFERENCES = 16000
KINDS = r"theorem|lemma|proposition|corollary|conjecture|definition|assumption|hypothesis"
NUMBER = r"(?:\d{1,6}(?:\.\d{1,6}){0,6}[a-z]?|[A-Z](?:\.\d{1,6}){1,6})"
HEADING = re.compile(
    rf"^\s*(?P<kind>{KINDS})\s+(?P<number>{NUMBER})(?=\s*\(|\.(?:\s|$)|:(?:\s|$)|\s*$)",
    re.IGNORECASE,
)
REFERENCE = re.compile(rf"\b(?P<kind>{KINDS})\s+(?P<number>{NUMBER})\b", re.IGNORECASE)
PROOF = re.compile(r"^\s*Proof(?:\s+of\b[^\n.:]{0,100})?\s*[.:]", re.IGNORECASE)
SECTION = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\s+[A-Z][^.!?]{2,80}|References|Bibliography|Appendix(?:\s+\w+)?)\s*$"
)
DERIVATION = re.compile(
    r"\b(?:by|using|applying|apply|from|follows from|consequence of|according to)\s*$",
    re.IGNORECASE,
)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def analyze_pdf_semantics(ir: dict[str, Any]) -> dict[str, Any]:
    """Extract review-only statements and explicit reference relationships."""
    pages = [e for e in ir.get("elements", []) if e.get("kind") == "PDF_PAGE_TEXT"]
    lines: list[dict[str, Any]] = []
    for page_index, element in enumerate(pages):
        text = element.get("text", "")
        if not isinstance(text, str):
            continue
        offset = 0
        page_lines = text.splitlines(keepends=True)
        for index, page_line in enumerate(page_lines):
            lines.append(
                {
                    "page_index": page_index,
                    "start": offset,
                    "end": offset + len(page_line),
                    "text": page_line,
                    "margin": index < 2 or index >= len(page_lines) - 2,
                }
            )
            offset += len(page_line)
    # Repeated page-margin lines are likely running titles, not fresh assertions.
    margins: dict[str, set[int]] = defaultdict(set)
    for line in lines:
        if line["margin"]:
            margins[line["text"].strip()].add(line["page_index"])
    repeated = {text for text, occurrences in margins.items() if len(occurrences) >= 3}
    findings: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    references: list[tuple[str, str, dict[str, Any], dict[str, Any], str, bool]] = []
    active: dict[str, Any] | None = None
    proof_mode = False
    ignored = 0
    truncated = 0
    total_span_chars = 0
    omitted_references = 0

    def anchor(page_index: int, start: int, end: int) -> dict[str, Any]:
        element = pages[page_index]
        text = element["text"][start:end]
        locator = dict(element.get("locator", {}))
        return {
            "page": locator.get("page", page_index + 1),
            "page_index": page_index,
            "char_start": start,
            "char_end": end,
            "excerpt": text,
            "excerpt_sha256": _hash(text),
            "offsets": "reconstructed-page-text-unicode-codepoints-half-open",
            "locator": locator,
        }

    def finish() -> None:
        nonlocal active
        if active is None:
            return
        for field in ("source", "proof"):
            block = active[field]
            block["text"] = "".join(span["excerpt"] for span in block["spans"])
        active["statement"] = active["source"]["text"]
        nodes.append(active)
        active = None

    for line in lines:
        if total_span_chars >= MAX_TOTAL_SPAN_CHARS:
            findings.append(
                {
                    "title": "Total excerpt limit reached",
                    "detail": "Extraction is incomplete; review the original document.",
                }
            )
            break
        text = line["text"]
        stripped = text.strip()
        if stripped in repeated or re.fullmatch(r"\d+", stripped):
            ignored += 1
            continue
        match = HEADING.match(text)
        if match and (re.search(r"\.{3,}|…", text) or re.search(r"\s{2,}\d+\s*$", text)):
            ignored += 1
            continue
        if match:
            finish()
            if len(nodes) >= MAX_NODES:
                findings.append(
                    {
                        "title": "Candidate limit reached",
                        "detail": f"Stopped at {MAX_NODES} candidates; extraction is incomplete.",
                    }
                )
                break
            kind, number = match.group("kind").upper(), match.group("number").rstrip(".")
            identity = anchor(line["page_index"], line["start"], line["end"])
            active = {
                "id": "pdf-" + _hash(str(identity))[:24],
                "label": f"{kind.title()} {number}",
                "number": number,
                "kind": kind,
                "layer": "BOUNDARY",
                "domain": "Manuscript",
                "status": "EXTRACTION_CANDIDATE",
                "uncertainty": None,
                "uncertainty_description": "Uncalibrated extraction uncertainty; statement boundaries and references require human review.",
                "review_required": True,
                "extraction_method": "numbered-heading-and-explicit-reference-v1",
                "source": {"spans": []},
                "proof": {"spans": []},
                "truncated": False,
            }
            proof_mode = False
        elif active is not None and SECTION.match(text):
            finish()
        if active is None:
            continue
        if PROOF.match(text):
            proof_mode = True
        field = "proof" if proof_mode else "source"
        used = sum(len(s["excerpt"]) for key in ("source", "proof") for s in active[key]["spans"])
        remaining = min(MAX_SPAN_CHARS - used, MAX_TOTAL_SPAN_CHARS - total_span_chars)
        if remaining <= 0:
            if not active["truncated"]:
                active["truncated"] = True
                truncated += 1
            continue
        end = min(line["end"], line["start"] + remaining)
        span = anchor(line["page_index"], line["start"], end)
        total_span_chars += end - line["start"]
        spans = active[field]["spans"]
        if (
            spans
            and spans[-1]["page_index"] == span["page_index"]
            and spans[-1]["char_end"] == span["char_start"]
        ):
            spans[-1] = anchor(line["page_index"], spans[-1]["char_start"], end)
        else:
            spans.append(span)
        if end < line["end"]:
            active["truncated"] = True
            truncated += 1
        for ref in REFERENCE.finditer(span["excerpt"]):
            if match and ref.start() == match.start("kind"):
                continue
            ref_anchor = anchor(
                line["page_index"], line["start"] + ref.start(), line["start"] + ref.end()
            )
            key = ref.group("kind").upper() + " " + ref.group("number").lower()
            cue = bool(DERIVATION.search(span["excerpt"][max(0, ref.start() - 60) : ref.start()]))
            prefix = span["excerpt"][max(0, ref.start() - 80) : ref.start()]
            if re.search(r"\b(?:not|never|without|cannot)\b[^.;:]{0,60}$", prefix, re.IGNORECASE):
                cue = False
            if len(references) >= MAX_REFERENCES:
                omitted_references += 1
                continue
            context_anchor = anchor(
                line["page_index"],
                max(line["start"], line["start"] + ref.start() - 80),
                min(end, line["start"] + ref.end() + 80),
            )
            references.append(
                (
                    active["id"],
                    key,
                    ref_anchor,
                    context_anchor,
                    context_anchor["excerpt"].strip(),
                    cue,
                )
            )
    finish()
    lookup: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        lookup[node["kind"] + " " + node["number"].lower()].append(node["id"])
    edges: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for citing, key, source, context_anchor, context, cue in references:
        targets = lookup.get(key, [])
        if len(targets) != 1:
            status = "Ambiguous" if targets else "Unresolved"
            counts[status.lower()] += 1
            if len(findings) < MAX_EDGES:
                findings.append(
                    {
                        "title": status + " reference",
                        "detail": f"{key}: no unique extracted target. Context: {context[:300]}",
                        "source": source,
                        "node": citing,
                        "review_required": True,
                    }
                )
            continue
        if targets[0] == citing:
            continue
        if len(edges) >= MAX_EDGES:
            counts["omitted_edges"] += 1
            continue
        edges.append(
            {
                "source": targets[0],
                "target": citing,
                "kind": "CANDIDATE_DEPENDENCY" if cue else "EXPLICIT_MENTION",
                "source_anchor": source,
                "context_anchor": context_anchor,
                "context": context[:500],
                "review_required": True,
                "rationale": "Explicit reference with a derivation cue; not verified logical dependence."
                if cue
                else "Explicit textual mention only; no logical dependence inferred.",
            }
        )
    if truncated or counts["omitted_edges"] or omitted_references:
        findings.append(
            {
                "title": "Extraction bounds applied",
                "detail": f"{truncated} statement spans truncated; {counts['omitted_edges']} edges and {omitted_references} references omitted. Review the original source.",
            }
        )
    if not nodes:
        findings.append(
            {
                "title": "No numbered statement candidates",
                "detail": "No supported numbered headings found. This does not mean the document contains no mathematical claims.",
            }
        )
    findings.insert(
        0,
        {
            "title": "Review-only semantic candidates",
            "detail": "Exact reconstructed-text excerpts, heuristic statement/proof boundaries, and explicit references only. No mathematical correctness, novelty, logical completeness, or proof acceptance assessment.",
        },
    )
    return {
        "nodes": nodes,
        "edges": edges,
        "findings": findings,
        "metrics": {
            "source_pages": len(pages),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "boundary_count": len(nodes),
            "accepted_claims": 0,
            "candidate_count": len(nodes),
            "proof_span_count": sum(bool(n["proof"]["spans"]) for n in nodes),
            "unresolved_references": counts["unresolved"],
            "ambiguous_references": counts["ambiguous"],
        },
        "extraction": {
            "method": "numbered-heading-and-explicit-reference-v1",
            "review_required": True,
            "ignored_margin_or_toc_lines": ignored,
            "limitations": [
                "Reconstructed PDF text may lose mathematical layout.",
                "Unnumbered statements and equations are not extracted.",
                "Text between headings can include commentary; spans require review.",
                "Reference recognition is lexical, not logical verification.",
            ],
            "limits": {
                "nodes": MAX_NODES,
                "edges": MAX_EDGES,
                "candidate_characters": MAX_SPAN_CHARS,
                "total_excerpt_characters": MAX_TOTAL_SPAN_CHARS,
                "references": MAX_REFERENCES,
            },
        },
    }
