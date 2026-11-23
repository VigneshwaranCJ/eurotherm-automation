"""Archive identity and exact-content duplicate verification."""
from pathlib import Path
import re
from ..common.time import utc_time
from .identity import identity_candidates
from .validation import hash_file


def archived_file(group, file):
    def safe(value):
        return re.sub(r'[\\/:*?"<>|]', "", value)
    instrument = group["instrument"]
    return (Path(r"C:\ProgramData\Eurotherm\Reviewer\archive")
            / f"{safe(instrument['instrumentName'])}_{instrument['macAddress']}"
            / f"{safe(group['groupName'])}_{safe(group['groupId'])}" / file.name)


def check_duplicate(group, file):
    archive = archived_file(group, file)
    if not archive.exists():
        return dict(status="uncertain", archive=str(archive))
    if hash_file(archive) != hash_file(file):
        raise RuntimeError("Archive filename collision: content differs; import stopped")
    return dict(status="already-imported", archive=str(archive))


def import_evidence(groups, metadata, file):
    candidates = identity_candidates(groups, metadata)
    for group in candidates:
        duplicate = check_duplicate(group, file)
        if duplicate["status"] == "already-imported":
            return dict(duplicate, group=group)
    overlapping = any(utc_time(g["dataStart"]) <= utc_time(metadata["LastSample"])
                      and utc_time(g["dataEnd"]) >= utc_time(metadata["FirstSample"]) for g in candidates)
    return dict(status="uncertain" if overlapping else "not-imported")
