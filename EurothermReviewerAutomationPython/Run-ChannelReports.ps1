<#
.SYNOPSIS
Creates Channel, Pen and Message Log PDFs, one per channel, for an IST time range.

.EXAMPLE
.\Run-ChannelReports.ps1 -Start "2026-11-03 18:00" -End "2026-11-03 22:00"

.NOTES
Imports into Reviewer are always blocked here; the input must already be imported.
Rerunning with the same range reuses verified reports and continues where a run stopped.
Environment variables are set for this run only and restored afterwards; .env and workflow.json are not changed.
#>
param(
    [Parameter(Mandatory = $true)][string]$Start,
    [Parameter(Mandatory = $true)][string]$End,
    [string]$Config = "$PSScriptRoot\.tmp\e2e\r5\wf-split.json",
    [switch]$ShowBrowser
)
$ErrorActionPreference = 'Stop'

function ConvertTo-IstTimestamp([string]$value, [string]$name) {
    $formats = [string[]]@('yyyy-MM-dd HH:mm', 'yyyy-MM-dd HH:mm:ss', 'yyyy-MM-ddTHH:mm', 'yyyy-MM-ddTHH:mm:ss')
    $parsed = [datetime]::MinValue
    if (-not [datetime]::TryParseExact($value, $formats, [Globalization.CultureInfo]::InvariantCulture, 'None', [ref]$parsed)) {
        throw "$name must look like 2026-11-03 18:00 (IST); got '$value'"
    }
    return $parsed.ToString('yyyy-MM-ddTHH:mm:ss') + '+05:30'
}

$startStamp = ConvertTo-IstTimestamp $Start '-Start'
$endStamp = ConvertTo-IstTimestamp $End '-End'
if ($endStamp -le $startStamp) { throw '-End must be later than -Start' }
$Config = (Resolve-Path $Config).Path
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "Python environment not found: $python. Run Initialize.ps1 first." }

$names = 'REVIEWER_BLOCK_IMPORTS', 'HEADLESS', 'WORKFLOW_CONFIG', 'REPORT_MODE', 'START_DATETIME', 'END_DATETIME'
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
Push-Location $PSScriptRoot
try {
    $env:REVIEWER_BLOCK_IMPORTS = 'true'
    $env:HEADLESS = if ($ShowBrowser) { 'false' } else { 'true' }
    $env:WORKFLOW_CONFIG = $Config
    $env:REPORT_MODE = 'env'
    $env:START_DATETIME = $startStamp
    $env:END_DATETIME = $endStamp
    Write-Host "Reports for $startStamp to $endStamp using $Config"
    & $python -m reviewer workflow:run
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        $output = (Get-Content $Config -Raw | ConvertFrom-Json).output_dir
        Write-Host "Completed. Reports are under $output"
    } else {
        Write-Host "Stopped with exit code $code. Run the same command again to continue from the last finished report."
    }
    exit $code
} finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    Pop-Location
}
