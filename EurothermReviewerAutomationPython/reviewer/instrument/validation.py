"""Stable read-only file validation and hashing."""
import hashlib
from pathlib import Path
from ..common.process import powershell


def hash_file(file):
    with Path(file).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_file(file):
    if file.suffix.lower() != '.uhh':
        raise ValueError('Input must be a .UHH file')
    before = file.stat()
    if not file.is_file() or before.st_size == 0:
        raise RuntimeError("UHH file is missing or empty")
    escaped = str(file).replace("'", "''")
    digest = powershell(
        "$ErrorActionPreference='Stop';"
        f"$s=[IO.File]::Open('{escaped}',[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);"
        "$h=[Security.Cryptography.SHA256]::Create();"
        "try{Start-Sleep -Milliseconds 1000;[BitConverter]::ToString($h.ComputeHash($s)).Replace('-','').ToLowerInvariant()}"
        "finally{$h.Dispose();$s.Dispose()}"
    )
    after = file.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise RuntimeError("UHH file changed during validation")
    return dict(file=str(file), size=after.st_size, sha256=digest, readable=True, stable=True, writerExcludedDuringCheck=True)
