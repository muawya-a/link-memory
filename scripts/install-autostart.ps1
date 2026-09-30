$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$AutoStart = Join-Path $Root 'scripts\autostart.ps1'
$Backup = Join-Path $Root 'scripts\backup.ps1'
$UserId = "$env:USERDOMAIN\$env:USERNAME"
$Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited

# Sandbox-specific names ensure installation cannot replace tasks belonging to
# the original application. No model or provider service is launched here.
$TaskName = 'Link Memory Sandbox - Start Local Dashboard'
$Action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$AutoStart`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description 'Starts only the isolated Link Memory sandbox Gateway and dashboard.' -Force | Out-Null
Write-Output "Installed sandbox scheduled task: $TaskName"

$BackupTask = 'Link Memory Sandbox - Daily Verified Backup'
$BackupAction = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Backup`""
$BackupTrigger = New-ScheduledTaskTrigger -Daily -At 3:00am
$BackupSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName $BackupTask -Action $BackupAction -Trigger $BackupTrigger -Settings $BackupSettings -Principal $Principal -Description 'Backs up only the sandbox Gateway database.' -Force | Out-Null
Write-Output "Installed sandbox scheduled task: $BackupTask"
