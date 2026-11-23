"""Unique instrument/group mapping from vendor metadata."""
from ..common.time import utc_time


def identity(metadata):
    records = {record["kind"]: record.get("details") for record in metadata["Records"]}
    segment, history = records.get("SegmentRecord"), records.get("HistoryRecord")
    if not segment or not history:
        raise RuntimeError("Vendor reader returned no group/instrument identity")
    return segment, history


def identity_candidates(groups, metadata):
    segment, history = identity(metadata)
    return [g for g in groups if g["groupName"] == segment["GroupName"]
            and g["instrument"]["instrumentName"] == segment["InstrumentName"]
            and g["instrument"]["macAddress"] == history["MacAddr"]]


def select_group(groups, metadata, configured_group=""):
    candidates = [g for g in identity_candidates(groups, metadata)
                  if utc_time(g["dataStart"]) <= utc_time(metadata["FirstSample"])
                  and utc_time(g["dataEnd"]) >= utc_time(metadata["LastSample"])]
    if len(candidates) != 1:
        raise RuntimeError(f"Reliable group mapping unavailable: {len(candidates)} candidates")
    if configured_group and configured_group != candidates[0]["groupName"]:
        raise RuntimeError("Configured group does not match UHH metadata")
    return candidates[0]
