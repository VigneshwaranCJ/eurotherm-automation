"""Run lifecycle, locks, browser cleanup and failure evidence."""
from contextlib import ExitStack
import traceback
from urllib.parse import urlparse
from ..config import ROOT
from ..common.errors import WorkflowError
from ..common.logging import create_logger
from ..common.time import now_iso
from ..common.locking import run_lock
from ..ui.browser import open_reviewer
from ..instrument.validation import validate_file
from ..ranges import configured_interval
from .workflow import execute


def run_command(command, settings, authorization=None, pipeline_config=None, on_event=None):
    pipeline = command.startswith('workflow:')
    if pipeline:
        from ..pipeline.runner import prepare_pipeline, execute_pipeline
        if pipeline_config is None:
            config, settings = prepare_pipeline(settings)
        else:
            config = pipeline_config
    settings.prepare()
    run_id = now_iso().replace(":", "-").replace(".", "-")
    log = create_logger(settings.logs, run_id, mirror='execution.log' if settings.recording_date else None, observer=on_event)
    with ExitStack() as stack:
        page = None
        try:
            stack.enter_context(run_lock(settings.temp / "automation.lock"))
            # Also acquire the reference lock so the projects cannot drive Reviewer together.
            reference_temp = ROOT.parent / "EurothermReviewerAutomation" / ".tmp"
            if reference_temp.is_dir() and reference_temp.resolve() != settings.temp.resolve():
                stack.enter_context(run_lock(reference_temp / "automation.lock"))
            log("start", dict(command=command, runId=run_id, root=str(ROOT), dryRun=settings.dry_run, reportMode=settings.range_mode, reportTitle=settings.title))
            file = validate_file(settings.file)
            log("fileVerified", file)
            if command == "file:check":
                log("complete", dict(command=command))
                return
            if settings.range_mode == "env":
                configured_interval(settings.start, settings.end)
            try:
                page = stack.enter_context(open_reviewer(settings))
            except Exception as error:
                raise WorkflowError("APPLICATION_UNAVAILABLE", str(error)) from error
            page.on("pageerror", lambda e: log("applicationError", dict(message=str(e))))
            page.on("console", lambda m: log("browserError", dict(message=m.text)) if m.type == "error" else None)
            page.on("response", lambda r: log("httpError", dict(status=r.status, path=urlparse(r.url).path)) if r.status >= 400 else None)
            log("applicationAccessible", dict(url=page.url))
            if pipeline:
                result = execute_pipeline(command, settings, config, dict(sha=file['sha256'], token=authorization), log, run_id, page)
            else:
                execute(command, settings, dict(sha=file["sha256"], token=authorization), log, run_id, page)
            log("complete", dict(command=command))
            return result if pipeline else None
        except Exception as error:
            log("failure", dict(code=getattr(error, "code", "WORKFLOW_FAILED"), message=str(error),
                                details=getattr(error, "details", None), stack=traceback.format_exc(), url=page.url if page else None))
            if page:
                try:
                    page.screenshot(path=str(settings.screenshots / f"{run_id}-failure.png"), full_page=True)
                    (settings.logs / f"{run_id}-failure.html").write_text(page.content(), encoding="utf-8")
                except Exception as capture_error:
                    log("failureCaptureError", dict(message=str(capture_error)))
            raise
