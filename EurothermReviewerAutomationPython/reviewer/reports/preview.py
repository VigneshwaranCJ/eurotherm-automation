"""Native page-count and rendered Preview verification."""
from ..common.errors import WorkflowError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from .validation import message_only, preview_page_total, verify_text

MESSAGE_PREVIEW_TIMEOUT = 60000


def validate_preview(page, group, chart, settings, log, run_id):
    # Listen to both native responses before clicking; inspect page count immediately.
    previews = []
    def collect(response):
        if response.url.endswith("/api/groupsamples/preview"):
            previews.append(response)
    page.on("response", collect)
    try:
        with page.expect_response(lambda r: r.url.endswith("/api/groupsamples/pageCheck"), timeout=120000) as pending:
            page.get_by_role("button", name="Preview", exact=True).click()
        response = pending.value
        if not response.ok:
            raise RuntimeError(f"Native page check failed: {response.status}")
        pages = response.json()
        log("nativePageCheck", dict(pages=pages))
        # This is Reviewer's own gate on chart pages; PDFs are counted from their page footers.
        if float(pages) > 30:
            raise RuntimeError(f"Reviewer limits reports to 30 pages; selected report needs {pages}. Narrow the configured interval.")
        if not previews:
            with page.expect_response(lambda r: r.url.endswith("/api/groupsamples/preview"), timeout=180000) as pending:
                page.wait_for_timeout(1)
            previews.append(pending.value)
        if not previews[-1].ok:
            raise RuntimeError(f"Preview failed: HTTP {previews[-1].status}")
        body = page.frame_locator("#previewWindow").locator("body")
        try:
            body.get_by_text(settings.title, exact=False).first.wait_for(
                timeout=MESSAGE_PREVIEW_TIMEOUT if message_only(settings) else 180000)
        except PlaywrightTimeout as error:
            if not message_only(settings):
                raise
            # Days confirmed to have no messages are skipped earlier, so this is a real failure.
            raise RuntimeError("Reviewer listed messages for this interval but rendered no Message Logs preview") from error
        text = body.inner_text()
        evidence = verify_text(text, group, chart, settings)
        chart["previewPages"] = preview_page_total(text)
        graphics, tables = body.locator("svg,img,canvas").count(), body.locator("table").count()
        if settings.include_chart and not graphics:
            raise RuntimeError("Preview has no chart graphic")
        if settings.include_values and not tables:
            raise RuntimeError("Preview has no raw-value table")
        (settings.logs / f"preview-{run_id}.html").write_text(body.inner_html(), encoding="utf-8")
        log("preview", dict(pages=chart["previewPages"], nativePageCheck=pages, graphics=graphics, tables=tables,
                            textExcerpt=text[:2000], **evidence))
        page.screenshot(path=str(settings.screenshots / f"preview-{run_id}.png"), full_page=True)
    except Exception as error:
        raise WorkflowError("PREVIEW_FAILED", str(error)) from error
    finally:
        page.remove_listener("response", collect)
