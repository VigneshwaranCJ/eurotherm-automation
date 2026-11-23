"""Lightweight Windows disk and service queries."""
import re
import shutil
import subprocess


def disk_and_service_status():
    # Use lightweight Windows queries: starting PowerShell while headed Chrome is
    # running can fail to create threads on this memory-constrained host.
    disks = []
    for drive in ("C:\\", "D:\\"):
        usage = shutil.disk_usage(drive)
        disks.append(dict(drive=drive, totalGB=usage.total / 1024**3, freeGB=usage.free / 1024**3))
    output = subprocess.check_output(["sc.exe", "query", "type=", "service", "state=", "all", "bufsize=", "262144"],
                                     text=True, errors="replace", timeout=90,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
    return dict(disks=disks, services=parse_services(output))


def parse_services(output):
    services = []
    for block in output.split("SERVICE_NAME:")[1:]:
        name = block.splitlines()[0].strip()
        display = re.search(r"DISPLAY_NAME:\s*(.*)", block)
        if re.search("Reviewer|Elastic", name + " " + (display[1] if display else ""), re.I):
            state = re.search(r"STATE\s*:\s*\d+\s+(\w+)", block)
            if not state:
                raise RuntimeError(f"Service status unavailable: {name}")
            services.append(dict(name=name, status=state[1].replace("_", " ").title().replace(" ", "")))
    return services
