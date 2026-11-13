"""Actual browser execution required when explicitly selected by security CI."""

import os
from pathlib import Path

import pytest

from proofmap.examples import build_minimal_conops_map
from proofmap.surface_visualize import render_surface_explorer_html


@pytest.mark.skipif(
    os.environ.get("PROOFMAP_BROWSER_TEST") != "1",
    reason="Select real browser suite with PROOFMAP_BROWSER_TEST=1",
)
def test_paper_labels_remain_inert_in_real_browser(tmp_path: Path):
    from playwright.sync_api import sync_playwright

    pm = build_minimal_conops_map()
    sentinel = '</script><script>window.PWNED=1</script><img src=x onerror="window.PWNED=2"><svg onload="window.PWNED=3">'
    for node in pm.nodes.values():
        node.label = sentinel
        node.statement = sentinel
        node.theory_ids = [sentinel]
    path = tmp_path / "explorer.html"
    render_surface_explorer_html(pm, path)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(path.as_uri())
        assert page.locator("#ledger tbody tr").count() > 0
        page.locator("#ledger tbody tr").first.focus()
        assert sentinel in page.locator("#infoBox").inner_text()
        assert page.evaluate("window.PWNED") is None
        assert page.locator("img, svg").count() == 0
        assert not errors
        browser.close()


@pytest.mark.skipif(
    os.environ.get("PROOFMAP_BROWSER_TEST") != "1",
    reason="Select real browser suite with PROOFMAP_BROWSER_TEST=1",
)
def test_static_paper_report_keeps_source_inert_and_readable(tmp_path: Path):
    from playwright.sync_api import sync_playwright

    from proofmap.paper import ci

    sentinel = '</script><script>window.PWNED=1</script><img src=x onerror="window.PWNED=2">'
    math = "α ≤ β — source text"
    source = tmp_path / "paper.tex"
    source.write_text(
        r"\documentclass{article}\begin{document}\begin{theorem}"
        + sentinel
        + math
        + " javascript:alert(1)"
        + r"\end{theorem}\end{document}",
        encoding="utf-8",
    )
    ci(source, tmp_path / "out", tmp_path / "store")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto((tmp_path / "out" / "report.html").as_uri())
        page.locator("details summary").first.focus()
        page.keyboard.press("Enter")
        assert sentinel in page.locator("body").inner_text()
        assert math in page.locator("body").inner_text()
        assert page.locator("script, img, svg").count() == 0
        assert page.locator('a[href^="javascript:"]').count() == 0
        assert page.evaluate("window.PWNED") is None
        browser.close()
