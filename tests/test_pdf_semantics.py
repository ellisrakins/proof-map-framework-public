"""Only synthetic source content is used in these regressions."""

from typing import Any

from proofmap import pdf_semantics as semantic


def ir(*texts: str) -> dict[str, Any]:
    return {
        "elements": [
            {
                "kind": "PDF_PAGE_TEXT",
                "text": text,
                "locator": {"page": index + 1, "artifact": "synthetic.pdf"},
            }
            for index, text in enumerate(texts)
        ]
    }


def test_multiline_crosspage_proof_and_exact_spans() -> None:
    document = ir(
        "Theorem 1. Every synthetic object\nhas property P,\n",
        "provided Q holds.\nProof. By Lemma 2, P follows.\nLemma 2. Q implies P.\n",
    )
    result = semantic.analyze_pdf_semantics(document)
    assert len(result["nodes"]) == 2
    node = result["nodes"][0]
    assert "provided Q holds" in node["statement"]
    assert "Proof." not in node["statement"]
    assert node["proof"]["text"].startswith("Proof.")
    assert [span["page"] for span in node["source"]["spans"]] == [1, 2]
    for block in (node["source"], node["proof"]):
        for span in block["spans"]:
            original = document["elements"][span["page"] - 1]["text"]
            assert original[span["char_start"] : span["char_end"]] == span["excerpt"]
            assert semantic._hash(span["excerpt"]) == span["excerpt_sha256"]
    edge = result["edges"][0]
    assert edge["kind"] == "CANDIDATE_DEPENDENCY"
    assert edge["source"] == result["nodes"][1]["id"]
    assert edge["target"] == node["id"]
    assert edge["source_anchor"]["excerpt"] == "Lemma 2"
    assert result == semantic.analyze_pdf_semantics(document)


def test_mentions_are_not_dependencies() -> None:
    result = semantic.analyze_pdf_semantics(ir("Lemma 1. A.\nTheorem 2. Compare Lemma 1.\n"))
    assert result["edges"][0]["kind"] == "EXPLICIT_MENTION"
    assert all(n["status"] == "EXTRACTION_CANDIDATE" for n in result["nodes"])
    assert result["metrics"]["accepted_claims"] == 0


def test_unresolved_and_ambiguous_targets() -> None:
    result = semantic.analyze_pdf_semantics(
        ir("Lemma 1. A.\nLemma 1. B.\nTheorem 2. By Lemma 1 and Theorem 99, C.\n")
    )
    assert not result["edges"]
    assert result["metrics"]["ambiguous_references"] == 1
    assert result["metrics"]["unresolved_references"] == 1


def test_prose_title_and_toc_do_not_create_candidates() -> None:
    result = semantic.analyze_pdf_semantics(
        ir(
            "A theorem about objects\nTheorem 1 is discussed below.\n"
            "We state Lemma 2 in the next section.\nTheorem 3 ........... 12\n"
            "Lemma 4. An interesting result    25\nTheorem 5 (Synthetic). A real statement.\n"
        )
    )
    assert [node["label"] for node in result["nodes"]] == ["Theorem 5"]


def test_running_headers_skipped_and_sections_end_spans() -> None:
    result = semantic.analyze_pdf_semantics(
        ir(
            "Theorem 99. Running title\nTheorem 1. A.\n1 Introduction\nNot statement text.\n",
            "Theorem 99. Running title\nbody\n",
            "Theorem 99. Running title\nbody\n",
        )
    )
    assert [node["label"] for node in result["nodes"]] == ["Theorem 1"]
    assert "Not statement" not in result["nodes"][0]["statement"]


def test_bounds_and_empty_results(monkeypatch: Any) -> None:
    monkeypatch.setattr(semantic, "MAX_SPAN_CHARS", 18)
    result = semantic.analyze_pdf_semantics(ir("Theorem 1. " + "x" * 40))
    assert result["nodes"][0]["truncated"]
    assert len(result["nodes"][0]["statement"]) == 18
    monkeypatch.setattr(semantic, "MAX_NODES", 1)
    result = semantic.analyze_pdf_semantics(ir("Theorem 1. A.\nTheorem 2. B.\n"))
    assert len(result["nodes"]) == 1
    assert semantic.analyze_pdf_semantics(ir("Ordinary prose."))["nodes"] == []


def test_duplicate_page_numbers_never_merge_distinct_page_text() -> None:
    document = ir("Theorem 1. First part.\n", "Continuation.\n")
    document["elements"][1]["locator"]["page"] = 1
    result = semantic.analyze_pdf_semantics(document)
    spans = result["nodes"][0]["source"]["spans"]
    assert len(spans) == 2
    assert [span["page_index"] for span in spans] == [0, 1]
    for span in spans:
        assert (
            document["elements"][span["page_index"]]["text"][span["char_start"] : span["char_end"]]
            == span["excerpt"]
        )


def test_edge_and_reference_bounds_and_context_anchors(monkeypatch: Any) -> None:
    monkeypatch.setattr(semantic, "MAX_EDGES", 1)
    document = ir("Lemma 1. A.\nTheorem 2. By Lemma 1, B. Compare Lemma 1.\n")
    result = semantic.analyze_pdf_semantics(document)
    assert len(result["edges"]) == 1
    anchor = result["edges"][0]["context_anchor"]
    assert (
        document["elements"][anchor["page_index"]]["text"][
            anchor["char_start"] : anchor["char_end"]
        ]
        == anchor["excerpt"]
    )
    assert "By Lemma 1" in anchor["excerpt"]
    assert any("edges" in finding["detail"] for finding in result["findings"])
    monkeypatch.setattr(semantic, "MAX_REFERENCES", 1)
    result = semantic.analyze_pdf_semantics(document)
    assert any("1 references omitted" in finding["detail"] for finding in result["findings"])


def test_total_excerpt_bound(monkeypatch: Any) -> None:
    monkeypatch.setattr(semantic, "MAX_TOTAL_SPAN_CHARS", 20)
    result = semantic.analyze_pdf_semantics(ir("Theorem 1. " + "x" * 30 + "\nTheorem 2. B.\n"))
    assert sum(len(n["statement"]) + len(n["proof"]["text"]) for n in result["nodes"]) <= 20
    assert result["nodes"][0]["truncated"]


def test_negated_derivation_is_only_a_mention() -> None:
    result = semantic.analyze_pdf_semantics(
        ir("Lemma 1. A.\nTheorem 2. This does not follow by Lemma 1.\n")
    )
    assert result["edges"][0]["kind"] == "EXPLICIT_MENTION"
