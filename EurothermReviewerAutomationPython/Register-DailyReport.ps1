$ErrorActionPreference = 'Stop'
$taskName = 'Eurotherm Daily PDF Report Python'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw "Task '$taskName' already exists; it will not be overwritten."
}
if ((Get-TimeZone).Id -ne 'India Standard Time') {
    throw 'Windows timezone must be India Standard Time for this 10 AM schedule.'
}
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$launcher = Join-Path $PSScriptRoot 'Run-DailyReport.cmd'
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument "/d /c `"$launcher`"" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At '10:00AM'
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Native Reviewer Python PDF report using exact .env dates. Requires logged-in user. No imports.' | Select-Object TaskName,State
