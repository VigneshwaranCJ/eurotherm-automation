"""A local stand-in for Reviewer's UI and API, matching behavior observed on the live application.

Used by the integration tests with real Chrome and real PDFs. It never contacts Reviewer.
Modelled behaviors: Reviewer remembers the Custom tab, overlapping record names, Show/Hide
Channel rows without .fa-check, hidden time-axis controls when charts are off, Virtual
Instrument headers on message-only Custom reports, and pageCheck always answering 1.
"""
import json
from html import escape
from urllib.parse import parse_qs, urlparse

BASE = "https://reviewer.test/"
INSTRUMENT = dict(instrumentName="SLS-GL-EUT-01", macAddress="000A8D820FF9")
CHANNELS = ["ULTF-01"] + [f"CH-{i:02d}" for i in range(2, 36)]
START, END = "2026-11-02T18:30:00.000Z", "2026-11-03T18:30:00.000Z"
SELECTED, DESELECTED = CHANNELS[:25], CHANNELS[25:]


def record(name, group_id, channels=CHANNELS, custom=True):
    return dict(groupId=group_id, groupName=name, instrument=INSTRUMENT, isCustomGroup=custom, channels=channels,
                dataStart="2025-12-25T05:50:00", dataEnd="2026-11-04T04:18:00", timezoneOffset=19800000, daylightSavings=None)


RECORDS = [record("EUT-01", "id-eut"), record("SLS733(EUT-01)", "id-733"), record("SLS525(EUT-01)", "id-525", CHANNELS[:33])]
NORMAL = [record("Group 1", "id-group", custom=False)]
TITLES = {"graph": "SLS733(EUT-01) - graph", "pen-log": "SLS733(EUT-01) - pen-log", "message-log": "SLS733(EUT-01) - message-log"}


def token(name):
    return f"{CHANNELS.index(name) + 1}(2) {name}"


def message_lines(selected=SELECTED, deselected=DESELECTED):
    """A selected alarm, an alarm mixing selected and deselected channels, and a login with no channel."""
    mixed = " ".join(token(n) for n in list(selected[:2]) + list(deselected[:2]))
    return [f"03/11/2026 02:08:20 Alarm(s) on {token(selected[0])}", f"03/11/2026 04:57:16 Alarm(s) on {mixed}",
            "03/11/2026 09:56:18 Login by (192.0.2.1)operator"]


def api_messages():
    kinds = (2, 3, 18)
    return [dict(content=line, created=f"2026-11-02T20:38:2{i}", messageType=kinds[i], group=0)
            for i, line in enumerate(message_lines())]


def report_html(profile, group="SLS733(EUT-01)", instrument=None, selected=SELECTED, deselected=DESELECTED, **fault):
    """Render a report with Reviewer's layout. Fault arguments create specific defects."""
    instrument = instrument or ("Virtual Instrument" if profile == "message-log" else INSTRUMENT["instrumentName"])
    title = fault.get("title", TITLES[profile])
    columns = list(selected) + list(fault.get("extra_columns", ()))
    legend = " ".join(selected)
    cursor = "<h3>Cursor Statistics</h3><p>Cursor Position 00:00:00.000 04/11/2026</p>" + "".join(f"<p>■ {escape(n)} (°C) 1.5</p>" for n in columns)
    rows = "".join(f"<tr><td>{h:02d}:00:00.000 03/11/2026</td>" + "<td>1.5</td>" * 3 + "</tr>" for h in range(4))
    table = f"<table><tr><th>Date/Time</th>{''.join(f'<th>■ {escape(n)} (°C)</th>' for n in columns)}</tr>{rows}</table>"
    message_day = fault.get("message_day", "03/11/2026")
    lines = [line.replace("03/11/2026", message_day, 1) if index == 0 else line
             for index, line in enumerate(message_lines(selected, deselected))]
    messages =("" if fault.get("no_heading") else "<h3>Messages</h3>") + "".join(f"<p>{escape(l)}</p>" for l in lines)
    chart = f"<svg width='300' height='60'><rect width='300' height='60' fill='#eee'/></svg><p>{escape(legend)}</p>"
    if profile == "graph":
        bodies = [chart, cursor]
    elif profile == "pen-log":
        bodies = [chart, cursor, table, messages]
    else:
        bodies = [messages]
    if fault.get("graph_mentions_deselected"):
        bodies[0] += f"<p>{escape(deselected[0])}</p>"
    total = fault.get("claimed_total", len(bodies))
    pages = []
    start, end = fault.get("start", "00:00:00.000 03/11/2026"), fault.get("end", "00:00:00.000 04/11/2026")
    for number, body in enumerate(bodies, 1):
        footer = "" if fault.get("no_footer") else f"Chart Speed: fit to 1 pages <span>{number}/{total}</span>"
        pages.append(f"<section class='page'><div>Instrument: {escape(instrument)}, Group: {escape(group)}</div>"
                     f"<div>{escape(title)}</div>{body}<div>{start} Time of print: 11:35:55 06/11/2026 {end}</div>"
                     f"<div>Instrument Id: Virtual Instrument | Printed by user: autologin</div><div>{footer}</div></section>")
    return "<style>.page{page-break-after:always;font:9px sans-serif}.page:last-child{page-break-after:auto}table{font-size:6px}</style>" + "".join(pages)


APP = r"""<!doctype html><title>Reviewer stub</title>
<style>.hidden{display:none} check-selector,date-picker-start,date-picker-end{display:block}</style>
<button id="testAuto_topMenu_groupsAndBatches">Groups and Batches</button>
<button id="testAuto_topMenu_dateSources">Data Sources</button>
<div id="groups" class="hidden"><button id="loadNormalGroups">Groups</button><button id="loadCustomGroups">Custom</button>
  <button id="toggle">Filters</button><div id="filter" class="hidden"><date-picker-filter><span class="date"></span></date-picker-filter><span id="close">Close</span></div>
  <div id="cards"></div></div>
<div id="chart" class="hidden">
  <date-picker-start><span class="date"></span><input></date-picker-start><date-picker-end><span class="date"></span><input></date-picker-end>
  <svg width="200" height="50"></svg><span>Show/Hide All</span>
  <div class="channel-list" id="rows"></div>
  <button id="testAuto_chartdisplay_print">Print</button>
  <div id="print" class="hidden"><div id="testAuto_print_page_title">Print</div>
    <select id="testAuto_cps_paperSize"><option value="1">A3</option><option value="0">A4</option><option value="2">Letter</option><option value="4">Ledger</option></select>
    <input id="testAuto_cps_chartTitle">
    <check-selector id="testAuto_cps_includeValues" data-key="includeValues">values</check-selector>
    <check-selector id="testAuto_cps_includeChart" data-key="includeChart">chart</check-selector>
    <check-selector id="testAuto_cps_includeMessages" data-key="includeMessages">messages</check-selector>
    <check-selector ng-model="settings.includeMessagesSeperately" data-key="includeMessagesSeperately">separate</check-selector>
    <check-selector ng-model="settings.includeCursorStats" data-key="includeCursorStats">cursor</check-selector>
    <select id="interval" ng-model="sampleIntervals.sampleInterval"><option>Raw Data</option></select>
    <div id="axis"><div id="testAuto_cps_fitToPages"><i class="fa-circle"></i>fit</div>
      <select ng-model="settings.fitToPagesUnits"><option value="pages">pages</option></select>
      <input id="testAuto_fitToPages_value"><input id="testAuto_majorGridLine"><input id="testAuto_minorGridLine"></div>
    <button id="preview">Preview</button><button id="download">Download PDF</button>
    <iframe id="previewWindow" title="preview"></iframe></div>
</div>
<script>
const $ = s => document.querySelector(s), config = window.__config;
const scope = { chartDataLoading:false, navigatorDataLoading:false, chartSettings:{group:null, channelStatuses:{allSelected:true}},
  settings:{paperSize:"1", chartTitle:"", includeValues:true, includeChart:true, includeMessages:true, includeMessagesSeperately:false, includeCursorStats:false,
            fitToPages:true, fitToPagesLength:1, fitToPagesUnits:"pages", useFixedScaling:false, numMajorGridLines:5, numMinorGridLines:5, valuesTableSampleInterval:0} };
const http = {post: (url, body) => fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}).then(async r => ({data:await r.json()}))};
const injector = {get: name => name === '$http' ? http : {api:'/api/'}};
window.angular = {element: e => ({scope: () => e.closest && e.closest('.box-body') ? {card:e.closest('.box-body').__card} : scope, isolateScope: () => ({chartSettings:{}}), injector: () => injector})};
const moment = s => ({value:new Date(s).toISOString(), toISOString(){return this.value}});
window.moment = Object.assign(moment, {utc: moment});
const wrap = list => ({first: () => wrap(list.slice(0,1)), find: s => wrap(list.flatMap(e => [...e.querySelectorAll(s)])), data: () => list[0]?.__picker});
window.jQuery = x => wrap(typeof x === 'string' ? [...document.querySelectorAll(x)] : [x]);
const post = (path, body) => fetch('/api/' + path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
let tab = config.rememberedTab;
const render = groups => { $('#cards').replaceChildren(...groups.map(g => { const d = document.createElement('div'); d.className = 'box-body'; d.__card = g;
    d.textContent = `${g.groupName} [${g.instrument.instrumentName} - 8523769] Data available`; d.onclick = () => openChart(g); return d; })); };
const load = async start => render((await (await post(tab === 'custom' ? 'groups/custom/filters' : 'groups/filters', {start})).json()).groups);
const show = id => ['groups','chart'].forEach(v => $('#'+v).classList.toggle('hidden', v !== id));
$('#testAuto_topMenu_dateSources').onclick = () => { location.hash = '#/datasources'; show(''); };
$('#testAuto_topMenu_groupsAndBatches').onclick = () => { location.hash = '#/groups'; show('groups'); load('2026-11-01T00:00:00Z'); };
const select = name => { tab = name; $('#loadCustomGroups').classList.toggle('btn-selected', name === 'custom'); load('2026-11-01T00:00:00Z'); };
$('#loadNormalGroups').onclick = () => select('normal'); $('#loadCustomGroups').onclick = () => select('custom');
$('#toggle').onclick = () => $('#filter').classList.remove('hidden'); $('#close').onclick = () => $('#filter').classList.add('hidden');
$('date-picker-filter .date').__picker = {show(){}, hide(){}, date(v){ load(v.toISOString()); }};
const pad = (v, n=2) => String(v).padStart(n, '0');
const display = iso => { const d = new Date(new Date(iso).getTime() + 19800000);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}.${pad(d.getUTCMilliseconds(),3)} ${pad(d.getUTCDate())}/${pad(d.getUTCMonth()+1)}/${d.getUTCFullYear()} +05:30`; };
let range = {start:'2026-11-01T00:00:00.000Z', end:'2026-11-04T04:18:00.000Z'}, current;
const picker = (selector, key) => { const box = $(selector), input = box.querySelector('input'); input.value = display(range[key]);
  box.querySelector('.date').__picker = {show(){}, hide(){}, date(v){ if (!v) return moment(range[key]); range[key] = v.toISOString(); input.value = display(range[key]);
    post('groupsamples', {groupId:current.groupId, start:range.start, end:range.end}); }}; };
picker('date-picker-start','start'); picker('date-picker-end','end');
function openChart(group) { current = group; post('groupsamples', {groupId:group.groupId, start:range.start, end:range.end});
  location.hash = `#/visualizer?chartType=linear&groupId=${group.groupId}`; show('chart');
  scope.chartSettings.group = config.wrongChart ? 'id-other' : group.groupId;
  scope.chartSettings.channelStatuses = {allSelected:true};
  $('#rows').replaceChildren(...group.channels.map(name => { const id = 'uid-' + name; scope.chartSettings.channelStatuses[id] = {selected:true};
    const row = document.createElement('div'); row.setAttribute('ng-repeat', 'channel in channels');
    row.innerHTML = '<div class="channel-options"><div title="Show/Hide Channel"><i class="fa fa-line-chart">chart</i></div></div><div class="channel-name"><div></div> (units)</div>';
    row.querySelector('.channel-name div').textContent = name;
    row.querySelector('[title]').onclick = () => { if (!config.ignoreToggle?.includes(name)) scope.chartSettings.channelStatuses[id].selected = !scope.chartSettings.channelStatuses[id].selected; };
    return row; })); }
const refresh = () => { document.querySelectorAll('check-selector').forEach(c => { const on = scope.settings[c.dataset.key]; const i = c.querySelector('.fa-check');
    if (on && !i) { const m = document.createElement('i'); m.className = 'fa-check'; c.append(m); } if (!on && i) i.remove(); });
  $('#axis').classList.toggle('hidden', !scope.settings.includeChart); };
document.querySelectorAll('check-selector').forEach(c => c.onclick = () => { const s = scope.settings, k = c.dataset.key; s[k] = !s[k];
  if (s.includeMessages && !s.includeChart) s.includeMessagesSeperately = true; if (!s.includeMessages) s.includeMessagesSeperately = false; refresh(); });
$('#testAuto_chartdisplay_print').onclick = () => { $('#print').classList.remove('hidden'); refresh(); };
$('#testAuto_cps_paperSize').onchange = e => scope.settings.paperSize = e.target.value;
$('#testAuto_cps_chartTitle').oninput = e => scope.settings.chartTitle = e.target.value;
$('#testAuto_fitToPages_value').oninput = e => scope.settings.fitToPagesLength = +e.target.value;
$('#testAuto_majorGridLine').oninput = e => scope.settings.numMajorGridLines = +e.target.value;
$('#testAuto_minorGridLine').oninput = e => scope.settings.numMinorGridLines = +e.target.value;
const profile = () => scope.settings.includeChart ? (scope.settings.includeValues ? 'pen-log' : 'graph') : 'message-log';
// Reports may be keyed "profile|channel,..." for the channels currently shown; otherwise by profile alone.
const shown = () => Object.entries(scope.chartSettings.channelStatuses).filter(([k, v]) => k !== 'allSelected' && v.selected).map(([k]) => k.slice(4)).join(',');
const reportKey = () => { const k = profile() + '|' + shown(); return k in window.__previews ? k : profile(); };
$('#preview').onclick = async () => { await post('groupsamples/pageCheck', {}); await post('groupsamples/preview', {}); if (config.blankPreview) return; $('#previewWindow').srcdoc = window.__previews[reportKey()]; };
$('#download').onclick = async () => { const blob = await (await fetch('/download.pdf?profile=' + encodeURIComponent(reportKey()))).blob();
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'native.pdf'; a.click(); };
location.hash = '#/groups'; show('groups');
</script>"""


class ReviewerStub:
    """Serve the stub through Playwright routing and record API traffic."""

    def __init__(self, page, pdfs, previews=None, channels=None, messages=None, remembered_tab="custom", **config):
        self.requests = []
        self.messages = api_messages() if messages is None else messages
        self.page = page
        self.pdfs = pdfs
        self.channels = channels
        page.add_init_script(f"window.__config={json.dumps(dict(config, rememberedTab=remembered_tab))};"
                             f"window.__previews={json.dumps(previews or {})};")
        page.route(BASE + "**", self.handle)
        page.goto(BASE)
        page.locator("#testAuto_topMenu_dateSources").click()

    def handle(self, route):
        request = route.request
        path = urlparse(request.url).path
        self.requests.append(path)
        if path == "/":
            return route.fulfill(content_type="text/html", body=APP)
        if path == "/api/groups/custom/filters":
            return route.fulfill(json=dict(totalCount=len(RECORDS), groups=RECORDS))
        if path == "/api/groups/filters":
            return route.fulfill(json=dict(totalCount=len(NORMAL), groups=NORMAL))
        if path == "/api/groupsamples":
            group = next(g for g in RECORDS + NORMAL if g["groupId"] == request.post_data_json["groupId"])
            sampled = self.channels or (lambda name: [1, 2])
            return route.fulfill(json=dict(groupSample=dict(
                messages=self.messages if request.post_data_json.get("includeMessages") else [],
                channels=[dict(channelName=n, channelNumber=CHANNELS.index(n) + 1, channelUniqueId="uid-" + n, units="C", dataPoints=sampled(n))
                          for n in group["channels"]])))
        if path == "/api/groupsamples/pageCheck":
            return route.fulfill(json=1)  # Observed on live Reviewer even for a 199-page report.
        if path == "/api/groupsamples/preview":
            return route.fulfill(json={})
        if path == "/download.pdf":
            profile = parse_qs(urlparse(request.url).query)["profile"][0]
            return route.fulfill(body=self.pdfs[profile], content_type="application/pdf")
        return route.fulfill(status=404, body="not found")
