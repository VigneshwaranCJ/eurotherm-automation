"""Native print controls and accepted-settings verification."""



def set_custom_check(locator, wanted):
    if bool(locator.locator(".fa-check").count()) != wanted:
        locator.click()
    if bool(locator.locator(".fa-check").count()) != wanted:
        raise RuntimeError("Reviewer checkbox did not accept requested state")


def configure_print(page, settings, log):
    page.locator("#testAuto_chartdisplay_print").click()
    page.locator("#testAuto_print_page_title").wait_for()
    page.locator("#testAuto_cps_paperSize:visible").select_option(label=settings.paper)
    page.locator("#testAuto_cps_chartTitle:visible").fill(settings.title)
    for selector, wanted in (
        ("#testAuto_cps_includeValues:visible", settings.include_values),
        ("#testAuto_cps_includeChart:visible", settings.include_chart),
        ("#testAuto_cps_includeMessages:visible", settings.include_messages),
        ('check-selector[ng-model="settings.includeMessagesSeperately"]:visible', settings.separate_messages),
        ('check-selector[ng-model="settings.includeCursorStats"]:visible', settings.cursor_statistics),
    ):
        set_custom_check(page.locator(selector), wanted)
    if settings.include_values:
        page.locator('select[ng-model="sampleIntervals.sampleInterval"]:visible').select_option(label="Raw Data")
    expected = dict(paperSize={"A4": "0", "A3": "1", "Letter": "2", "Ledger": "4"}[settings.paper],
                    chartTitle=settings.title, includeValues=settings.include_values, includeChart=settings.include_chart,
                    includeMessages=settings.include_messages, includeMessagesSeperately=settings.separate_messages,
                    includeCursorStats=settings.cursor_statistics)
    # Reviewer hides the time-axis and gridline controls when no chart is included.
    if settings.include_chart:
        if not page.locator("#testAuto_cps_fitToPages:visible .fa-circle").count():
            page.locator("#testAuto_cps_fitToPages:visible").click()
        page.locator('select[ng-model="settings.fitToPagesUnits"]:visible').select_option("pages")
        page.locator("#testAuto_fitToPages_value:visible").fill(str(settings.pages))
        page.locator("#testAuto_majorGridLine:visible").fill(str(settings.major))
        page.locator("#testAuto_minorGridLine:visible").fill(str(settings.minor))
        expected.update(fitToPages=True, fitToPagesLength=settings.pages, fitToPagesUnits="pages", useFixedScaling=False,
                        numMajorGridLines=settings.major, numMinorGridLines=settings.minor)
    if settings.include_values:
        expected['valuesTableSampleInterval'] = 0
    accepted = page.locator("#testAuto_cps_chartTitle:visible").evaluate("""(e,keys) => {
        const s=window.angular.element(e).scope().settings;
        return Object.fromEntries(keys.map(k=>[k,s[k]]));
    }""", list(expected))
    for key, value in expected.items():
        if type(accepted.get(key)) is not type(value) or accepted[key] != value:
            raise RuntimeError(f"Print setting mismatch: {key} (wanted {value!r}, got {accepted.get(key)!r})")
    log("printSettings", accepted)
