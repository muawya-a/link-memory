$ErrorActionPreference = 'Stop'

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$stopScript = Join-Path $repoRoot 'scripts\stop.ps1'
$stopSource = Get-Content -LiteralPath $stopScript -Raw
if ($stopSource -notmatch '(?m)^param\([\s\S]*\[switch\]\$TestMode' -or
    $stopSource -notmatch '(?m)^if \(\$TestMode\) \{ return \}') {
  throw 'stop.ps1 must expose a side-effect-free TestMode before the test can load its functions.'
}
. $stopScript -TestMode

function Assert-Equal($Expected, $Actual, [string]$Message) {
  if ($Expected -ne $Actual) {
    throw "$Message (expected: '$Expected'; actual: '$Actual')"
  }
}

$syntheticRoot = Join-Path $repoRoot 'synthetic checkout with spaces'
$targetScript = Join-Path $syntheticRoot 'gateway\server.py'
$stoppedIds = [System.Collections.Generic.List[int]]::new()
$stopAction = { param($Id) [void]$stoppedIds.Add([int]$Id) }

$mismatchedProcess = [pscustomobject]@{
  ProcessId = 4101
  CommandLine = 'python.exe "C:\other-checkout\gateway\server.py"'
}
$mismatchResult = Stop-OwnedProcess -PidText '4101' -ScriptPath $targetScript -ProjectRoot $syntheticRoot `
  -ProcessLookup { param($Id) $mismatchedProcess } -StopAction $stopAction
Assert-Equal $false $mismatchResult 'A PID for another checkout must not be selected'
Assert-Equal 0 $stoppedIds.Count 'A mismatched PID must never reach the stop action'

$pathAsDataProcess = [pscustomobject]@{
  ProcessId = 4103
  CommandLine = "python.exe -c `"print('ok')`" `"$targetScript`""
}
$pathAsDataResult = Stop-OwnedProcess -PidText '4103' -ScriptPath $targetScript -ProjectRoot $syntheticRoot `
  -ProcessLookup { param($Id) $pathAsDataProcess } -StopAction $stopAction
Assert-Equal $false $pathAsDataResult 'A project script path appearing as a later Python data argument must not be selected'
Assert-Equal 0 $stoppedIds.Count 'A later data argument must never reach the stop action'

$matchingProcess = [pscustomobject]@{
  ProcessId = 4102
  CommandLine = "python.exe `"$targetScript`""
}
$matchingResult = Stop-OwnedProcess -PidText '4102' -ScriptPath $targetScript -ProjectRoot $syntheticRoot `
  -ProcessLookup { param($Id) $matchingProcess } -StopAction $stopAction
Assert-Equal $true $matchingResult 'A PID whose command line names this checkout script should be selected'
Assert-Equal 1 $stoppedIds.Count 'The matching synthetic process should be selected exactly once'
Assert-Equal 4102 $stoppedIds[0] 'The selected synthetic PID should be passed to the injected action'

$stagingGatewayScript = Join-Path $syntheticRoot 'scripts\staging_gateway.py'
$sandboxGatewayScript = Join-Path $syntheticRoot 'gateway\server.py'
$foreignStagingGateway = Join-Path ([IO.Path]::GetFullPath($env:TEMP)) 'other-checkout\scripts\staging_gateway.py'
$processCandidates = @(
  [pscustomobject]@{ ProcessId = 4201; CommandLine = "python.exe `"$stagingGatewayScript`" --link-memory-profile=staging" },
  [pscustomobject]@{ ProcessId = 4202; CommandLine = "python.exe `"$sandboxGatewayScript`"" },
  [pscustomobject]@{ ProcessId = 4203; CommandLine = "python.exe `"$foreignStagingGateway`" --link-memory-profile=staging" }
)
$scopedProcesses = @(Get-ProjectScriptProcesses -Processes $processCandidates -ScriptPath $stagingGatewayScript -ProjectRoot $syntheticRoot -Profile staging)
Assert-Equal 1 $scopedProcesses.Count 'Only a process for this checkout and profile should reach PID revalidation'
Assert-Equal 4201 $scopedProcesses[0].ProcessId 'The exact staging Gateway process should be retained for revalidation'
$sameScriptWrongProfile = [pscustomobject]@{ ProcessId = 4204; CommandLine = "python.exe `"$stagingGatewayScript`" --link-memory-profile=other" }
Assert-Equal $false (Test-ProjectScriptProcess -Process $sameScriptWrongProfile -ScriptPath $stagingGatewayScript -ProjectRoot $syntheticRoot -Profile staging) 'A same-script process with a wrong profile marker must be rejected'

$invalidPidResult = Stop-OwnedProcess -PidText '0' -ScriptPath $targetScript -ProjectRoot $syntheticRoot `
  -ProcessLookup { throw 'Process lookup must not run for an invalid PID' } -StopAction $stopAction
Assert-Equal $false $invalidPidResult 'Zero is not a valid process ID'
Assert-Equal 1 $stoppedIds.Count 'Invalid PIDs must not reach the stop action'

$stagingStopPlan = & $stopScript -Profile staging -PlanOnly
$expectedStagingGateway = Join-Path $repoRoot 'scripts\staging_gateway.py'
$expectedStagingDashboard = Join-Path $repoRoot 'scripts\staging_dashboard.py'
Assert-Equal $expectedStagingGateway $stagingStopPlan.PidTargets[0].Script 'A staging stop plan must target the staging Gateway wrapper'
Assert-Equal $expectedStagingDashboard $stagingStopPlan.PidTargets[4].Script 'A staging stop plan must target the staging Dashboard wrapper'
Assert-Equal (Join-Path $repoRoot 'scripts\watch_inbox.py') $stagingStopPlan.PidTargets[5].Script 'A staging stop plan must retain the scoped inbox watcher target'
Assert-Equal (Join-Path $repoRoot 'staging-data') $stagingStopPlan.PidDirectory 'A staging stop plan must read PID files only from staging-data'

$sandboxStopPlan = & $stopScript -Profile sandbox -PlanOnly
Assert-Equal (Join-Path $repoRoot 'gateway\server.py') $sandboxStopPlan.PidTargets[0].Script 'A sandbox stop plan must target the sandbox Gateway script'
Assert-Equal (Join-Path $repoRoot 'dashboard\serve.py') $sandboxStopPlan.PidTargets[4].Script 'A sandbox stop plan must target the sandbox Dashboard script'
Assert-Equal (Join-Path $repoRoot 'data') $sandboxStopPlan.PidDirectory 'A sandbox stop plan must read PID files only from data'

Write-Output 'PowerShell stop scoping checks passed; no process command was invoked.'
