"""Validate the machine prerequisites; `python -m reviewer check-env` reports them all at once."""
import importlib.metadata
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys

from ..config import ROOT

VENDOR_LIBRARY = Path(r"C:\Program Files\Eurotherm\Eurotherm Reviewer\ReviewerService\Eurotherm.Data.dll")
HELPER = ROOT / "tools" / "reader" / "VendorInspect.dll"
TEMPORARY_MARKERS = ("codex-runtimes", r"\appdata\local\temp", r"\.cache")


def is_temporary(path):
    text = str(path).lower()
    return any(marker in text for marker in TEMPORARY_MARKERS)


def check_python():
    version = sys.version_info
    home = Path(sys.base_prefix)
    if version < (3, 11):
        return False, f"Python {version.major}.{version.minor} found; 3.11 or newer is required (3.12 recommended)"
    if is_temporary(home):
        return False, f"Python {version.major}.{version.minor} is based on a temporary folder ({home}). Install standalone Python 3.12 and rerun Initialize.ps1"
    return True, f"Python {version.major}.{version.minor}.{version.micro} at {home}"


def locked_packages(lock=None):
    lines = Path(lock or ROOT / "requirements.lock.txt").read_text(encoding="utf-8").splitlines()
    return dict(line.strip().split("==", 1) for line in lines if "==" in line)


def check_packages():
    wrong = []
    for name, expected in locked_packages().items():
        try:
            found = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            found = "missing"
        if found != expected:
            wrong.append(f"{name} {found} (needs {expected})")
    return (False, "Rerun Initialize.ps1: " + ", ".join(wrong)) if wrong else (True, "Locked packages installed")


def dotnet_10_versions(output):
    return re.findall(r"^Microsoft\.NETCore\.App (10\.\S+)", output, re.M)


def check_dotnet():
    executable = shutil.which("dotnet")
    if not executable:
        return False, "dotnet not found on PATH. Install it with: winget install Microsoft.DotNet.Runtime.10"
    output = subprocess.run([executable, "--list-runtimes"], capture_output=True, text=True, timeout=30).stdout
    versions = dotnet_10_versions(output)
    if not versions:
        return False, "dotnet is present, but Microsoft.NETCore.App 10.x is not. Install it with: winget install Microsoft.DotNet.Runtime.10"
    if is_temporary(executable):
        return False, f"dotnet {versions[-1]} is in a temporary folder ({executable}). Install it with: winget install Microsoft.DotNet.Runtime.10"
    return True, f".NET runtime {versions[-1]} at {executable}"


def check_file(path, missing):
    return (True, str(path)) if Path(path).is_file() else (False, missing)


def check_chrome():
    roots = (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA"))
    for root in filter(None, roots):
        path = Path(root, "Google", "Chrome", "Application", "chrome.exe")
        if path.is_file():
            return True, str(path)
    return False, "Google Chrome is not installed"


def check_reviewer():
    try:
        with socket.create_connection(("localhost", 443), timeout=3):
            return True, "Reviewer is reachable on https://localhost"
    except OSError:
        return False, "Nothing is listening on https://localhost. Start the Reviewer services"


def environment_report():
    return dict(python=check_python(), packages=check_packages(), dotnet10=check_dotnet(),
                metadataHelper=check_file(HELPER, f"Missing {HELPER}; restore tools\\reader or rebuild tools\\VendorInspect.cs"),
                vendorLibrary=check_file(VENDOR_LIBRARY, f"Missing {VENDOR_LIBRARY}; Eurotherm Reviewer must be installed"),
                chrome=check_chrome(), reviewer=check_reviewer())


def print_environment_report(report=None):
    report = report or environment_report()
    for name, (passed, detail) in report.items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}: {detail}")
    return all(passed for passed, _ in report.values())
