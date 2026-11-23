"""Native PDF download and parsed content verification."""
from datetime import datetime, timezone
import re
import shutil
from .validation import verify_page_count, verify_text


def download_pdf(page, group, chart, settings, log):
    from pypdf import PdfReader
    if shutil.disk_usage(settings.reports).free < 100 * 1024 * 1024:
        raise RuntimeError("Less than 100 MB available for report output")
    with page.expect_download(timeout=180000) as pending:
        page.get_by_role("button", name="Download PDF", exact=True).click()
    download = pending.value
    if download.failure():
        raise RuntimeError(f"Native PDF download failed: {download.failure()}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    label = "HistoricalTest" if settings.range_mode == "latestAvailable" else "Report"
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", group["groupName"])
    output = settings.reports / (settings.report_name or f"{name}_{label}_Python_{stamp}.pdf")
    if settings.report_name and output.exists():
        output = output.with_name(f'{output.stem}_{stamp}{output.suffix}')
    if output.exists():
        raise RuntimeError("Report output already exists")
    pending_output = output.with_suffix('.pdf.part')
    download.save_as(pending_output)
    with pending_output.open('rb') as stream:
        signature = stream.read(5)
    if signature != b"%PDF-":
        raise RuntimeError("Downloaded artifact is not a PDF")
    with pending_output.open("rb") as stream:
        document = PdfReader(stream)
        if not document.pages:
            raise RuntimeError("PDF contains no pages")
        page_texts = [pdf_page.extract_text() or "" for pdf_page in document.pages]
        text = "\n".join(page_texts)
        evidence = verify_text(text, group, chart, settings) or {}
        pages = verify_page_count(page_texts, settings, chart.get("previewPages"))
        result = dict(output=str(output), size=pending_output.stat().st_size, pages=pages,
                      nativeFilename=download.suggested_filename, readable=True, channelCount=len(chart["channels"]),
                      **evidence)
    pending_output.replace(output)
    # Prefixed with the folder: split reports reuse names such as 01_ULTF-01.pdf in channel, pen and message.
    (settings.logs / f"{output.parent.name}_{output.name}.txt").write_text(text, encoding="utf-8")
    if evidence.get("deselectedChannelsInMessages"):
        log("messageScopeWarning", dict(channels=evidence["deselectedChannelsInMessages"],
                                        reason="Reviewer scopes messages to the source group, not the selected channels"))
    log("pdfVerified", result)
    return result
