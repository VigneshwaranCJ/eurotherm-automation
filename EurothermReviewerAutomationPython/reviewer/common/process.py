"""Read-only Windows subprocess helpers."""
import subprocess


def powershell(script):
    return subprocess.check_output(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        encoding="utf-8", timeout=90, creationflags=subprocess.CREATE_NO_WINDOW,
    ).strip()
