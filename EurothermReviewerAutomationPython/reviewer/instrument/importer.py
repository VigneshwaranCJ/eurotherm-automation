"""Authorized single-file upload and persistent attempt journal."""
import hashlib
import json
import os
import re
from ..config import ROOT
from ..common.errors import WorkflowError
from ..common.time import now_iso
from .validation import validate_file
from ..ui.status import reviewer_status, assert_reviewer_ready
from ..health.readiness import readiness_issues


def assert_import_authorized(dry_run, authorization, sha, uncertain):
    if uncertain:
        raise RuntimeError("Import state uncertain: submission is prohibited")
    if dry_run:
        raise RuntimeError("DRY_RUN=true: file selection would auto-submit; no file selected")
    if authorization != sha:
        raise RuntimeError("Separate explicit single-file import authorization required: --authorize-import=<verified SHA-256>")


def import_single_file(page, settings, sha, uncertain, authorization, log):
    # Process-level safeguard for testing; child runs inherit it and no authorization overrides it.
    if os.environ.get("REVIEWER_BLOCK_IMPORTS", "").lower() == "true":
        raise WorkflowError("IMPORTS_BLOCKED", "REVIEWER_BLOCK_IMPORTS=true: no file was selected or submitted")
    assert_import_authorized(settings.dry_run, authorization, sha, uncertain)
    status = reviewer_status(page)
    assert_reviewer_ready(status)
    if readiness_issues(status):
        raise RuntimeError("Import readiness failed")
    if validate_file(settings.file)["sha256"] != sha:
        raise RuntimeError("UHH changed since import authorization; no submission allowed")
    payload = settings.file.read_bytes()
    if hashlib.sha256(payload).hexdigest() != sha:
        raise RuntimeError("UHH upload content changed; no submission allowed")
    local_intent = settings.temp / f"import-{sha}.json"
    reference_intent = ROOT.parent / "EurothermReviewerAutomation" / ".tmp" / local_intent.name
    if local_intent.exists() or reference_intent.exists():
        raise RuntimeError("A previous import attempt exists; reconcile its result manually before resubmitting")
    # Share the reference's intent journal when it is present, so either CLI sees an interrupted submission.
    intent = reference_intent if reference_intent.parent.is_dir() else local_intent
    page.locator("#testAuto_topMenu_importUHHFiles").click()
    control = page.locator("#dropfilehere")
    control.wait_for(state="attached")
    with intent.open("x", encoding="utf-8") as stream:
        json.dump(dict(sha=sha, file=str(settings.file), state="pending", time=now_iso()), stream)
    submitted = False
    def guard(route):
        nonlocal submitted
        body = route.request.post_data_buffer or b""
        names = re.findall(rb'filename="([^"]+)"', body)
        selected = control.evaluate("e => Array.from(e.files).map(f => f.name)")
        if not submitted and names == [settings.file.name.encode("utf-8")] and selected == [settings.file.name]:
            submitted = True
            route.continue_()
        else:
            route.abort()
    page.route("**/api/imports/progress", guard)
    try:
        with page.expect_response(lambda r: r.url.endswith("/api/imports/progress"), timeout=180000) as pending:
            control.set_input_files(dict(name=settings.file.name, mimeType="application/octet-stream", buffer=payload))
        response = pending.value
        text = response.text()
        (settings.logs / f"import-{sha}.txt").write_text(text, encoding="utf-8")
        if not response.ok or "FileLoadComplete" not in text:
            raise RuntimeError("Import was not confirmed successful; no automatic resubmission")
        if re.search(r"DuplicateDataImport|FileLoadCompleteNoData|FileLoadCompleteButCorrupted|FileLoadCompleteOneTimeStamp", text):
            raise RuntimeError("Import returned duplicate, no-data, or incomplete-data status; review native log")
        intent.write_text(json.dumps(dict(sha=sha, file=str(settings.file), state="native-complete", time=now_iso())), encoding="utf-8")
        log("importNativeComplete", {"sha": sha})
    finally:
        page.unroute("**/api/imports/progress", guard)
