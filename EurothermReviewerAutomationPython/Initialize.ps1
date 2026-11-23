param(
    # Path to a standalone Python 3.11+ python.exe (3.12 is recommended and tested).
    [string]$Python,
    # For test copies only: permit an interpreter in a temporary or tool-managed folder.
    [switch]$AllowTemporaryPython
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Test-Interpreter([string]$Path) {
    $ErrorActionPreference = 'Continue'  # A broken interpreter must report failure, not stop setup.
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $false }
    if ((Get-Item -LiteralPath $Path).Length -eq 0) { return $false }  # Microsoft Store alias, not Python.
    & $Path -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}
function Test-Temporary([string]$Path) {
    return $Path -match 'codex-runtimes|\\AppData\\Local\\Temp\\|\\\.cache\\'
}
function Find-StandalonePython {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:ProgramFiles 'Python312\python.exe'),
        (Get-Command python -ErrorAction SilentlyContinue).Source,
        (Join-Path $env:LOCALAPPDATA 'Python\pythoncore-3.14-64\python.exe'))
    return $candidates | Where-Object { $_ -and -not (Test-Temporary $_) -and (Test-Interpreter $_) } | Select-Object -First 1
}

if ($Python) {
    if ((Test-Temporary $Python) -and -not $AllowTemporaryPython) {
        throw "Refusing a temporary or tool-managed Python ($Python). Install standalone Python 3.12: winget install --id Python.Python.3.12 --scope user"
    }
    if (-not (Test-Interpreter $Python)) { throw "Not a working Python 3.11+ interpreter: $Python" }
    $base = $Python
} else {
    $base = Find-StandalonePython
}

$venvWorks = Test-Interpreter '.venv\Scripts\python.exe'
$venvHome = if (Test-Path -LiteralPath '.venv\pyvenv.cfg') { (Select-String -LiteralPath '.venv\pyvenv.cfg' -Pattern '^home\s*=\s*(.+)$').Matches.Groups[1].Value } else { '' }
$venvTemporary = $venvHome -and (Test-Temporary "$venvHome\") -and -not $AllowTemporaryPython
if (-not $venvWorks -or $venvTemporary -or $Python) {
    if ($base) {
        Write-Host "Creating .venv from $base"
        & $base -m venv --clear .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv.' }
    } elseif (-not $venvWorks) {
        throw 'Python 3.11 or newer is required. Install standalone Python 3.12: winget install --id Python.Python.3.12 --scope user'
    } else {
        Write-Warning ".venv is based on a temporary Python ($venvHome), and no standalone Python was found. Install one: winget install --id Python.Python.3.12 --scope user"
    }
}

& .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}

$helper = 'tools\reader\VendorInspect.dll'
if (-not (Test-Path -LiteralPath $helper)) {
    $reference = Join-Path (Split-Path $PSScriptRoot -Parent) 'EurothermReviewerAutomation'
    $reader = Join-Path $reference '.tmp\reader-v2\net10.0'
    if (-not (Test-Path -LiteralPath $reader)) {
        throw "Vendor metadata helper missing: $helper. Restore tools\reader or build tools\VendorInspect.cs for net10.0."
    }
    New-Item -ItemType Directory -Force -Path 'tools\reader' | Out-Null
    Copy-Item -Path "$reader\VendorInspect.*" -Destination 'tools\reader' -Force
}

Write-Host 'Environment check:'
$ErrorActionPreference = 'Continue'
& .\.venv\Scripts\python.exe -m reviewer check-env
if ($LASTEXITCODE -eq 0) { Write-Host 'Setup complete.' } else { Write-Warning 'Setup finished, but the failed checks above must be fixed before running automation.' }
