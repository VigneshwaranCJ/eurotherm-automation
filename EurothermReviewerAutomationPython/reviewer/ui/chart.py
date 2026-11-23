from ..common.errors import WorkflowError
from ..common.time import utc_time
from .groups import group_card
from ..ranges import require_data

LOADED = """() => {
    const e=document.querySelector('#testAuto_chartdisplay_print');
    if(!e) return false;
    const s=window.angular.element(e).scope();
    return !s.chartDataLoading && !s.navigatorDataLoading;
}"""
PICKER_VALUE = "e => window.jQuery(e).find('.date').data('DateTimePicker').date().toISOString()"


def select_date(picker, stamp):
    picker.evaluate("""(e,stamp)=>{
        const p=window.jQuery(e).find('.date').data('DateTimePicker');
        if(!p) throw new Error('Reviewer date picker is not initialized');
        const scope=window.angular.element(e).isolateScope(), m=window.moment.utc(stamp);
        if(scope.chartSettings?.dateSettings) m.utcOffset(window.moment.calculateOffset(m,scope.chartSettings.dateSettings));
        p.show();p.date(m);p.hide();
    }""", stamp)


def open_chart(page, group, interval, settings, log, run_id):
    require_data(group, interval)
    with page.expect_response(lambda r: r.url.endswith("/api/groupsamples") and r.status == 200, timeout=90000):
        group_card(page, group).click()
    page.wait_for_url("**/#/visualizer?**", timeout=90000)
    if "chartType=linear" not in page.url:
        raise WorkflowError("CHART_LOAD_FAILED", "Selected chart is not linear")
    page.wait_for_function("() => window.jQuery('date-picker-start .date').data('DateTimePicker') && window.jQuery('date-picker-end .date').data('DateTimePicker')", timeout=90000)
    dates = page.locator("date-picker-start:visible,date-picker-end:visible")
    if dates.count() != 2:
        raise WorkflowError("CHART_LOAD_FAILED", "Expected two live chart date controls")
    start, end = interval["start"], interval["end"]
    def matches(response, match_end=False):
        if not response.url.endswith("/api/groupsamples") or response.status != 200:
            return False
        query = response.request.post_data_json
        return utc_time(query["start"]) == utc_time(start) and (not match_end or utc_time(query["end"]) == utc_time(end))
    with page.expect_response(matches, timeout=120000) as pending:
        select_date(dates.nth(0), start)
    data = pending.value.json()
    page.wait_for_function(LOADED, timeout=120000)
    if utc_time(dates.nth(1).evaluate(PICKER_VALUE)) != utc_time(end):
        with page.expect_response(lambda r: matches(r, True), timeout=120000) as pending:
            select_date(dates.nth(1), end)
        data = pending.value.json()
    channels = (data.get("groupSample") or {}).get("channels", [])
    if not any(c.get("dataPoints") for c in channels):
        raise WorkflowError("MISSING_DATA", "Selected interval has no measurement samples")
    page.wait_for_function(LOADED, timeout=120000)
    opened = page.locator("#testAuto_chartdisplay_print").evaluate("e => window.angular.element(e).scope().chartSettings.group")
    if opened != group["groupId"]:
        raise WorkflowError("CHART_LOAD_FAILED", f"Chart opened {opened!r} instead of the selected record {group['groupId']!r}")
    accepted = [dates.nth(i).evaluate(PICKER_VALUE) for i in range(2)]
    if [utc_time(s) for s in accepted] != [utc_time(start), utc_time(end)]:
        raise WorkflowError("CHART_LOAD_FAILED", "Chart dates changed from the requested interval")
    all_selected = page.locator("#testAuto_chartdisplay_print").evaluate("e => window.angular.element(e).scope().chartSettings.channelStatuses.allSelected")
    if not all_selected:
        page.get_by_text("Show/Hide All", exact=True).click()
    if not page.locator("svg:visible,canvas:visible").count():
        raise WorkflowError("CHART_LOAD_FAILED", "No visible chart graphic rendered")
    log("chart", dict(url=page.url, start=start, end=end, channels=[dict(name=c["channelName"], units=c.get("units"), points=len(c.get("dataPoints", []))) for c in channels]))
    page.screenshot(path=str(settings.screenshots / f"chart-{run_id}.png"), full_page=True)
    return dict(start=start, end=end, channels=channels,
                displayStart=dates.nth(0).locator("input").input_value(),
                displayEnd=dates.nth(1).locator("input").input_value())
