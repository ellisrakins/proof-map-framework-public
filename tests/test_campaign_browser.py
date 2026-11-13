"""Exercise generated offline campaign/source/evidence links in actual Chromium."""

import os

import pytest
from test_campaign_dossier import make_campaign, make_task

from proofmap.campaign import queue
from proofmap.campaign.reports import write_campaign_report


@pytest.mark.skipif(
    os.environ.get("PROOFMAP_BROWSER_TEST") != "1",
    reason="Select real browser suite with PROOFMAP_BROWSER_TEST=1",
)
def test_campaign_links_and_hostile_text_in_chromium(tmp_path):
    from playwright.sync_api import sync_playwright

    hostile = '<script>window.PWNED=1</script><img src="https://example.invalid/exfil" onerror="window.PWNED=2">'
    store, campaign_id, refs, _ = make_campaign(tmp_path, hostile=hostile)
    try:
        task = make_task(store, campaign_id, refs[0], review=True)
        queue.enqueue(store, campaign_id, task, actor="browser-test", state="AWAITING_REVIEW")
        out = tmp_path / "dossier"
        model = write_campaign_report(store, campaign_id, out)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            remote = []
            page.on(
                "request",
                lambda request: (
                    remote.append(request.url)
                    if request.url.startswith(("http:", "https:"))
                    else None
                ),
            )
            page.goto((out / "campaign-report.html").as_uri())
            assert hostile in page.locator("body").inner_text()
            page.get_by_role("link", name="Planning", exact=True).click()
            assert (
                page.locator(":target").inner_text()
                == "Retained plans, ranking, blockers and assumptions"
            )
            assert "runnable-prerequisites-goal-relevance-v1" in page.locator("body").inner_text()
            assert "FORMALIZATION_UNSUPPORTED" in page.locator("body").inner_text()
            assert "PLANNING_ONLY" in page.locator("body").inner_text()
            page.get_by_role("link", name="Goals", exact=True).click()
            assert page.locator(":target").inner_text() == "Goals"
            page.get_by_role("link", name="Exact goal target").first.click()
            assert (
                page.locator(":target").get_attribute("id")
                == model["papers"][0]["claims"][0]["anchor"]
            )
            page.get_by_role("link", name="Tasks", exact=True).click()
            assert "AWAITING_REVIEW" in page.locator("body").inner_text()
            page.get_by_role("link", name="Exact source target", exact=True).first.click()
            page.get_by_role(
                "link", name="Formal statement, exact evidence, review and next actions", exact=True
            ).first.click()
            assert page.url.endswith("paper-report.html#" + page.url.split("#")[-1])
            page.locator("details summary").first.click()
            for text in ("Source", "Context", "Formal", "Evidence", "Reviews"):
                page.get_by_role("navigation", name="Claim details").get_by_role(
                    "link", name=text, exact=True
                ).click()
                assert page.locator(":target h3").inner_text() == text
            assert page.evaluate("window.PWNED") is None
            assert page.locator("script,img,svg").count() == 0
            assert page.locator('a[href^="javascript:"]').count() == 0
            assert remote == []
            browser.close()
    finally:
        store.close()
