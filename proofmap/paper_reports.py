"""Source locations for local SARIF; UTF-8 byte spans become Unicode columns."""

from __future__ import annotations

import html
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .integrity import (
    artifact_digest,
    atomic_write,
    digest,
    markdown_text,
    relative_path,
    write_json,
)


def physical_location(locator: dict[str, Any], artifacts: dict[str, bytes]) -> dict[str, Any]:
    name = relative_path(locator["artifact"])
    result: dict[str, Any] = {"artifactLocation": {"uri": quote(name, safe="/")}}
    if locator["format"] == "pdf":
        result["properties"] = {
            "pdfPage": locator["page"],
            "locationKind": "reconstructed-page-text",
        }
        return result
    raw = artifacts[name]
    if artifact_digest(raw) != locator["artifact_sha256"]:
        raise ValueError("SARIF_SOURCE_DIGEST_MISMATCH")
    start, end = locator["start"], locator["end"]
    if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(raw):
        raise ValueError("SARIF_SOURCE_RANGE")

    def position(offset: int) -> tuple[int, int]:
        prefix = raw[:offset].decode("utf-8")
        # SARIF unicodeCodePoints columns, 1-based; CRLF counts as one newline.
        normalized = prefix.replace("\r\n", "\n").replace("\r", "\n")
        return normalized.count("\n") + 1, len(normalized.rsplit("\n", 1)[-1]) + 1

    a, b = position(start), position(end)
    result["region"] = {"startLine": a[0], "startColumn": a[1], "endLine": b[0], "endColumn": b[1]}
    return result


def sarif_results(bundle: dict[str, Any], artifacts: dict[str, bytes]) -> list[dict[str, Any]]:
    sources = {e["id"]: e["locator"] for e in bundle["document_ir"]["elements"]}
    results = []
    for finding in bundle["findings"]:
        row: dict[str, Any] = {
            "ruleId": finding["code"],
            "level": "warning",
            "message": {"text": finding.get("detail", finding["code"])},
        }
        locator = sources.get(finding.get("source", ""))
        if locator and (locator["format"] == "pdf" or locator["artifact"] in artifacts):
            row["locations"] = [{"physicalLocation": physical_location(locator, artifacts)}]
        results.append(row)
    return results


def report_model(
    bundle: dict[str, Any],
    artifacts: dict[str, bytes] | None = None,
    reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One offline presentation model; a stored assessment is explicitly historical."""
    ir = bundle.get("interpreted_ir", bundle["document_ir"])
    sources = {row["id"]: row for row in ir["elements"]}
    raw = {row["id"]: row for row in bundle["document_ir"]["elements"]}
    formal = {row["assertion_id"]: row for row in bundle.get("formalizations", [])}
    events = {row["event"]["id"]: row for row in bundle.get("execution_events", [])}
    inferences = bundle["argument_map"].get("inferences", [])
    claims = []
    for assertion in bundle["assertions"]:
        ident = assertion["id"]
        source, encoding = sources[ident], formal.get(ident)
        decisions = list((encoding or {}).get("review_decisions", []))
        for review in reviews or []:
            for decision in review.get("decisions", []):
                if decision.get("assertion") == ident:
                    decisions.append(
                        {**decision, "author": review["author"], "attribution_authenticated": False}
                    )
        current = (encoding or {}).get("current_assessment")
        finding_ids = [
            index
            for index, finding in enumerate(bundle["findings"])
            if finding.get("source") in {ident, *assertion.get("proof_ids", [])}
        ]
        claims.append(
            {
                "id": ident,
                "title": ", ".join(source.get("labels", [])) or ident[:12],
                "role": assertion.get("role", "UNRESOLVED"),
                "state": current["assessment"] if current else assertion["status"],
                "assessment_scope": "CURRENT_AUTHORITY_EVALUATION"
                if current
                else "HISTORICAL_RUN_SNAPSHOT",
                "source": {
                    "id": ident,
                    "text": raw[ident]["text"],
                    "locator": raw[ident]["locator"],
                },
                "context": {
                    "scope": assertion.get("scope"),
                    "lexical_scope": source.get("lexical_scope"),
                    "hypotheses": assertion.get("hypotheses"),
                    "quantifiers": assertion.get("quantifiers"),
                    "records": [
                        r for r in ir.get("mathematical_context", []) if r.get("owner") == ident
                    ],
                    "symbols": [
                        r
                        for r in bundle.get("symbols", [])
                        if r.get("owner") == ident or r.get("scope") == assertion.get("scope")
                    ],
                },
                "proofs": [
                    sources[pid] for pid in assertion.get("proof_ids", []) if pid in sources
                ],
                "alternatives": [r for r in inferences if r.get("conclusion") == ident],
                "formal": encoding,
                "evidence": [events[encoding["execution_event"]]]
                if encoding and encoding.get("execution_event") in events
                else [],
                "reviews": decisions,
                "finding_indices": finding_ids,
                "next_steps": [],
            }
        )
    # The planner is independent of report rendering and never confers authority.
    from .paper_actions import plan_paper_actions

    plan = plan_paper_actions(bundle)
    for claim in claims:
        claim["next_steps"] = [
            action for action in plan["actions"] if action["subject"]["id"] == claim["id"]
        ]
    return {
        "schema_version": "1.0",
        "tool": {"name": "ProofMap paper-ci", "version": version("proof-map-boundary-analysis")},
        "run": bundle["run_manifest"]["run_id"],
        "revision": bundle["input_manifest"]["revision"],
        "analysis_digest": bundle["run_manifest"]["analysis_digest"],
        "warning": "Extracted claims, formal verification, policy acceptance and scholarly acceptance are distinct.",
        "outcomes": bundle["assessment"]["outcomes"],
        "checkers": bundle["assessment"].get("checkers", []),
        "claims": claims,
        "inventory": [
            {
                "id": row["id"],
                "kind": row["kind"],
                "role": row.get("role"),
                "text": row["text"],
                "locator": row["locator"],
                "proof_for": row.get("proof_for"),
                "association": row.get("proof_association"),
            }
            for row in ir["elements"]
            if row["kind"] in {"ASSERTION", "PROOF", "MACRO_DEFINITION"}
        ],
        "sources": list(raw.values()),
        "findings": bundle["findings"],
        "interpretation_overrides": bundle.get("interpretation_overrides", []),
        "planning": plan,
        "sarif_results": sarif_results(bundle, artifacts or {}),
    }


def _anchor(kind: str, ident: str) -> str:
    return kind + "-" + digest("paper-report-anchor.v1", ident)


def _pairs(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Readable labelled values rather than repr(dict); text is escaped by the writer."""
    if isinstance(value, dict):
        return [
            item
            for key, child in value.items()
            for item in _pairs(child, f"{prefix} / {key}" if prefix else str(key))
        ]
    if isinstance(value, list):
        return [
            item
            for index, child in enumerate(value, 1)
            for item in _pairs(child, f"{prefix} / {index}")
        ] or [(prefix, "None recorded")]
    return [(prefix, "Unknown / not assessed" if value is None else str(value))]


def write_reports(
    bundle: dict[str, Any],
    out: Path,
    artifacts: dict[str, bytes] | None = None,
    *,
    reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Produce consistent static JSON, text, HTML and SARIF without active source URLs."""
    model = report_model(bundle, artifacts, reviews)
    out.mkdir(parents=True, exist_ok=True)
    md = [
        "# Paper CI review",
        "",
        model["warning"],
        "",
        "Revision: " + model["revision"],
        "",
        "## Independent outcomes",
        "",
    ]
    body = [
        "<h1>Paper CI review</h1><p>" + html.escape(model["warning"]) + "</p>",
        '<nav aria-label="Report sections"><a href="#claims">Claims</a> · <a href="#inventory">Inventory</a> · <a href="#checkers">Checkers</a> · <a href="#findings">Findings</a> · <a href="#sources">Source browser</a></nav>',
    ]

    def values(value: Any) -> str:
        return (
            "<dl>"
            + "".join(
                "<dt>" + html.escape(k) + "</dt><dd>" + html.escape(v) + "</dd>"
                for k, v in _pairs(value)
            )
            + "</dl>"
        )

    def text_values(value: Any) -> None:
        md.extend("- " + markdown_text(k) + ": " + markdown_text(v) for k, v in _pairs(value))
        md.append("")

    body.append("<h2>Independent outcomes</h2>" + values(model["outcomes"]))
    text_values(model["outcomes"])
    body.append('<h2 id="claims">Claims</h2><ul>')
    for claim in model["claims"]:
        body.append(
            '<li><a href="#'
            + _anchor("claim", claim["id"])
            + '">'
            + html.escape(claim["title"])
            + "</a> — "
            + html.escape(claim["role"])
            + ": "
            + html.escape(claim["state"])
            + "</li>"
        )
    body.append("</ul>")
    md.extend(["## Claims", ""])
    for claim in model["claims"]:
        ident = claim["id"]
        md.extend(
            ["### " + markdown_text(claim["title"]), "", markdown_text(claim["source"]["text"]), ""]
        )
        body.append(
            '<details id="'
            + _anchor("claim", ident)
            + '"><summary>'
            + html.escape(claim["title"])
            + " — "
            + html.escape(claim["role"])
            + "</summary><p>"
            + html.escape(claim["state"] + "; " + claim["assessment_scope"])
            + '</p><nav aria-label="Claim details">'
        )
        for section in ("source", "context", "formal", "evidence", "reviews"):
            body.append('<a href="#' + _anchor(section, ident) + '">' + section.title() + "</a> ")
        body.append("</nav>")
        for section in (
            "source",
            "context",
            "proofs",
            "alternatives",
            "formal",
            "evidence",
            "reviews",
            "next_steps",
        ):
            body.append(
                '<section id="'
                + _anchor(section, ident)
                + '"><h3>'
                + html.escape(section.replace("_", " ").title())
                + "</h3>"
                + values(claim[section])
                + "</section>"
            )
            md.extend(["#### " + section.replace("_", " ").title(), ""])
            text_values(claim[section])
        body.append("</details>")
    for section in ("inventory", "checkers", "findings"):
        body.append(
            '<section id="'
            + section
            + '"><h2>'
            + section.title()
            + "</h2>"
            + values(model[section])
            + "</section>"
        )
        md.extend(["## " + section.title(), ""])
        text_values(model[section])
    body.append('<h2 id="sources">Source browser</h2>')
    for source in model["sources"]:
        body.append(
            '<details id="'
            + _anchor("raw", source["id"])
            + '"><summary>'
            + html.escape(source["kind"] + " — " + source["locator"]["artifact"])
            + "</summary><pre>"
            + html.escape(source["text"])
            + "</pre>"
            + values(source["locator"])
            + "</details>"
        )
    head = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>Paper CI review</title><style>body{font:16px system-ui;max-width:76rem;margin:auto;padding:2rem}pre,dd{white-space:pre-wrap;overflow-wrap:anywhere}details{padding:1rem;border:1px solid #bbb;margin:1rem 0}dt{font-weight:600}dd{margin:0 0 .5rem 1rem}a:focus,summary:focus{outline:3px solid #3565cc}nav{display:flex;gap:1rem;flex-wrap:wrap}section:target{outline:2px solid #3565cc}summary{cursor:pointer}</style></head><body>'
    atomic_write(out / "report.html", head + "".join(body) + "</body></html>")
    atomic_write(out / "report.md", "\n".join(md))
    write_json(out / "report.json", model)
    write_json(
        out / "results.sarif",
        {
            "version": "2.1.0",
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "runs": [
                {
                    "tool": {"driver": model["tool"]},
                    "columnKind": "unicodeCodePoints",
                    "results": model["sarif_results"],
                    "properties": {
                        "run": model["run"],
                        "revision": model["revision"],
                        "analysis_digest": model["analysis_digest"],
                        "outcomes": model["outcomes"],
                    },
                }
            ],
        },
    )
    return model


def query_store(
    store: Any,
    *,
    paper: str = "",
    revision: str | None = None,
    role: str | None = None,
    state: str | None = None,
    finding: str | None = None,
) -> list[dict[str, Any]]:
    """Read immutable indexed runs; accepted views always identify their evaluation scope."""
    result = []
    for row in store.list(paper):
        if revision is not None and row["revision"] != revision:
            continue
        bundle = store.inspect(row["run"])["bundle"]
        model = report_model(bundle)
        for claim in model["claims"]:
            codes = [model["findings"][i]["code"] for i in claim["finding_indices"]]
            if role is not None and claim["role"] != role:
                continue
            if state is not None and claim["state"] != state:
                continue
            if finding is not None and finding not in codes:
                continue
            result.append(
                {
                    **row,
                    "assertion": claim["id"],
                    "title": claim["title"],
                    "role": claim["role"],
                    "state": claim["state"],
                    "assessment_scope": claim["assessment_scope"],
                    "findings": codes,
                }
            )
    return result
