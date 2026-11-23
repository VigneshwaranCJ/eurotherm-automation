"""Command-specific orchestration of domain operations."""
from ..common.errors import WorkflowError
from .commands import should_import, should_download
from ..ui.chart import open_chart
from ..ui.sources import inspect_sources
from ..ui.status import reviewer_status, assert_reviewer_ready
from ..ui.groups import all_groups
from ..ui.batches import inspect_batches
from ..health.preflight import run_preflight
from ..ranges import configured_interval, verify_import_interval
from ..reports.settings import configure_print
from ..reports.preview import validate_preview
from ..reports.pdf import download_pdf
from ..instrument.metadata import read_interval
from ..instrument.identity import select_group
from ..instrument.duplicates import import_evidence, check_duplicate
from ..instrument.importer import import_single_file


def execute(command, settings, authorization, log, run_id, page):
    if command == "discover":
        log("navigation", dict(url=page.url, text=page.locator("body").inner_text()))
        page.locator("#testAuto_topMenu_importUHHFiles").click()
        page.locator("#dropfilehere").wait_for(state="attached")
        log("importInterface", dict(type=page.locator("#dropfilehere").get_attribute("type"), autoSubmitsOnSelection=True))
        page.screenshot(path=str(settings.screenshots / f"discovery-{run_id}.png"), full_page=True)
        return
    sources = inspect_sources(page, settings, log, run_id)
    if command == "datasources":
        return
    metadata = read_interval(settings)
    log("uhhMetadata", metadata)
    groups = all_groups(page)
    log("groups", dict(count=len(groups)))
    evidence = import_evidence(groups, metadata, settings.file)
    log("importEvidence", dict(status=evidence["status"], groupId=evidence.get("group", {}).get("groupId"), archive=evidence.get("archive")))
    if should_import(command, evidence["status"]):
        if command != "import:test":  # An import-only command requests no report dates.
            verify_import_interval(page, settings, metadata, groups, log)
        import_single_file(page, settings, authorization["sha"], evidence["status"] == "uncertain", authorization["token"], log)
        groups = all_groups(page)
    group = select_group(groups, metadata, settings.group)
    log("groupMatched", dict(id=group["groupId"], name=group["groupName"], instrument=group["instrument"], start=group["dataStart"], end=group["dataEnd"]))
    duplicate = check_duplicate(group, settings.file)
    log("duplicateCheck", duplicate)
    if command == "import:test":
        if duplicate["status"] == "already-imported":
            log("importSkipped", dict(reason="Exact archived content already exists"))
            return
        raise RuntimeError("Native completion did not produce a verified archive match; do not resubmit")
    if duplicate["status"] != "already-imported":
        raise RuntimeError("Cannot report from an unverified import")
    configured = configured_interval(settings.start, settings.end) if settings.range_mode == "env" else None
    interval = run_preflight(page, group, groups, metadata, sources, settings, log, run_id, configured)
    if command == "diagnostics":
        log("diagnosticsComplete", dict(chartRequested=False, pdfDownloaded=False))
        return
    all_groups(page)
    inspect_batches(page, group, metadata, settings, log)
    assert_reviewer_ready(reviewer_status(page))
    chart = open_chart(page, group, interval, settings, log, run_id)
    configure_print(page, settings, log)
    validate_preview(page, group, chart, settings, log, run_id)
    if should_download(command, settings.dry_run):
        try:
            download_pdf(page, group, chart, settings, log)
        except Exception as error:
            raise WorkflowError("PDF_DOWNLOAD_FAILED", str(error)) from error
    else:
        log("dryRunComplete", dict(pdfDownloaded=False, instrumentDataModified=False))
