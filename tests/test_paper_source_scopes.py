"""Original source fixtures: lexical extraction is never proof authority."""

import pytest

from proofmap.formalize import formalize_document
from proofmap.paper_sources import acquire, parse_tex, validate_locator


def document(tmp_path, source, parts=None):
    (tmp_path / "main.tex").write_text(source, encoding="utf-8")
    for name, content in (parts or {}).items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    manifest, files = acquire(tmp_path, "main.tex")
    ir = parse_tex(manifest, files)
    for element in ir["elements"]:
        validate_locator(element["locator"], files, element["text"])
    return ir


def occurrences(ir, symbol):
    return [
        el for el in ir["elements"] if el["kind"] == "SYMBOL_OCCURRENCE" and el["symbol"] == symbol
    ]


def declarations(ir, symbol):
    return [
        el
        for el in ir["elements"]
        if el["kind"] == "MACRO_DEFINITION" and el.get("declaration", {}).get("symbol") == symbol
    ]


def test_group_shadowing_restores_outer_binding(tmp_path):
    ir = document(tmp_path, r"\newcommand{\foo}{1}\foo{\renewcommand{\foo}{2}\foo}\foo")
    defs = [el["id"] for el in declarations(ir, "foo")]
    uses = occurrences(ir, "foo")
    assert [el["definition"] for el in uses] == [defs[0], defs[1], defs[0]]
    assert uses[0]["lexical_scope"] == uses[2]["lexical_scope"]
    assert uses[1]["lexical_scope"] != uses[0]["lexical_scope"]


def test_math_tokens_are_exact_and_keep_each_use_anchor(tmp_path):
    ir = document(tmp_path, r"é\newcommand{\foo}{1}$\foo+\foobar+\foo$")
    uses = occurrences(ir, "foo")
    assert len(uses) == 2
    assert all(el["text"] == r"\foo" for el in uses)
    assert uses[0]["locator"]["end"] < uses[1]["locator"]["start"]
    assert len(occurrences(ir, "foobar")) == 1
    assert "definition" not in occurrences(ir, "foobar")[0]
    assert next(el for el in ir["elements"] if el["kind"] == "MATH_EXPRESSION")[
        "context_dependencies"
    ] == [declarations(ir, "foo")[0]["id"]]


def test_prefix_collision_cannot_create_false_dependency(tmp_path):
    ir = document(tmp_path, r"\newcommand{\alph}{1}$\alpha$")
    math = next(el for el in ir["elements"] if el["kind"] == "MATH_EXPRESSION")
    assert not math.get("context_dependencies")
    assert not occurrences(ir, "alph")


def test_include_shares_then_group_restores_bindings(tmp_path):
    ir = document(
        tmp_path,
        r"\newcommand{\foo}{1}{\input{part}\foo}\foo",
        {"part.tex": r"\foo\renewcommand{\foo}{2}\foo"},
    )
    defs = [el["id"] for el in declarations(ir, "foo")]
    assert [el["definition"] for el in occurrences(ir, "foo")] == [
        defs[0],
        defs[1],
        defs[1],
        defs[0],
    ]


def test_environment_local_binding_does_not_escape(tmp_path):
    ir = document(
        tmp_path,
        r"\newcommand{\foo}{1}\begin{theorem}\renewcommand{\foo}{2}$\foo$\end{theorem}\foo",
    )
    defs = [el["id"] for el in declarations(ir, "foo")]
    uses = occurrences(ir, "foo")
    assert [el["definition"] for el in uses] == [defs[1], defs[0]]
    theorem = next(el for el in ir["elements"] if el["kind"] == "ASSERTION")
    assert uses[0]["scope"] != theorem["scope"]


def test_math_local_binding_does_not_escape(tmp_path):
    ir = document(tmp_path, r"\newcommand{\foo}{1}$\renewcommand{\foo}{2}\foo$\foo")
    defs = [el["id"] for el in declarations(ir, "foo")]
    assert [el["definition"] for el in occurrences(ir, "foo")] == [defs[1], defs[0]]


def test_sections_nest_discourse_without_resetting_lexical_bindings(tmp_path):
    ir = document(
        tmp_path,
        r"\newcommand{\foo}{1}\section{One}\foo\subsection{Two}\foo"
        r"\subsubsection{Three}\foo\section{Four}\foo",
    )
    uses = occurrences(ir, "foo")
    assert len({el["lexical_scope"] for el in uses}) == 1
    assert len({el["definition"] for el in uses}) == 1
    scopes = {scope["id"]: scope for scope in ir["scopes"]}
    assert scopes[uses[1]["scope"]]["parent"] == uses[0]["scope"]
    assert scopes[uses[2]["scope"]]["parent"] == uses[1]["scope"]
    assert scopes[uses[3]["scope"]]["parent"] == "global"


def test_providecommand_keeps_existing_binding(tmp_path):
    ir = document(tmp_path, r"\newcommand{\foo}{1}\providecommand{\foo}{2}\foo")
    assert occurrences(ir, "foo")[0]["definition"] == declarations(ir, "foo")[0]["id"]


@pytest.mark.parametrize(
    "declaration",
    [r"\newcommand*{\foo}[2][x]{#1+#2}", r"\DeclareMathOperator*{\foo}{lim}"],
)
def test_common_declaration_argument_positions(tmp_path, declaration):
    ir = document(tmp_path, declaration + r"\foo")
    assert occurrences(ir, "foo")[0]["definition"] == declarations(ir, "foo")[0]["id"]


def test_binding_records_do_not_authorize_arbitrary_macro_formalization(tmp_path):
    ir = document(
        tmp_path,
        r"\newcommand{\foo}{x+1}\begin{theorem}For every $x\in\mathbb{Z}$,"
        r"\[\foo=\foo.\]\end{theorem}",
    )
    row = formalize_document(ir)[0]
    assert row["status"] == "UNSUPPORTED"
    assert row["reason"] == "UNRESOLVED_DEFINITION_CONTEXT"


def test_use_before_declaration_stays_unresolved(tmp_path):
    ir = document(tmp_path, r"\foo\newcommand{\foo}{1}\foo")
    before, after = occurrences(ir, "foo")
    assert before["binding_status"] == "UNRESOLVED"
    assert "definition" not in before
    assert after["definition"] == declarations(ir, "foo")[0]["id"]


@pytest.mark.parametrize(
    "declaration",
    [
        r"\renewcommand{\foo}{1}",
        r"\newcommand{bad}{1}",
        r"\newcommand{\foo}[10]{#1}",
        r"\newcommand{\foo}[-1]{#1}",
        r"\newcommand{\foo}[0][x]{#1}",
    ],
)
def test_invalid_declarations_never_create_bindings(tmp_path, declaration):
    from proofmap.schema import validate

    ir = document(tmp_path, declaration + r"\foo")
    definition = next(el for el in ir["elements"] if el["kind"] == "MACRO_DEFINITION")
    assert definition["declaration"]["binding_status"] == "INVALID"
    assert "definition" not in occurrences(ir, "foo")[0]
    assert ir["status"] == "PARTIAL"
    assert not validate("document-ir", ir)


@pytest.mark.parametrize("dynamic", [r"\def\bar{2}", r"\let\bar\foo", r"\csname bar\endcsname"])
def test_dynamic_local_scope_is_unresolved_then_restored(tmp_path, dynamic):
    ir = document(tmp_path, r"\newcommand{\foo}{1}{" + dynamic + r"\foo}\foo")
    local, restored = occurrences(ir, "foo")[-2:]
    assert local["binding_status"] == "UNRESOLVED"
    assert "definition" not in local
    assert restored["definition"] == declarations(ir, "foo")[0]["id"]


@pytest.mark.parametrize("dynamic", [r"\global\def\foo{2}", r"\gdef\foo{2}", r"\xdef\foo{2}"])
def test_global_dynamic_construct_cannot_restore_outer_certainty(tmp_path, dynamic):
    ir = document(tmp_path, r"\newcommand{\foo}{1}{" + dynamic + r"}\foo")
    use = occurrences(ir, "foo")[-1]
    assert use["binding_status"] == "UNRESOLVED"
    assert "definition" not in use


def test_missing_include_invalidates_active_binding_certainty(tmp_path):
    ir = document(tmp_path, r"\newcommand{\foo}{1}\input{missing}\foo")
    use = occurrences(ir, "foo")[-1]
    assert use["binding_status"] == "UNRESOLVED"
    assert "definition" not in use
    assert any(f["code"] == "MISSING_INCLUDE" for f in ir["findings"])


def test_grouped_missing_include_cannot_restore_outer_certainty(tmp_path):
    ir = document(tmp_path, r"\newcommand{\foo}{1}{\input{missing}}\foo")
    use = occurrences(ir, "foo")[-1]
    assert use["binding_status"] == "UNRESOLVED"
    assert "definition" not in use


def test_aftergroup_effect_cannot_restore_outer_certainty(tmp_path):
    ir = document(
        tmp_path,
        r"\newcommand{\foo}{1}\newcommand{\changer}{\renewcommand{\foo}{2}}"
        r"{\aftergroup\changer}\foo",
    )
    use = occurrences(ir, "foo")[-1]
    assert use["binding_status"] == "UNRESOLVED"
    assert "definition" not in use


def test_unexpanded_optional_default_cannot_restore_outer_certainty(tmp_path):
    ir = document(
        tmp_path,
        r"\newcommand{\foo}{1}\newcommand{\changer}[1][\global\def\foo{2}]{#1}"
        r"{\changer}\foo",
    )
    use = occurrences(ir, "foo")[-1]
    assert use["binding_status"] == "UNRESOLVED"
    assert "definition" not in use


def test_macro_replacement_tokens_are_not_frozen_as_declaration_time_uses(tmp_path):
    ir = document(
        tmp_path,
        r"\newcommand{\baseval}{1}\newcommand{\foo}{\baseval}\renewcommand{\baseval}{2}\foo",
    )
    declaration = declarations(ir, "foo")[0]["declaration"]
    assert declaration["replacement_tokens"] == ["baseval"]
    assert not occurrences(ir, "baseval")
    assert occurrences(ir, "foo")[0]["definition"] == declarations(ir, "foo")[0]["id"]
    assert any(f["code"] == "MACRO_EXPANSION_NOT_PERFORMED" for f in ir["findings"])


def test_known_macro_argument_keeps_anchored_custom_use(tmp_path):
    ir = document(tmp_path, r"\newcommand{\foo}{1}\textbf{\foo}")
    use = occurrences(ir, "foo")[0]
    assert use["text"] == r"\foo"
    assert use["definition"] == declarations(ir, "foo")[0]["id"]


def test_unexpanded_mutating_replacement_cannot_preserve_later_binding_certainty(tmp_path):
    ir = document(
        tmp_path,
        r"\newcommand{\foo}{1}\newcommand{\changer}{\renewcommand{\foo}{2}}\changer\foo",
    )
    later = occurrences(ir, "foo")[-1]
    assert later["binding_status"] == "UNRESOLVED"
    assert "definition" not in later


@pytest.mark.parametrize(
    "definitions",
    [r"\newcommand{\foo}{\foo}", r"\newcommand{\foo}{\baseval}\newcommand{\baseval}{\foo}"],
)
def test_cyclic_replacement_is_explicitly_unresolved(tmp_path, definitions):
    ir = document(tmp_path, definitions + r"\foo")
    use = occurrences(ir, "foo")[-1]
    assert use["binding_status"] == "UNRESOLVED"
    assert use["binding_reason"] == "MACRO_CYCLE"
    assert "definition" not in use


def test_commented_macro_tokens_are_not_uses(tmp_path):
    ir = document(tmp_path, "\\newcommand{\\foo}{1}% \\foo\n$\\foo% \\foo\n$")
    assert len(occurrences(ir, "foo")) == 1


def test_scoped_paper_pipeline_roundtrip_and_revision_invalidation(tmp_path):
    from proofmap.paper import ci, diff
    from proofmap.paper_store import PaperStore

    source = tmp_path / "scoped.tex"
    source.write_text(
        r"\newcommand{\foo}{1}\begin{theorem}\label{t}$\foo=1$\end{theorem}"
        r"\begin{proof}{\renewcommand{\foo}{2}$\foo=2$}\end{proof}",
        encoding="utf-8",
    )
    first, code = ci(source, tmp_path / "first", tmp_path / "store")
    assert code == 0
    assert first["assertions"][0]["status"] == "AUTHOR_ASSERTED"
    assert first["assertions"][0]["proof_ids"]
    assert not first["assessment"]["closure"]["closed"]
    assert first["formalizations"][0]["status"] == "UNSUPPORTED"
    store = PaperStore(tmp_path / "store")
    try:
        run = store.list()[0]["run"]
        assert store.inspect(run)["bundle"]["document_ir"] == first["document_ir"]
    finally:
        store.close()
    source.write_text(source.read_text(encoding="utf-8").replace("{2}", "{3}"), encoding="utf-8")
    second, _ = ci(source, tmp_path / "second", tmp_path / "store")
    delta = diff(first, second)
    assert delta["reviews"] == "STALE"
    assert delta["invalidated_assertions"]


def test_scoped_nested_macro_uses_stay_with_theorem_and_proof_chunk(tmp_path):
    from proofmap.extractor import chunk_document

    ir = document(
        tmp_path,
        r"\begin{theorem}\newcommand{\foo}{1}{\foo}\end{theorem}"
        r"\begin{proof}\newcommand{\baseval}{2}$\baseval$\end{proof}",
    )
    ids = {el["id"] for el in ir["elements"]}
    ir["elements"] = [
        *[
            {"id": f"s{i}", "kind": "PROSE", "text": f"Context {i}", "scope": "global"}
            for i in range(255)
        ],
        *ir["elements"],
    ]
    chunks, findings = chunk_document(ir)
    assert not findings
    assert len(chunks) == 2
    assert {el["id"] for el in chunks[1]["elements"]} == ids
