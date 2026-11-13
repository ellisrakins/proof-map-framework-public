import io
import zipfile
from pathlib import Path

import pytest

from proofmap.paper_sources import acquire, parse, validate_locator


def test_real_syntax_parser_and_exact_anchors():
    manifest, files = acquire(Path("tests/fixtures/papers/train/basic.tex"))
    ir = parse(manifest, files)
    assert ir["parser"]["name"] == "pylatexenc"
    assert sum(e["kind"] == "ASSERTION" for e in ir["elements"]) == 2
    proofs = [e for e in ir["elements"] if e["kind"] == "PROOF"]
    assert len(proofs) == 1 and proofs[0]["proof_for"]
    for element in ir["elements"]:
        validate_locator(element["locator"], files, element["text"])
    assert ir["references"][0]["targets"]


def test_heldout_missing_refs_and_proof_quality():
    manifest, files = acquire(Path("tests/fixtures/papers/heldout/missing.tex"))
    ir = parse(manifest, files)
    assert {f["code"] for f in ir["findings"]} >= {
        "MISSING_OR_AMBIGUOUS_REFERENCE",
        "UNRESOLVED_CITATION",
        "UNSUPPORTED_MACRO",
    }
    assert next(e for e in ir["elements"] if e["kind"] == "PROOF")["quality"] == "OMITTED_OR_SKETCH"


@pytest.mark.parametrize(
    "name", ["../evil.tex", "/evil.tex", "C:/evil.tex", "con.tex", "a\\b.tex", "a/../b.tex"]
)
def test_archive_escape_rejected(tmp_path, name):
    archive = tmp_path / "paper.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(name.replace("\\", "!"), "untrusted")
    if "\\" in name:
        archive.write_bytes(archive.read_bytes().replace(b"!", b"\\"))
    with pytest.raises(ValueError):
        acquire(archive)


def test_include_cycle_custom_theorem_and_unicode(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\newtheorem{result}{Result}\input{part}", encoding="utf-8"
    )
    (tmp_path / "part.tex").write_text(
        r"é\begin{result}\label{x}If $x=1$, then $x=1$.\end{result}\input{main}", encoding="utf-8"
    )
    manifest, files = acquire(tmp_path)
    ir = parse(manifest, files)
    assert any(e["kind"] == "ASSERTION" for e in ir["elements"])
    assert any(f["code"] == "INCLUDE_CYCLE" for f in ir["findings"])
    for e in ir["elements"]:
        validate_locator(e["locator"], files, e["text"])


def test_duplicate_case_and_ambiguous_entrypoint(tmp_path):
    zpath = tmp_path / "x.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("A.tex", "x")
        z.writestr("a.tex", "y")
    with pytest.raises(ValueError, match="COLLISION"):
        acquire(zpath)


def test_pdf_real_adapter_without_invented_offsets(tmp_path):
    from pypdf import PdfWriter

    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(300, 300)
    writer.write(stream)
    path = tmp_path / "blank.pdf"
    path.write_bytes(stream.getvalue())
    manifest, files = acquire(path)
    ir = parse(manifest, files)
    assert ir["parser"]["name"] == "pypdf"
    assert ir["findings"][0]["code"] == "NEEDS_OCR"
    assert ir["elements"][0]["locator"]["start"] is None
