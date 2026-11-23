"""Shared report identity, values, channels, dates and page-count checks."""
from datetime import datetime
import re

VIRTUAL_INSTRUMENT = "Virtual Instrument"
HEADER = re.compile(r"^[ \t]*Instrument:[ \t]*(.*?),[ \t]*Group:[ \t]*(.*?)[ \t]*$", re.M)
PAGE_FOOTER = re.compile(r"(?<![\d/.:])(\d{1,4})/(\d{1,4})\s*$")
PREVIEW_FOOTER = re.compile(r"(?<![\d/.:])(\d{1,4})/(\d{1,4})[ \t]*$", re.M)
MESSAGES_HEADING = re.compile(r"^[ \t]*Messages[ \t]*$", re.M)
TIME_FIRST = re.compile(r"(?<![\d:.])(\d{2}:\d{2}:\d{2}\.\d{3})\s+(\d{2}/\d{2}/\d{4})")
DATE_FIRST = re.compile(r"(?<![\d/])(\d{2}/\d{2}/\d{4})[ \t]+(\d{2}:\d{2}:\d{2})(?![.\d])")


def report_date(chart):
    """The report's start date as Reviewer displays it, in the instrument's local time."""
    found = re.search(r"(\d{2})/(\d{2})/(\d{4})", chart["displayStart"])
    if not found:
        raise RuntimeError(f"Unreadable report start date: {chart['displayStart']}")
    return f"{found[3]}-{found[2]}-{found[1]}"


def message_only(settings):
    return settings.include_messages and not settings.include_chart and not settings.include_values


def channel_present(name, text):
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text) is not None


def verify_boundaries(text, chart):
    normalized = " ".join(text.split())
    for name, display in (("start", chart["displayStart"]), ("end", chart["displayEnd"])):
        boundary = re.search(r"\d{2}:\d{2}:\d{2}(?:\.\d{3})?\s+\d{2}/\d{2}/\d{4}", display)
        if not boundary or " ".join(boundary[0].split()) not in normalized:
            raise RuntimeError(f"Report lacks the verified {name} time and recording date")


def verify_identity(text, group, settings):
    if settings.title not in text:
        raise RuntimeError("Report lacks expected title/group/instrument")
    headers = {(instrument.strip(), name.strip()) for instrument, name in HEADER.findall(text)}
    if not headers:
        raise RuntimeError("Report lacks expected title/group/instrument")
    allowed = {group["instrument"]["instrumentName"].strip()}
    # Without a chart, Reviewer labels Custom records with their virtual instrument.
    if group.get("isCustomGroup") and message_only(settings):
        allowed.add(VIRTUAL_INSTRUMENT)
    expected = group["groupName"].strip()
    wrong = sorted(h for h in headers if h[0] not in allowed or h[1] != expected)
    if wrong:
        raise RuntimeError(f"Report identity mismatch: expected {sorted(allowed)} / {expected!r}; found {wrong}")


def verify_date_range(text, chart):
    """Every sample, cursor and message timestamp must fall inside the requested display range."""
    def display(value):
        found = re.search(r"(\d{2}:\d{2}:\d{2})(?:\.(\d{3}))?\s+(\d{2}/\d{2}/\d{4})", value)
        if not found:
            raise RuntimeError(f"Unreadable report boundary: {value}")
        stamp = datetime.strptime(f"{found[3]} {found[1]}", "%d/%m/%Y %H:%M:%S")
        return stamp.replace(microsecond=int(found[2] or 0) * 1000)
    start, end = display(chart["displayStart"]), display(chart["displayEnd"])
    first_second = start.replace(microsecond=0)  # Messages have one-second resolution.
    samples = [datetime.strptime(f"{day} {clock}", "%d/%m/%Y %H:%M:%S.%f") for clock, day in TIME_FIRST.findall(text)]
    messages = [datetime.strptime(f"{day} {clock}", "%d/%m/%Y %H:%M:%S") for day, clock in DATE_FIRST.findall(text)]
    outside = [stamp for stamp in samples + messages if not first_second <= stamp <= end]
    if outside:
        raise RuntimeError(f"Report contains {len(outside)} timestamps outside the requested range; first {outside[0]}")
    return dict(messageTimestamps=len(messages), firstMessage=str(min(messages)) if messages else None,
                lastMessage=str(max(messages)) if messages else None)


def verify_channel_scope(text, chart, settings):
    """Deselected channels must not supply report data. Native messages can still name them."""
    deselected = chart.get("deselectedChannels") or []
    in_columns = [name for name in deselected if re.search(rf"■\s*{re.escape(name)}\s*\(", text)]
    if in_columns:
        raise RuntimeError(f"Report contains deselected channel data: {', '.join(in_columns)}")
    mentioned = [name for name in deselected if channel_present(name, text)]
    if mentioned and not settings.include_messages:
        raise RuntimeError(f"Report contains deselected channels: {', '.join(mentioned)}")
    return mentioned


def verify_text(text, group, chart, settings):
    verify_identity(text, group, settings)
    only_messages = message_only(settings)
    if settings.include_values and not re.search(r"\d+[.,]\d+", text):
        raise RuntimeError("Report has no readable measurement values")
    if settings.cursor_statistics and not only_messages and not re.search(r"cursor\s+statistics|range\s+start|range\s+end", text, re.I):
        raise RuntimeError("Report cursor statistics have not been verified")
    if only_messages and not MESSAGES_HEADING.search(text):
        raise RuntimeError("Message-only report lacks a message section")
    missing = [] if only_messages else [c["channelName"] for c in chart["channels"] if not channel_present(c["channelName"], text)]
    if missing:
        raise RuntimeError(f"Report is missing channels: {', '.join(missing)}")
    verify_boundaries(text, chart)
    evidence = verify_date_range(text, chart)
    evidence["deselectedChannelsInMessages"] = verify_channel_scope(text, chart, settings)
    return evidence


def preview_page_total(text):
    """Read the rendered Preview's final n/N footer; Reviewer's pageCheck only estimates chart width."""
    footers = PREVIEW_FOOTER.findall(text)
    if not footers or footers[-1][0] != footers[-1][1]:
        raise RuntimeError("Preview lacks a final page-number footer")
    return int(footers[-1][1])


def verify_page_count(pages, settings, preview_pages=None):
    """Require a complete 1..N document that matches its Preview and the included content."""
    if not pages:
        raise RuntimeError("PDF contains no pages")
    total = len(pages)
    footers = [PAGE_FOOTER.search(page) for page in pages]
    if not all(footers):
        raise RuntimeError("PDF has pages without a page-number footer")
    found = [(int(f[1]), int(f[2])) for f in footers]
    if found != [(number, total) for number in range(1, total + 1)]:
        raise RuntimeError(f"PDF page numbering is incomplete: {total} pages, footers {found[0]}..{found[-1]}")
    without_header = [number for number, page in enumerate(pages, 1) if not HEADER.search(page)]
    if without_header:
        raise RuntimeError(f"PDF pages lack the instrument/group header: {without_header[:5]}")
    minimum = settings.pages + int(settings.cursor_statistics) if settings.include_chart else 1
    if total < minimum:
        raise RuntimeError(f"PDF has {total} pages; the selected content requires at least {minimum}")
    if preview_pages is not None and total != preview_pages:
        raise RuntimeError(f"PDF has {total} pages but its verified Preview had {preview_pages}")
    return total
