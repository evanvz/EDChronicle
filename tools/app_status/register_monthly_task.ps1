# Registers the monthly full app status run. Run by hand once: powershell -File register_monthly_task.ps1
# New-ScheduledTaskTrigger has no monthly option (docs checked 2026-11-07), so schtasks.exe is used.
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$py = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "missing $py" }
$tr = 'cmd /c cd /d \"{0}\" && \"{1}\" -m tools.app_status --full' -f $repo, $py
$schArgs = '/Create /F /SC MONTHLY /D 1 /ST 10:00 /IT /TN "EDChronicle App Status (monthly)" /TR "{0}"' -f $tr
$p = Start-Process schtasks.exe -ArgumentList $schArgs -Wait -NoNewWindow -PassThru
exit $p.ExitCode
