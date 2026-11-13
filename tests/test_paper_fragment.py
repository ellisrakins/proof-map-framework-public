"""Source-driven fragment and independent locator regression tests."""

from pathlib import Path

import pytest

from proofmap.integrity import artifact_digest
from proofmap.paper_sources import acquire, parse, validate_locator


def document(tmp_path, text):
    path = tmp_path / "novel.tex"
    path.write_text(text, encoding="utf-8")
    manifest, files = acquire(path)
    return parse(manifest, files), files


@pytest.mark.parametrize(
    ("variable", "formula", "identity"),
    [
        ("x", "(x+1)^2=x^2+2x+1", True),
        ("t", "(3t-2)(t+4)=3t^2+10t-8", True),
        ("z", "(z-1)^3=z^3-3z^2+3z-1", True),
        ("u", "u^0+u-u=1", True),
        ("a", "(a+1)^2=a^2+1", False),
    ],
)
def test_runtime_ast_and_exact_statement(tmp_path, variable, formula, identity):
    from proofmap.formalize import formalize_document

    ir, _ = document(
        tmp_path,
        rf"\begin{{theorem}}For every ${variable}\in\mathbb{{Z}}$,\[{formula}.\]\end{{theorem}}",
    )
    row = formalize_document(ir)[0]
    assert row["status"] == "SUPPORTED"
    assert row["source_ast"]["variable"] == variable
    assert row["source_ast"]["domain"] == "Int"
    assert row["obligation"]["statement"].startswith(f"∀ ({variable} : Int), ")
    assert row["exact_check"]["equal"] is identity
    assert row["candidate"] == "by\n  grind\n"
    assert set(row["source_spans"]) == {"binder", "equation", "left", "right"}


@pytest.mark.parametrize(
    "body",
    [
        r"For every $x\in\mathbb{R}$,\[x=x.\]",
        r"For every $x\in\mathbb{Z}$ with $x>0$,\[x=x.\]",
        r"If $x=0$, then \[x=x.\]",
        r"For every $x\in\mathbb{Z}$,\[y=y.\]",
        r"For every $x\in\mathbb{Z}$,\[x^{99}=x.\]",
        r"For every $x\in\mathbb{Z}$,\[\mystery{x}=x.\]",
        r"For every $x\in\mathbb{Z}$,\[x=x.\] Assume $x>1$.",
        r"For every $x\in\mathbb{Z}$,\[x=x=x.\]",
    ],
)
def test_unparsed_scope_and_notation_block_formalization(tmp_path, body):
    from proofmap.formalize import formalize_document

    ir, _ = document(tmp_path, r"\begin{theorem}" + body + r"\end{theorem}")
    assert formalize_document(ir)[0]["status"] == "UNSUPPORTED"


def test_roles_aliases_and_macro_context_are_conservative(tmp_path):
    from proofmap.formalize import formalize_document

    ir, _ = document(
        tmp_path,
        r"\newtheorem{result}{Result}\newcommand{\local}{2}"
        r"\begin{definition}An object.\end{definition}"
        r"\begin{example}An example.\end{example}"
        r"\begin{remark}A remark.\end{remark}"
        r"\begin{result}For every $x\in\mathbb{Z}$,\[x=x.\]\end{result}"
        r"\begin{theorem}For every $x\in\mathbb{Z}$,\[x=x.\]\end{theorem}",
    )
    roles = [el["role"] for el in ir["elements"] if el["kind"] == "ASSERTION"]
    assert roles == ["DEFINITION", "EXAMPLE", "REMARK", "UNRESOLVED", "THEOREM"]
    assert formalize_document(ir)[0]["reason"] == "UNRESOLVED_DEFINITION_CONTEXT"


def test_pdf_forged_excerpt_and_page_rejected():
    manifest, files = acquire(Path("tests/fixtures/papers/pdf/born_digital.pdf"))
    ir = parse(manifest, files)
    el = ir["elements"][0]
    loc = dict(el["locator"])
    loc["page"] = 12345
    with pytest.raises(ValueError, match="PDF"):
        validate_locator(loc, files, el["text"])
    loc = dict(el["locator"])
    loc["excerpt_sha256"] = artifact_digest(b"fabricated theorem")
    with pytest.raises(ValueError, match="MISMATCH"):
        validate_locator(loc, files, "fabricated theorem")


def test_parser_deadline_is_enforced_and_source_identity_retained(tmp_path):
    path = tmp_path / "bounded.tex"
    path.write_text("x")
    manifest, files = acquire(path)
    ir = parse(manifest, files, timeout_seconds=0.000001)
    assert ir["status"] == "PARTIAL"
    assert ir["revision"] == manifest.revision
    assert ir["findings"][0]["code"] == "PARSER_TIMEOUT"
    assert ir["parser"]["execution"] == "TIMEOUT"


def test_surrounding_scope_is_not_guessed_from_keywords(tmp_path):
    from proofmap.formalize import formalize_document

    ir, _ = document(
        tmp_path,
        r"All quantities below are positive."
        r"\begin{theorem}For every $x\in\mathbb{Z}$,\[x=x.\]\end{theorem}",
    )
    assert formalize_document(ir)[0]["reason"] == "UNRESOLVED_DEFINITION_CONTEXT"


@pytest.mark.parametrize(
    "prefix",
    [
        r"\let\mathbb\mathfrak",
        r"\usepackage{unresolved-package}",
        r"\renewenvironment{theorem}{Restricted universe.}{}",
        r"\begin{customscope}Restricted universe.\end{customscope}",
    ],
)
def test_unsupported_constructs_block_implicit_semantic_changes(tmp_path, prefix):
    from proofmap.formalize import formalize_document

    ir, _ = document(
        tmp_path, prefix + r"\begin{theorem}For every $x\in\mathbb{Z}$,\[x=x.\]\end{theorem}"
    )
    assert formalize_document(ir)[0]["reason"] == "UNRESOLVED_DEFINITION_CONTEXT"


def test_formal_source_spans_preserve_unicode_and_crlf(tmp_path):
    from proofmap.formalize import formalize_document

    ir, files = document(
        tmp_path,
        "% é comment\r\n"
        r"\begin{theorem}\label{utf8}For every $z\in\mathbb{Z}$," + "\r\n"
        r"\[(z-1)^2=z^2-2z+1.\]\end{theorem}",
    )
    row = formalize_document(ir)[0]
    assert row["status"] == "SUPPORTED"
    for span in row["source_spans"].values():
        raw = files[span["artifact"]][span["start"] : span["end"]]
        assert artifact_digest(raw) == span["excerpt_sha256"]
    binder = row["source_spans"]["binder"]
    assert files[binder["artifact"]][binder["start"] : binder["end"]] == rb"$z\in\mathbb{Z}$"


def test_pdf_validation_session_reconstructs_once(monkeypatch):
    import proofmap.paper_sources as sources

    manifest, files = acquire(Path("tests/fixtures/papers/pdf/born_digital.pdf"))
    ir = parse(manifest, files)
    real_parse = sources.parse
    calls = []

    def observed(*args, **kwargs):
        calls.append(1)
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(sources, "parse", observed)
    session = sources.LocatorValidationSession()
    for _ in range(2):
        for el in ir["elements"]:
            validate_locator(el["locator"], files, el["text"], session=session)
    assert len(calls) == 1


@pytest.mark.parametrize("value", [True, False, 0, -1, 61, float("inf"), float("nan")])
def test_invalid_parser_deadline_rejected(tmp_path, value):
    source = tmp_path / "x.tex"
    source.write_text("hello")
    manifest, files = acquire(source)
    with pytest.raises(ValueError, match="PARSER_TIMEOUT_LIMIT"):
        parse(manifest, files, timeout_seconds=value)
