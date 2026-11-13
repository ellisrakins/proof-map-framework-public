"""Browser smoke tests for the local studio; run explicitly with installed Chromium."""

import io
import json
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from proofmap.studio import StudioServer

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / ".work" / "studio-qa"
    out.mkdir(parents=True, exist_ok=True)
    server = StudioServer(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            expect(page.locator("#mode-tag")).to_have_text("DEMO", timeout=10000)
            assert int(page.locator("#metric-nodes").inner_text()) > 5
            page.screenshot(path=str(out / "desktop.png"), full_page=True)
            page.locator(".claim-item").first.click()
            assert "Authored status" in page.locator("#inspector-content").inner_text()
            page.locator("#atlas-mode").click()
            assert page.locator("#atlas-mode").get_attribute("aria-pressed") == "true"
            page.locator("#sphere-mode").click()
            page.locator("#zoom-in").click()
            page.locator("#reset-view").click()
            page.locator("#search").fill("no matching claim xyz")
            assert "No claims match" in page.locator("#claim-list").inner_text()
            page.locator("#search").fill("")
            with page.expect_download() as downloaded:
                page.locator("#export-json").click()
            assert downloaded.value.suggested_filename == "proof-map-analysis.json"
            page.locator("[data-view=papers]").click()
            page.locator("#file-input").set_input_files(
                ROOT / "tests/fixtures/papers/train/basic.tex"
            )
            expect(page.locator("#mode-tag")).to_have_text("PAPER", timeout=100000)
            assert int(page.locator("#metric-nodes").inner_text()) >= 1
            assert page.locator("#metric-gaps").inner_text() == "0"
            page.locator(".claim-item").first.click()
            page.screenshot(path=str(out / "paper.png"), full_page=True)
            page.locator("[data-view=analysis]").click()
            assert "No model, Lean execution" in page.locator("#analysis-notice").inner_text()
            assert "NOT RUN" in page.locator("#checks").inner_text()
            assert "Recorded" not in page.locator("#checks").inner_text()
            page.screenshot(path=str(out / "analysis.png"), full_page=True)
            page.locator("[data-view=papers]").click()
            assert "basic.tex" in page.locator("#library-list").inner_text()
            page.locator("#file-input").set_input_files(
                {"name": "bad.json", "mimeType": "application/json", "buffer": b"{invalid"}
            )
            expect(page.locator("#status")).to_have_class("status error", timeout=100000)
            assert page.locator("#import-button").is_enabled()
            page.locator("#file-input").set_input_files(
                {
                    "name": "bad.html",
                    "mimeType": "text/html",
                    "buffer": b"<script>alert(1)</script>",
                }
            )
            assert "Use a PDF" in page.locator("#status").inner_text()
            page.locator("#load-demo").click()
            expect(page.locator("#mode-tag")).to_have_text("DEMO", timeout=10000)
            # Drag-and-drop dispatch exercises the browser file path, not a mocked API.
            raw = (ROOT / "tests/fixtures/papers/train/basic.tex").read_text()
            page.evaluate(
                """text => {const dt=new DataTransfer();dt.items.add(new File([text], 'drop.tex',{type:'text/plain'}));window.dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true,cancelable:true}));}""",
                raw,
            )
            expect(page.locator("#map-title")).to_have_text("drop.tex", timeout=100000)
            assert page.locator("#paper-count").inner_text() == "2"
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(out / "mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("[data-view=analysis]").click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.reload()
            expect(page.locator("#mode-tag")).to_have_text("DEMO", timeout=10000)
            assert page.locator("#paper-count").inner_text() == "0"
            # Synthetic source only: real PDF parsing and candidate graph, no private paper fixtures.
            from reportlab.pdfgen import canvas

            pdf = io.BytesIO()
            document = canvas.Canvas(pdf)
            for y, text in [
                (750, "Lemma 1. Every positive integer is nonzero."),
                (720, "Proof. This follows from positivity."),
                (680, "Theorem 2. If n is positive then n is not zero."),
                (650, "Proof. By Lemma 1, the assertion follows."),
            ]:
                document.drawString(50, y, text)
            document.save()
            page.locator("#file-input").set_input_files(
                {"name": "semantic.pdf", "mimeType": "application/pdf", "buffer": pdf.getvalue()}
            )
            expect(page.locator("#mode-tag")).to_have_text("PAPER", timeout=100000)
            expect(page.locator("#nodes-label")).to_have_text("Extracted candidates")
            assert int(page.locator("#metric-nodes").inner_text()) == 2
            assert int(page.locator("#metric-edges").inner_text()) >= 1
            assert page.locator("#metric-gaps").inner_text() == "0"
            page.locator(".claim-item").first.click()
            assert "Page 1" in page.locator("#inspector-content").inner_text()
            assert "EXTRACTION CANDIDATE" in page.locator("#inspector-content").inner_text().upper()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(out / "semantic-pdf.png"), full_page=True)
            page.locator("#load-gravity").click()
            expect(page.locator("#mode-tag")).to_have_text("DEMO")
            expect(page.locator("#map-title")).to_contain_text("Newton")
            assert page.locator("#boundary-lab").is_visible()
            page.get_by_role("button", name="Start boundary analysis", exact=False).click()
            assert page.locator(".walkthrough-detail").is_visible()
            assert "Boundary question" in page.locator("#boundary-lab").inner_text()
            first_count = page.locator(".claim-item").count()
            assert 0 < first_count < int(page.locator("#metric-nodes").inner_text())
            for _ in range(page.locator(".walkthrough-steps button").count() - 2):
                page.get_by_role("button", name="Next analysis step", exact=False).click()
                assert page.locator(".claim-item").count() > 0
            assert page.get_by_role("button", name="Return to full map").is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(out / "gravity.png"), full_page=True)
            page.get_by_role("button", name="Return to full map").click()
            assert page.locator(".claim-item").count() == int(
                page.locator("#metric-nodes").inner_text()
            )
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    assert not errors, errors
    (out / "results.json").write_text(
        json.dumps(
            {
                "passed": True,
                "browser_errors": errors,
                "screenshots": ["desktop.png", "paper.png", "analysis.png", "mobile.png"],
            },
            indent=2,
        )
    )
    print(
        "Studio browser smoke passed: demo, controls, search, export, TeX, drag/drop, errors, mobile, reload."
    )


if __name__ == "__main__":
    main()
