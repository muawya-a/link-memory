$ErrorActionPreference = 'Stop'

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$setupScript = Join-Path $repoRoot 'Setup-Link-Memory.ps1'
if (-not (Test-Path -LiteralPath $setupScript)) {
  throw 'Setup-Link-Memory.ps1 must exist before the setup contract can be checked.'
}

function Assert-Equal($Expected, $Actual, [string]$Message) {
  if ($Expected -ne $Actual) {
    throw "$Message (expected: '$Expected'; actual: '$Actual')"
  }
}

$plan = & $setupScript -PlanOnly
Assert-Equal $repoRoot $plan.ProjectRoot 'Setup must resolve its project root from its own path'
Assert-Equal (Join-Path $repoRoot 'dashboard-react\package-lock.json') $plan.PackageLock 'Setup must use the exact npm lockfile'
Assert-Equal 'http://127.0.0.1:18765/react/' $plan.DashboardUrl 'Setup must open the local desktop dashboard'
Assert-Equal $false $plan.BuildPerformed 'PlanOnly must not build or install packages'
Assert-Equal $false $plan.ServicesStarted 'PlanOnly must not start Gateway or dashboard processes'

Write-Output 'PASS: setup plan is path-scoped, lockfile-based, and side-effect-free.'
