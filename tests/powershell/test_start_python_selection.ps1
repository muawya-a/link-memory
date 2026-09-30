$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
. (Join-Path $repoRoot 'scripts\start.ps1') -PlanOnly | Out-Null

function Assert-Equal($Expected, $Actual, [string]$Message) {
  if ($Expected -ne $Actual) { throw "$Message (expected: '$Expected'; actual: '$Actual')" }
}

$windowsAppsAlias = 'C:\Users\tester\AppData\Local\Microsoft\WindowsApps\python.exe'
$installedPython = 'C:\Python312\python.exe'
$olderPython = 'D:\Tools\Python311\python.exe'
$notepad = 'C:\Windows\System32\notepad.exe'
$existingPaths = @($installedPython, $olderPython, $notepad)
$exists = { param($Candidate) $existingPaths -contains $Candidate }.GetNewClosure()
$environmentBefore = @{}
[Environment]::GetEnvironmentVariables('Process').GetEnumerator() | ForEach-Object { $environmentBefore[[string]$_.Key] = [string]$_.Value }

Assert-Equal $installedPython (Resolve-LinkPythonExecutable -CandidatePaths @($windowsAppsAlias, 'C:\Missing\python.exe', $installedPython, $olderPython) -PathExists $exists) 'Auto-discovery must skip aliases and missing executables before choosing the first installed executable'
Assert-Equal $olderPython (Resolve-LinkPythonExecutable -CandidatePaths @($windowsAppsAlias, $olderPython) -PathExists $exists) 'Auto-discovery must continue after a WindowsApps alias'
Assert-Equal $olderPython (Resolve-LinkPythonExecutable -ExplicitPath $olderPython -CandidatePaths @($installedPython) -PathExists $exists) 'An explicit installed interpreter must take precedence over auto-discovery'

$missing = 'C:\Python313\python.exe'
$missingError = $null
try { Resolve-LinkPythonExecutable -ExplicitPath $missing -CandidatePaths @($installedPython) -PathExists $exists | Out-Null } catch { $missingError = $_.Exception.Message }
if (-not $missingError -or $missingError -notmatch 'does not exist') { throw 'A missing explicit interpreter must fail with an actionable missing-path error.' }

$nonPythonError = $null
try { Resolve-LinkPythonExecutable -ExplicitPath $notepad -CandidatePaths @($installedPython) -PathExists $exists | Out-Null } catch { $nonPythonError = $_.Exception.Message }
if (-not $nonPythonError -or $nonPythonError -notmatch 'python.exe') { throw 'An existing non-Python executable must be rejected with guidance to specify python.exe.' }

$onlyAliasError = $null
try { Resolve-LinkPythonExecutable -CandidatePaths @($windowsAppsAlias) -PathExists $exists | Out-Null } catch { $onlyAliasError = $_.Exception.Message }
if (-not $onlyAliasError -or $onlyAliasError -notmatch 'WindowsApps|installed Python') { throw 'When only a WindowsApps alias is available, selection must explain how to install or specify Python.' }

$explicitAliasError = $null
try { Resolve-LinkPythonExecutable -ExplicitPath $windowsAppsAlias -PathExists $exists | Out-Null } catch { $explicitAliasError = $_.Exception.Message }
if (-not $explicitAliasError -or $explicitAliasError -notmatch 'WindowsApps') { throw 'An explicit WindowsApps alias must be rejected with a clear explanation.' }

$commandCandidates = @(
  [pscustomobject]@{ CommandType = 'Application'; Source = $windowsAppsAlias },
  [pscustomobject]@{ CommandType = 'Application'; Source = $installedPython }
)
$commands = { $commandCandidates }.GetNewClosure()
Assert-Equal $installedPython (Resolve-LinkPythonExecutable -CommandResolver $commands -PathExists $exists) 'Command discovery must ignore the Store alias and select an existing application executable'

$environmentAfter = @{}
[Environment]::GetEnvironmentVariables('Process').GetEnumerator() | ForEach-Object { $environmentAfter[[string]$_.Key] = [string]$_.Value }
Assert-Equal (ConvertTo-Json $environmentBefore -Compress) (ConvertTo-Json $environmentAfter -Compress) 'Python resolver tests must not mutate process environment variables'

Write-Output 'PASS: Python selection prefers installed executables, validates explicit paths, skips WindowsApps aliases, and uses injected resolvers without launching services or changing environment variables.'
