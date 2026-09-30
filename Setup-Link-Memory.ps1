param(
  [string]$PythonPath,
  [switch]$PlanOnly,
  [switch]$BuildOnly
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$PackageLock = Join-Path $ProjectRoot 'dashboard-react\package-lock.json'
$DashboardUrl = 'http://127.0.0.1:18765/react/'

if (-not (Test-Path -LiteralPath $PackageLock -PathType Leaf)) {
  throw 'The dashboard npm lockfile is missing. Restore dashboard-react/package-lock.json before setup.'
}

if ($PlanOnly) {
  return [pscustomobject]@{
    ProjectRoot = $ProjectRoot
    PackageLock = $PackageLock
    DashboardUrl = $DashboardUrl
    BuildPerformed = $false
    ServicesStarted = $false
  }
}

function Resolve-SetupPython([string]$ExplicitPath) {
  if ($ExplicitPath) {
    $candidates = @($ExplicitPath)
  } else {
    $candidates = @(Get-Command python.exe -All -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandType -eq 'Application' -and $_.Source } |
      ForEach-Object { $_.Source })
  }

  foreach ($candidate in $candidates) {
    if (-not $candidate -or [IO.Path]::GetExtension($candidate) -ine '.exe') { continue }
    if ([IO.Path]::GetFileName($candidate) -ine 'python.exe') { continue }
    if ($candidate -match '(?i)(?:^|[\\/])Microsoft[\\/]WindowsApps(?:[\\/]|$)') { continue }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    $versionOutput = & $candidate --version 2>&1
    if ($LASTEXITCODE -ne 0 -or [string]$versionOutput -notmatch '^Python\s+(\d+)\.(\d+)') { continue }
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    if (($major -gt 3) -or ($major -eq 3 -and $minor -ge 10)) { return $candidate }
  }

  throw 'Python 3.10 or later was not found. Install it from python.org, then rerun setup; or pass -PythonPath with the full installed python.exe path.'
}

function Resolve-SetupCommand([string]$Name, [int]$MinimumMajor) {
  $command = Get-Command $Name -ErrorAction SilentlyContinue
  if (-not $command -or -not $command.Source) {
    throw "$Name was not found. Install Node.js 20 or later from nodejs.org, then rerun setup."
  }
  $versionOutput = & $command.Source --version 2>&1
  if ($LASTEXITCODE -ne 0 -or [string]$versionOutput -notmatch 'v?(\d+)\.') {
    throw "Could not read the installed $Name version."
  }
  if ([int]$Matches[1] -lt $MinimumMajor) {
    throw "$Name $MinimumMajor or later is required; found $versionOutput."
  }
  return $command.Source
}

$Python = Resolve-SetupPython $PythonPath
$null = Resolve-SetupCommand 'node.exe' 20
$Npm = Get-Command 'npm.cmd' -ErrorAction SilentlyContinue
if (-not $Npm -or -not $Npm.Source) {
  throw 'npm.cmd was not found. Install Node.js 20 or later from nodejs.org, then rerun setup.'
}

Write-Output 'Installing dashboard dependencies from the pinned npm lockfile...'
Push-Location (Join-Path $ProjectRoot 'dashboard-react')
try {
  & $Npm.Source ci
  if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE." }
  & $Npm.Source run build
  if ($LASTEXITCODE -ne 0) { throw "Dashboard build failed with exit code $LASTEXITCODE." }
} finally {
  Pop-Location
}

if ($BuildOnly) {
  Write-Output 'Dashboard build completed; local services were not started.'
  return
}

Write-Output 'Starting the local Gateway and dashboard...'
& (Join-Path $ProjectRoot 'scripts\start.ps1') -PythonPath $Python
Start-Process $DashboardUrl
Write-Output "Link Memory is opening at $DashboardUrl"
