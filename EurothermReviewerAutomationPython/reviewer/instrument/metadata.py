"""Read-only vendor UHH metadata adapter."""
import json
import os
import subprocess
from ..config import ROOT


def read_interval(settings):
    helper = ROOT / "tools" / "reader" / "VendorInspect.dll"
    if not helper.is_file():
        raise RuntimeError("Vendor metadata helper is missing. Run Initialize.ps1.")
    env = dict(os.environ, DOTNET_CLI_HOME=str(settings.temp / "dotnet-home"),
               DOTNET_GENERATE_ASPNET_CERTIFICATE="false", DOTNET_CLI_TELEMETRY_OPTOUT="1",
               APPDATA=str(settings.temp / "AppData"), LOCALAPPDATA=str(settings.temp / "LocalAppData"))
    try:
        output = subprocess.check_output(["dotnet", str(helper), "read", str(settings.file)],
                                         encoding="utf-8", timeout=90, env=env,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
    except FileNotFoundError as error:
        raise RuntimeError("The .NET 10 runtime is required to read UHH metadata, but dotnet was not found. "
                           "Install it with: winget install Microsoft.DotNet.Runtime.10") from error
    line = next((line for line in output.splitlines() if line.startswith("{")), None)
    if line is None:
        raise RuntimeError("Vendor UHH reader returned no metadata")
    data = json.loads(line)
    if not data.get("FirstSample") or not data.get("LastSample") or data.get("Samples", 0) < 2:
        raise RuntimeError("UHH has no usable recording interval")
    return data
