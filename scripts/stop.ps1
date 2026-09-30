param(
  [switch]$TestMode,
  [ValidateSet('sandbox', 'staging')][string]$Profile = 'sandbox',
  [switch]$PlanOnly
)

$ErrorActionPreference = 'Continue'
$Root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
. (Join-Path $PSScriptRoot 'profile.ps1')
$profilePlan = Get-LinkProfilePlan -ProjectRoot $Root -Profile $Profile

function Test-ProjectScriptProcess {
  param(
    [object]$Process,
    [string]$ScriptPath,
    [string]$ProjectRoot,
    [ValidateSet('sandbox', 'staging')][string]$Profile = 'sandbox'
  )

  if (-not $Process -or -not $Process.ProcessId -or [int]$Process.ProcessId -le 0 -or -not $Process.CommandLine) {
    return $false
  }

  try {
    $rootPath = [IO.Path]::GetFullPath($ProjectRoot)
    $expectedPath = [IO.Path]::GetFullPath($ScriptPath)
  } catch {
    return $false
  }

  $rootPrefix = $rootPath.TrimEnd([char[]]@('\', '/')) + [IO.Path]::DirectorySeparatorChar
  if (-not $expectedPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    return $false
  }

  return (Test-LinkScriptCommand -CommandLine $Process.CommandLine -ScriptPath $expectedPath -Profile $Profile)
}

function Stop-OwnedProcess {
  param(
    [string]$PidText,
    [string]$ScriptPath,
    [string]$ProjectRoot,
    [ValidateSet('sandbox', 'staging')][string]$Profile = 'sandbox',
    [scriptblock]$ProcessLookup = {
      param($Id)
      Get-CimInstance Win32_Process -Filter "ProcessId = $Id" -ErrorAction SilentlyContinue
    },
    [scriptblock]$StopAction = {
      param($Id)
      Stop-Process -Id $Id -Force -ErrorAction SilentlyContinue
    }
  )

  if ($PidText -notmatch '^[1-9][0-9]*$') { return $false }
  try {
    $requestedPid = [int]$PidText
  } catch {
    return $false
  }
  if ($requestedPid -le 0) { return $false }

  $processes = @(& $ProcessLookup $requestedPid)
  if ($processes.Count -ne 1 -or [int]$processes[0].ProcessId -ne $requestedPid) {
    return $false
  }
  if (-not (Test-ProjectScriptProcess -Process $processes[0] -ScriptPath $ScriptPath -ProjectRoot $ProjectRoot -Profile $Profile)) {
    return $false
  }

  & $StopAction $requestedPid | Out-Null
  return $true
}

function Get-ProjectScriptProcesses {
  param(
    [object[]]$Processes,
    [string]$ScriptPath,
    [string]$ProjectRoot,
    [ValidateSet('sandbox', 'staging')][string]$Profile = 'sandbox'
  )

  return @($Processes | Where-Object {
    Test-ProjectScriptProcess -Process $_ -ScriptPath $ScriptPath -ProjectRoot $ProjectRoot -Profile $Profile
  })
}

function Get-StopPidTargets {
  param(
    [string]$ProjectRoot,
    [object]$ProfilePlan,
    [ValidateSet('sandbox', 'staging')][string]$Profile = 'sandbox'
  )

  $gatewayScript = if ($Profile -eq 'staging') {
    Join-Path $ProjectRoot 'scripts\staging_gateway.py'
  } else {
    Join-Path $ProjectRoot 'gateway\server.py'
  }
  $dashboardScript = if ($Profile -eq 'staging') {
    Join-Path $ProjectRoot 'scripts\staging_dashboard.py'
  } else {
    Join-Path $ProjectRoot 'dashboard\serve.py'
  }

  return @(
    @{ Path = (Join-Path $ProfilePlan.DataRoot 'gateway.pid'); Script = $gatewayScript },
    @{ Path = (Join-Path $ProfilePlan.DataRoot 'reranker.pid'); Script = (Join-Path $ProjectRoot 'gateway\reranker_server.py') },
    @{ Path = (Join-Path $ProfilePlan.DataRoot 'graphiti.pid'); Script = (Join-Path $ProjectRoot 'gateway\graphiti_service.py') },
    @{ Path = (Join-Path $ProfilePlan.DataRoot 'mempalace.pid'); Script = (Join-Path $ProjectRoot 'gateway\mempalace_service.py') },
    @{ Path = (Join-Path $ProfilePlan.DataRoot 'dashboard.pid'); Script = $dashboardScript },
    @{ Path = (Join-Path $ProfilePlan.DataRoot 'watcher.pid'); Script = (Join-Path $ProjectRoot 'scripts\watch_inbox.py') }
  )
}

if ($TestMode) { return }
if ($PlanOnly) {
  return [pscustomobject]@{
    Profile = $Profile
    PidDirectory = $profilePlan.DataRoot
    ProcessMarker = $profilePlan.ProcessMarker
    PidTargets = @(Get-StopPidTargets -ProjectRoot $Root -ProfilePlan $profilePlan -Profile $Profile)
  }
}

$PidTargets = @(Get-StopPidTargets -ProjectRoot $Root -ProfilePlan $profilePlan -Profile $Profile)

foreach ($target in $PidTargets) {
  if (Test-Path -LiteralPath $target.Path) {
    $pidText = Get-Content -LiteralPath $target.Path -Raw -ErrorAction SilentlyContinue
    if (-not (Stop-OwnedProcess -PidText ([string]$pidText).Trim() -ScriptPath $target.Script -ProjectRoot $Root -Profile $Profile)) {
      Write-Output "Skipped unverified process ID file: $($target.Path)"
    }
    Remove-Item -LiteralPath $target.Path -Force -ErrorAction SilentlyContinue
  }
}

function Stop-AllMatchingScript([string]$ScriptPath) {
  $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
  $matchingProcesses = @(Get-ProjectScriptProcesses -Processes $processes -ScriptPath $ScriptPath -ProjectRoot $Root -Profile $Profile)
  foreach ($process in $matchingProcesses) {
    $pidText = [string]$process.ProcessId
    [void](Stop-OwnedProcess -PidText $pidText -ScriptPath $ScriptPath -ProjectRoot $Root -Profile $Profile)
  }
}

if ($Profile -eq 'staging') {
  Stop-AllMatchingScript (Join-Path $Root 'scripts\staging_gateway.py')
} else {
  Stop-AllMatchingScript (Join-Path $Root 'gateway\server.py')
}
Stop-AllMatchingScript (Join-Path $Root 'gateway\reranker_server.py')
Stop-AllMatchingScript (Join-Path $Root 'gateway\graphiti_service.py')
Stop-AllMatchingScript (Join-Path $Root 'gateway\mempalace_service.py')
if ($Profile -eq 'staging') {
  Stop-AllMatchingScript (Join-Path $Root 'scripts\staging_dashboard.py')
} else {
  Stop-AllMatchingScript (Join-Path $Root 'dashboard\serve.py')
}
Stop-AllMatchingScript (Join-Path $Root 'scripts\watch_inbox.py')
