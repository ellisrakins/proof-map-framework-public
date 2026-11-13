"""Synthetic PDF resource-limit regressions; no private manuscripts."""

from types import SimpleNamespace

import pytest

from proofmap import paper_sources


class TextPage:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self, *, extraction_mode: str) -> str:
        assert extraction_mode == "plain"
        return self.text


def mock_reader(monkeypatch: pytest.MonkeyPatch, texts: list[str]) -> None:
    pypdf = pytest.importorskip("pypdf")
    reader = SimpleNamespace(is_encrypted=False, pages=[TextPage(text) for text in texts])
    monkeypatch.setattr(pypdf, "PdfReader", lambda *args, **kwargs: reader)


@pytest.mark.parametrize("page_count", [166, 250])
def test_long_text_pdf_allowed(monkeypatch: pytest.MonkeyPatch, page_count: int) -> None:
    texts = [f"Synthetic page {index}" for index in range(page_count)]
    mock_reader(monkeypatch, texts)
    assert paper_sources._pdf_pages(b"synthetic") == texts


def test_pdf_page_limit_reports_count_and_maximum(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_reader(monkeypatch, ["text"] * 251)
    with pytest.raises(ValueError, match="PDF has 251 pages; maximum is 250"):
        paper_sources._pdf_pages(b"synthetic")


def test_encrypted_pdf_rejected_before_reading_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    pypdf = pytest.importorskip("pypdf")
    # No pages attribute: encrypted inputs must not attempt page enumeration.
    monkeypatch.setattr(
        pypdf, "PdfReader", lambda *args, **kwargs: SimpleNamespace(is_encrypted=True)
    )
    with pytest.raises(ValueError, match="UNSUPPORTED_ENCRYPTED_PDF"):
        paper_sources._pdf_pages(b"synthetic")


def test_aggregate_text_limit_counts_utf8_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paper_sources, "MAX_BYTES", 8)
    mock_reader(monkeypatch, ["éé", "éé"])
    assert paper_sources._pdf_pages(b"synthetic") == ["éé", "éé"]
    mock_reader(monkeypatch, ["éé", "éé", "a"])
    with pytest.raises(ValueError, match="aggregate PDF text exceeds 8 UTF-8 bytes"):
        paper_sources._pdf_pages(b"synthetic")


def test_per_page_text_limit_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paper_sources, "MAX_FILE_BYTES", 3)
    mock_reader(monkeypatch, ["éé"])
    with pytest.raises(ValueError, match="RESOURCE_LIMIT: PDF text"):
        paper_sources._pdf_pages(b"synthetic")
