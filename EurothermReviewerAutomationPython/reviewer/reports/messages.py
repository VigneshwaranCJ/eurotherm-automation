"""Native message retrieval and a clearly labelled supplementary list for selected channels.

Reviewer cannot filter messages by channel. The native PDF is never altered; this module
writes a separate derived CSV holding only alarm entries whose channel can be proven.
"""
import csv
import hashlib
import io
import re

from ..common.time import now_iso

SKIPPED_NO_MESSAGES = "SKIPPED_NO_MESSAGES"
# Reviewer's message types for alarms (settings.allMessageTypes, group "alarms").
ALARM_TYPES = frozenset({2, 3, 4, 5, 6, 7, 8, 9, 10, 23})
ALL_TYPES = list(range(25))
ALARM_LINE = re.compile(r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})\s+Alarm\(s\)\s+(on|off|Ack'd)\s+(\S.*?)\s*$")
CHANNEL_TOKEN = re.compile(r"(?:^|(?<=\s))(\d+)\((\d+)\)\s+")
FORMULA_PREFIX = ("=", "+", "-", "@")
NOTICE = "SUPPLEMENTARY - NOT A NATIVE EUROTHERM REVIEWER REPORT"

FETCH = """body => new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Reviewer message query timed out')), 120000);
    const injector = window.angular.element(document.body).injector();
    injector.get('$http').post(injector.get('configuration').api + 'groupsamples', body).then(
        response => { clearTimeout(timer); resolve(response.data.groupSample); },
        () => { clearTimeout(timer); reject(new Error('Reviewer message query failed')); });
})"""


def fetch_messages(page, group, interval):
    """Ask Reviewer for this interval's messages the way its own message view does (read-only)."""
    types = [int(value) for value in group.get("messageTypes") or ALL_TYPES]
    sample = page.evaluate(FETCH, dict(groupId=group["groupId"], start=interval["start"], end=interval["end"],
                                       numberOfPoints=2, messageTypes=types, includeMessages=True,
                                       includeValues=True, sampleInterval=0))
    if not isinstance(sample, dict) or not isinstance(sample.get("messages"), list):
        raise RuntimeError("Reviewer returned no readable message list")
    return sample["messages"], sample.get("channels") or []


def parse_alarm(content):
    """Split a native alarm line into (time, state, [(number, alarm, name)]), or None if not exact."""
    line = ALARM_LINE.match(content or "")
    if not line:
        return None
    body = line[3]
    tokens = list(CHANNEL_TOKEN.finditer(body))
    if not tokens or tokens[0].start() != 0:
        return None
    channels = []
    for index, token in enumerate(tokens):
        end = tokens[index + 1].start() if index + 1 < len(tokens) else len(body)
        name = body[token.end():end].strip()
        if not name:
            return None
        channels.append((int(token[1]), int(token[2]), name))
    return line[1], line[2], channels


def classify_messages(messages, channels, selected):
    """Keep an entry only when a selected channel's number and exact name are both proven."""
    known = {(int(c["channelNumber"]), c["channelName"]) for c in channels if c.get("channelNumber") is not None}
    wanted = {pair for pair in known if pair[1] in set(selected)}
    selected_names = set(selected)
    rows = []
    counts = dict(total=len(messages), included=0, excludedNoChannel=0, excludedDeselectedOnly=0, excludedUnreliable=0)
    for message in messages:
        kind, content = message.get("messageType"), message.get("content", "")
        if kind not in ALARM_TYPES:
            counts["excludedNoChannel"] += 1
            continue
        parsed = parse_alarm(content)
        if parsed is None or any(name in selected_names and (number, name) not in wanted for number, _, name in parsed[2]):
            counts["excludedUnreliable"] += 1  # Includes a selected name carrying the wrong channel number.
            continue
        stamp, state, entries = parsed
        matched = [entry for entry in entries if (entry[0], entry[2]) in wanted]
        if not matched:
            counts["excludedDeselectedOnly"] += 1
            continue
        counts["included"] += 1
        removed = len(entries) - len(matched)
        rows.extend(dict(localTime=stamp, state=state, channelNumber=number, alarmNumber=alarm, channelName=name,
                         messageType=kind, createdUtc=message.get("created", ""), otherChannelsRemoved=removed)
                    for number, alarm, name in matched)
    counts["rows"] = len(rows)
    return rows, counts


def _cell(value):
    text = str(value)
    return "'" + text if text.startswith(FORMULA_PREFIX) else text  # Prevent spreadsheet formula execution.


def render_csv(rows, counts, native, record, instrument, interval, selected):
    """Build the CSV text. The notice is repeated in the filename, header and every row."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for line in (NOTICE,
                 "Derived from Reviewer's message data; it does not replace the native PDF.",
                 "Includes alarm entries only, and only where a selected channel's number and exact name are proven.",
                 f"Native report: {native['name']}", f"Native report SHA-256: {native['sha256']}",
                 f"Record: {record}", f"Instrument: {instrument}",
                 f"Interval (UTC): {interval['start']} to {interval['end']}", f"Selected channels: {len(selected)}",
                 "Counts: " + ", ".join(f"{key}={value}" for key, value in counts.items()), f"Generated (UTC): {now_iso()}"):
        buffer.write("# " + line + "\n")  # Written directly so every header line starts with "#".
    columns = ("source", "localTime", "state", "channelNumber", "alarmNumber", "channelName", "messageType", "createdUtc", "otherChannelsRemoved")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["SUPPLEMENTARY", *(_cell(row[key]) for key in columns[1:])])
    return buffer.getvalue()


def write_filtered_messages(result, messages, channels, selected, group, interval, log):
    """Write the supplementary CSV beside a verified native PDF, or explain why it was withheld."""
    from pathlib import Path
    pdf = Path(result["output"])
    if result.get("messageTimestamps") != len(messages):
        log("supplementaryMessagesWithheld", dict(reason="Message data does not match the native PDF",
                                                  pdfMessages=result.get("messageTimestamps"), dataMessages=len(messages)))
        return None
    rows, counts = classify_messages(messages, channels, selected)
    native = dict(name=pdf.name, sha256=hashlib.sha256(pdf.read_bytes()).hexdigest())
    instrument = group["instrument"]
    text = render_csv(rows, counts, native, group["groupName"], f"{instrument['instrumentName']} ({instrument.get('macAddress', '')})", interval, selected)
    output = pdf.with_name(f"SUPPLEMENTARY_filtered_messages_{pdf.stem}.csv")
    pending = output.with_name(output.name + ".part")
    payload = text.encode("utf-8-sig")  # A byte order mark lets Excel read the text correctly.
    pending.write_bytes(payload)
    pending.replace(output)
    evidence = dict(output=str(output), sha256=hashlib.sha256(payload).hexdigest(), nativeReport=native, native=False, **counts)
    log("supplementaryMessages", evidence)
    return evidence
