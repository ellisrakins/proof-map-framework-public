"""Independent fixtures for bounded source meaning, never scholarly acceptance."""

from copy import deepcopy
from pathlib import Path

import pytest

from proofmap.formalize import (
    definition_context,
    formalize_document,
    rebind_formalization,
    validate_formalization,
)
from proofmap.paper_sources import acquire, parse_tex, validate_locator
from proofmap.schema import validate
from proofmap.source_semantics import validate_source_semantics


def document(tmp_path, text, parts=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "main.tex").write_text(text, encoding="utf-8")
    for name, content in (parts or {}).items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    manifest, files = acquire(tmp_path, "main.tex")
    ir = parse_tex(manifest, files)
    assert not validate("document-ir", ir)
    for element in ir["elements"]:
        validate_locator(element["locator"], files, element["text"])
    validate_source_semantics(ir)
    return ir


def theorem(formula, label="t", condition=""):
    return rf"\begin{{theorem}}\label{{{label}}}For every $x\in\mathbb{{Z}}$, {condition}\[{formula}.\]\end{{theorem}}"


def test_explicit_integer_antecedent_is_implication_not_foundation(tmp_path):
    ir = document(
        tmp_path,
        theorem("x^2=4", condition="if $x=2$, then ") + r"\begin{proof}Assume $x=2$.\end{proof}",
    )
    row = formalize_document(ir)[0]
    validate_formalization(row)
    assert row["status"] == "SUPPORTED"
    assert "→" in row["obligation"]["statement"]
    assert row["source_ast"]["hypotheses"][0]["kind"] == "EQUALITY_ANTECEDENT"
    assert row["exact_check"]["equal"] is True
    assert row["exact_check"]["condition_value"] == 2
    assert {r["kind"] for r in ir["mathematical_context"]} == {
        "VARIABLE_BINDER",
        "THEOREM_ANTECEDENT",
        "LOCAL_PROOF_HYPOTHESIS",
    }
    hypotheses = [
        r
        for r in ir["mathematical_context"]
        if "HYPOTHESIS" in r["kind"] or "ANTECEDENT" in r["kind"]
    ]
    assert len({h["scope"] for h in hypotheses}) == 2


def test_false_conditional_has_exact_counterexample_not_failed_search(tmp_path):
    row = formalize_document(document(tmp_path, theorem("x^2=5", condition="if $x=2$, then ")))[0]
    assert row["status"] == "SUPPORTED"
    assert row["exact_check"]["equal"] is False
    assert row["exact_check"]["counterexample"] == {"x": 2}


@pytest.mark.parametrize(
    "condition", ["if $x>0$, then ", "if $x^2=4$, then ", "if $2x=1$, then ", "if $y=2$, then "]
)
def test_unsupported_antecedent_does_not_disappear(tmp_path, condition):
    row = formalize_document(document(tmp_path, theorem("x=x", condition=condition)))[0]
    assert row["status"] == "UNSUPPORTED"
    assert "obligation" not in row


def test_literal_macro_scope_dependencies_are_local_and_expansions_anchored(tmp_path):
    ir = document(
        tmp_path,
        r"\newcommand{\valuea}{2}\newcommand{\valueb}{3}"
        + theorem(r"x+\valuea=\valuea+x", "a")
        + theorem("x=x", "b"),
    )
    a, b = formalize_document(ir)
    assert a["status"] == b["status"] == "SUPPORTED"
    assert len(a["expansions"]) == 2
    elements = [el for el in ir["elements"] if el["kind"] == "ASSERTION"]
    assert [d["symbol"] for d in definition_context(ir, elements[0])["dependencies"]] == ["valuea"]
    assert not definition_context(ir, elements[1])["dependencies"]
    assert all(e["replacement"] == "2" for e in a["expansions"])


def test_unresolved_macro_and_discourse_remain_unsupported(tmp_path):
    ir = document(tmp_path, r"\newcommand{\valuea}{\unknown}" + theorem(r"x+\valuea=\valuea+x"))
    assert formalize_document(ir)[0]["status"] == "UNSUPPORTED"


def test_redefined_builtin_binder_cannot_keep_original_domain_meaning(tmp_path):
    ir = document(tmp_path, r"\renewcommand{\in}{2}" + theorem("x=x"))
    row = formalize_document(ir)[0]
    assert row["status"] == "UNSUPPORTED"
    assert row["reason"] == "UNSUPPORTED_BINDER_MACRO_REDEFINITION"


def test_multifile_bibliography_proof_and_explicit_alternatives():
    manifest, files = acquire(Path("tests/fixtures/papers/alpha_semantics"), "main.tex")
    ir = parse_tex(manifest, files)
    assert not validate("document-ir", ir)
    labels = {el["labels"][0]: el["id"] for el in ir["elements"] if el["labels"]}
    proof = next(el for el in ir["elements"] if el["kind"] == "PROOF")
    assert proof["proof_for"] == labels["combined"]
    assert proof["proof_association"]["method"] == "EXPLICIT"
    header_refs = [ref for ref in ir["references"] if ref.get("purpose") == "PROOF_ASSOCIATION"]
    assert len(header_refs) == 1
    assert header_refs[0]["targets"] == [labels["combined"]]
    assert [row["premises"] for row in ir["source_inferences"]] == [
        [labels["branch-a"], labels["branch-b"]],
        [labels["branch-c"]],
    ]
    citation = next(ref for ref in ir["references"] if ref["kind"] == "CITATION")
    assert len(citation["targets"]) == 1
    entry = next(el for el in ir["elements"] if el["id"] == citation["targets"][0])
    assert entry["locator"]["artifact"] == "refs.bib"
    assert entry["quality"] == "SYNTAX_ONLY"


def test_ambiguous_and_missing_citations_and_explicit_proof_targets(tmp_path):
    ir = document(
        tmp_path,
        theorem("x=x", "a")
        + theorem("x=x", "b")
        + r"\begin{proof}[Proof of \ref{a} and \ref{b}]Unclear.\end{proof}\cite{dup,missing}\bibliography{refs}",
        {"refs.bib": "@book{dup,title={A}}\n@book{dup,title={B}}"},
    )
    proof = next(el for el in ir["elements"] if el["kind"] == "PROOF")
    assert proof["proof_for"] is None
    assert proof["proof_association"]["status"] == "AMBIGUOUS"
    assert {f["code"] for f in ir["findings"]} >= {"AMBIGUOUS_CITATION", "UNRESOLVED_CITATION"}


def test_citation_adjacency_does_not_invent_groups(tmp_path):
    ir = document(
        tmp_path,
        theorem("x=x", "a")
        + theorem("x=x", "b")
        + theorem("x=x", "c")
        + r"\begin{proof}\ref{a}, \ref{b}.\end{proof}",
    )
    assert not ir["source_inferences"]


def test_bibitem_and_external_proof_are_inspectable(tmp_path):
    ir = document(
        tmp_path,
        theorem("x=x")
        + r"\begin{proof}[See \cite{outside}]Proof omitted.\end{proof}\begin{thebibliography}{9}\bibitem{outside}An external work.\end{thebibliography}",
    )
    proof = next(el for el in ir["elements"] if el["kind"] == "PROOF")
    assert proof["proof_for"] is None
    assert proof["proof_association"]["status"] == "EXTERNAL"
    assert proof["quality"] == "OMITTED_OR_SKETCH"
    entry = next(el for el in ir["elements"] if el["kind"] == "BIBLIOGRAPHIC_REFERENCE")
    assert "An external work." in entry["text"]


def test_tampered_semantic_context_is_rejected(tmp_path):
    ir = document(tmp_path, theorem("x=x"))
    damaged = deepcopy(ir)
    damaged["mathematical_context"][0]["domain"] = "Real"
    with pytest.raises(ValueError, match="CONTEXT_ID"):
        validate_source_semantics(damaged)


def test_rebind_reuses_pure_result_but_reanchors_and_refuses_changed_dependency(
    tmp_path, monkeypatch
):
    source = r"\newcommand{\valuea}{2}" + theorem(r"x+\valuea=\valuea+x")
    old = document(tmp_path / "old", source)
    new = document(tmp_path / "new", "% source relocation\n" + source)
    prior = formalize_document(old)[0]
    element = next(el for el in new["elements"] if el["kind"] == "ASSERTION")
    with monkeypatch.context() as rebind_guard:
        rebind_guard.setattr(
            "proofmap.formalize.polynomial", lambda *args: pytest.fail("rebind checker reran")
        )
        rebound = rebind_formalization(prior, old, new, element)
    # Loading an untrusted record independently validates its exact certificate.
    validate_formalization(rebound)
    assert rebound["revision"] != prior["revision"]
    assert rebound["source_spans"]["binder"]["start"] > prior["source_spans"]["binder"]["start"]
    assert rebound["obligation"]["statement"] == prior["obligation"]["statement"]
    changed = document(tmp_path / "changed", source.replace("{2}", "{3}"))
    with pytest.raises(ValueError, match="CONTEXT_CHANGED"):
        rebind_formalization(
            prior, old, changed, next(el for el in changed["elements"] if el["kind"] == "ASSERTION")
        )


@pytest.mark.parametrize(
    "field,value", [("equal", 1), ("equal", "yes"), ("authority", "FORMALLY_VERIFIED")]
)
def test_formalization_rejects_forged_exact_check_fields(tmp_path, field, value):
    row = formalize_document(document(tmp_path, theorem("x=x")))[0]
    row["exact_check"][field] = value
    with pytest.raises(ValueError, match="RESULT_SCHEMA"):
        validate_formalization(row)


def test_formalization_rejects_ast_free_variable_and_subject_substitution(tmp_path):
    row = formalize_document(document(tmp_path, theorem("x=x")))[0]
    row["source_ast"]["left"]["name"] = "y"
    with pytest.raises(ValueError, match="AST_FIELDS"):
        validate_formalization(row)
    row["source_ast"]["left"]["name"] = "x"
    row["obligation"]["target_node_id"] = "different-claim"
    with pytest.raises(ValueError, match="STATEMENT_AST_MISMATCH"):
        validate_formalization(row)


def test_local_unresolved_prose_does_not_become_sibling_hypothesis(tmp_path):
    ir = document(
        tmp_path,
        "{All local quantities are positive." + theorem("x=x", "a") + "}" + theorem("x=x", "b"),
    )
    a, b = formalize_document(ir)
    assert a["status"] == "UNSUPPORTED"
    assert b["status"] == "SUPPORTED"


def test_rebinding_never_transplants_cached_execution_or_resolution(tmp_path):
    old = document(tmp_path / "old", theorem("x=x"))
    new = document(tmp_path / "new", "% moved source\n" + theorem("x=x"))
    prior = formalize_document(old)[0]
    prior.update(
        execution_event="a" * 64,
        resolution={"formal_verified": True},
        historical_execution={"forged": True},
    )
    element = next(el for el in new["elements"] if el["kind"] == "ASSERTION")
    rebound = rebind_formalization(prior, old, new, element)
    assert not {"binding", "execution_event", "resolution", "historical_execution"} & rebound.keys()
    validate_formalization(rebound)


@pytest.mark.parametrize(
    "declaration",
    [r"\newcommand{\theorem}{2}", r"\newcommand{\endtheorem}{2}", r"\renewcommand{\section}{2}"],
)
def test_structural_macro_redefinition_cannot_keep_parser_meaning(tmp_path, declaration):
    ir = document(tmp_path, declaration + theorem("x=x"))
    assert formalize_document(ir)[0]["status"] == "UNSUPPORTED"
    assert "UNSUPPORTED_STRUCTURAL_MACRO_DECLARATION" in {f["code"] for f in ir["findings"]}


def test_library_syntax_error_preserves_unparsed_source(tmp_path):
    ir = document(tmp_path, r"\newcommand{\begin}{2}" + theorem("x=x"))
    assert any(el["kind"] == "UNPARSED_SOURCE" for el in ir["elements"])
    assert "TEX_PARSE_ERROR" in {f["code"] for f in ir["findings"]}


@pytest.mark.parametrize(
    "formula,condition,mutation",
    [
        ("x=x", "", "equal"),
        ("x=x", "", "coefficients"),
        ("x^2=4", "if $x=2$, then ", "equal"),
        ("x^2=4", "if $x=2$, then ", "condition"),
        ("x^2=5", "if $x=2$, then ", "counterexample"),
        ("x^2=5", "if $x=2$, then ", "missing-counterexample"),
    ],
)
def test_exact_certificate_is_recomputed_from_ast(tmp_path, formula, condition, mutation):
    row = formalize_document(document(tmp_path, theorem(formula, condition=condition)))[0]
    validate_formalization(row)
    check = row["exact_check"]
    if mutation == "equal":
        check["equal"] = not check["equal"]
    elif mutation == "coefficients":
        check["left_coefficients"] = check["right_coefficients"] = {"0": "42"}
    elif mutation == "condition":
        check["condition_value"] = -2
    elif mutation == "counterexample":
        check["counterexample"] = {"x": 3}
    else:
        check.pop("counterexample")
    with pytest.raises(ValueError, match="FORMALIZATION_EXACT_CHECK_AST_MISMATCH"):
        validate_formalization(row)
