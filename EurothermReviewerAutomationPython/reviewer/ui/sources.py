"""Native instrument network and transfer status (diagnostic only)."""
from playwright.sync_api import TimeoutError as PlaywrightTimeout

SOURCES_TIMEOUT = 30000


def inspect_sources(page, settings, log, run_id):
    """Read the Data Sources cards for the transfer-age warning.

    Nothing depends on this list except that warning, so when Reviewer shows an empty
    page (observed on the live system) the run records a warning and continues.
    """
    page.locator("#testAuto_topMenu_dateSources").click()
    page.wait_for_url("**/#/datasources")
    try:
        page.wait_for_function("() => document.querySelectorAll('[ng-repeat]').length > 0", timeout=SOURCES_TIMEOUT)
        page.wait_for_function("() => document.body.innerText.includes('Last file transfer')", timeout=SOURCES_TIMEOUT)
    except PlaywrightTimeout:
        log("preflightWarning", dict(code="DATA_SOURCES_UNAVAILABLE",
                                     message="Reviewer's Data Sources page listed no instruments; transfer age was not checked"))
        page.screenshot(path=str(settings.screenshots / f"data-sources-{run_id}.png"), full_page=True)
        return []
    instruments = page.locator(".box-container[ng-repeat]").evaluate_all("""es => es
        .map(e=>window.angular.element(e).scope()?.card).filter(c=>c?.instrumentName)
        .map(c=>({name:c.instrumentName,address:c.netAddress,pullServiceRunning:c.collectIsRunning,
            networkOnline:c.serverIsOnline,lastFileTransfer:c.lastFileTransferTime}))""")
    log("dataSources", dict(instruments=instruments, text=page.locator("body").inner_text()))
    page.screenshot(path=str(settings.screenshots / f"data-sources-{run_id}.png"), full_page=True)
    return instruments
