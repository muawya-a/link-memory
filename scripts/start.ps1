param(
  [switch]$EnvironmentImportOnly,
  [string]$EnvironmentFile,
  [ValidateSet('sandbox', 'staging')][string]$Profile = 'sandbox',
  [string]$PythonPath,
  [switch]$PlanOnly
)

function Test-LinkWindowsAppsAlias([string]$Path) {
  return $Path -match '(?i)(?:^|[\\/])Microsoft[\\/]WindowsApps(?:[\\/]|$)'
}

function Resolve-LinkPythonExecutable {
  param(
    [string]$ExplicitPath,
    [string[]]$CandidatePaths,
    [scriptblock]$CommandResolver,
    [scriptblock]$PathExists
  )

  if (-not $PathExists) {
    $PathExists = { param($Candidate) Test-Path -LiteralPath $Candidate -PathType Leaf }
  }

  if ($ExplicitPath) {
    if ([IO.Path]::GetExtension($ExplicitPath) -ine '.exe') {
      throw "PythonPath must point to an installed python.exe executable: '$ExplicitPath'."
    }
    if ([IO.Path]::GetFileName($ExplicitPath) -ine 'python.exe') {
      throw "PythonPath must point to python.exe, not another executable: '$ExplicitPath'."
    }
    if (Test-LinkWindowsAppsAlias $ExplicitPath) {
      throw "PythonPath points to the Microsoft Store WindowsApps alias, not an installed interpreter: '$ExplicitPath'. Install Python or specify the full path to an installed python.exe."
    }
    if (-not (& $PathExists $ExplicitPath)) {
      throw "The Python interpreter specified by PythonPath does not exist: '$ExplicitPath'. Install Python or specify the full path to an installed python.exe."
    }
    return $ExplicitPath
  }

  if (-not $CandidatePaths) {
    if (-not $CommandResolver) {
      $CommandResolver = { Get-Command python.exe -All -ErrorAction SilentlyContinue }
    }
    $CandidatePaths = @(& $CommandResolver | Where-Object {
      $_.CommandType -eq 'Application' -and $_.Source
    } | ForEach-Object { $_.Source })
  }

  foreach ($candidate in $CandidatePaths) {
    if (-not $candidate -or [IO.Path]::GetExtension($candidate) -ine '.exe') { continue }
    if (Test-LinkWindowsAppsAlias $candidate) { continue }
    if (& $PathExists $candidate) { return $candidate }
  }

  throw 'No installed Python interpreter was found. Install Python, or rerun with -PythonPath followed by the full path to an installed python.exe.'
}

function Import-SandboxEnvironmentFile([string]$Path) {
  $sandboxCriticalVariables = @(
    'MEMORY_GATEWAY_DATA', 'MEMORY_GATEWAY_DB', 'MEMORY_GATEWAY_BACKUP_DIR',
    'MEMORY_GATEWAY_INBOX', 'MEMORY_GATEWAY_PROCESSED',
    'MEMORY_GATEWAY_HOST', 'MEMORY_GATEWAY_PORT',
    'MEMORY_DASHBOARD_HOST', 'MEMORY_DASHBOARD_PORT',
    'MEMORY_GATEWAY_URL', 'MEMORY_GATEWAY_CORS_ORIGINS', 'MEMORY_GATEWAY_ALLOW_LAN_CORS'
  )

  Get-Content -LiteralPath $Path | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
      $name = $Matches[1]
      if ($sandboxCriticalVariables -notcontains $name) {
        [Environment]::SetEnvironmentVariable($name, $Matches[2], 'Process')
      }
    }
  }
}

if ($EnvironmentImportOnly) {
  if (-not $EnvironmentFile) { throw 'EnvironmentFile is required in import-only mode.' }
  Import-SandboxEnvironmentFile -Path $EnvironmentFile
  return
}

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'profile.ps1')
$plan = Get-LinkProfilePlan -ProjectRoot $Root -Profile $Profile
if ($PlanOnly) { return $plan }
$Python = Resolve-LinkPythonExecutable -ExplicitPath $PythonPath
$DataDir = $plan.DataRoot
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$LogDir = Join-Path $DataDir 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Never inherit provider credentials or personal Codex paths from the parent
# shell. Only a deliberately created sandbox .env may opt into a provider.
$isolatedVariables = @(
  'MODEL_API_KEY', 'OPENROUTER_API_KEY', 'GRAPHITI_OPENROUTER_API_KEY',
  'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY',
  'DEEPSEEK_API_KEY', 'XAI_API_KEY', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
  'MEMORY_GATEWAY_API_KEY', 'CODEX_HOME', 'CODEX_LEGACY_NOTIFY',
  'MEMORY_GATEWAY_EGRESS_ALLOWLIST', 'MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED',
  'MEMORY_GATEWAY_NEO4J_ALLOWLIST',
  'MEMORY_GATEWAY_URL', 'OPENROUTER_URL', 'OLLAMA_URL', 'RERANKER_URL',
  'OPENMEMORY_URL', 'GRAPHITI_URL', 'MEMPALACE_URL'
)
foreach ($name in $isolatedVariables) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }

$env:MEMORY_GATEWAY_HOST = '127.0.0.1'
$env:MEMORY_GATEWAY_PORT = [string]$plan.GatewayPort
$env:MEMORY_GATEWAY_DATA = $DataDir
$env:MEMORY_GATEWAY_DB = $plan.Database
$env:MEMORY_GATEWAY_BACKUP_DIR = $plan.BackupRoot
$env:MEMORY_GATEWAY_INBOX = $plan.InboxRoot
$env:MEMORY_GATEWAY_PROCESSED = $plan.ProcessedRoot
$env:MEMORY_DASHBOARD_HOST = '127.0.0.1'
$env:MEMORY_DASHBOARD_PORT = [string]$plan.DashboardPort
$env:MEMORY_GATEWAY_URL = "http://127.0.0.1:$($plan.GatewayPort)"
$env:MEMORY_GATEWAY_CORS_ORIGINS = "http://127.0.0.1:$($plan.DashboardPort),http://localhost:$($plan.DashboardPort)"
$env:MEMORY_GATEWAY_ALLOW_LAN_CORS = 'false'
# Read only this sandbox's optional configuration, after clearing inherited
# values. The distributed copy contains .env.example, never a copied .env.
# Optional integrations stay off unless their documented settings are enabled
# in this checkout's private .env. Inherited shell credentials remain cleared.
$EnvFile = Join-Path $Root '.env'
if ($Profile -eq 'sandbox' -and (Test-Path -LiteralPath $EnvFile)) {
  Import-SandboxEnvironmentFile -Path $EnvFile
}

$Gateway = if ($Profile -eq 'staging') { Join-Path $Root 'scripts\staging_gateway.py' } else { Join-Path $Root 'gateway\server.py' }
$Dashboard = if ($Profile -eq 'staging') { Join-Path $Root 'scripts\staging_dashboard.py' } else { Join-Path $Root 'dashboard\serve.py' }
function Test-SandboxProcess([string]$ScriptPath) {
  return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    Test-LinkScriptCommand -CommandLine $_.CommandLine -ScriptPath $ScriptPath -Profile $Profile
  }).Count -gt 0
}

$processArguments = if ($plan.ProcessMarker) { @($plan.ProcessMarker) } else { @() }
if (-not (Test-SandboxProcess $Gateway)) {
  Start-Process -FilePath $Python -ArgumentList (@('"' + $Gateway + '"') + $processArguments) -WorkingDirectory $Root -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir 'gateway.stdout.log') `
    -RedirectStandardError (Join-Path $LogDir 'gateway.stderr.log') | Out-Null
}

if (-not (Test-SandboxProcess $Dashboard)) {
  Start-Process -FilePath $Python -ArgumentList (@('"' + $Dashboard + '"') + $processArguments) -WorkingDirectory (Join-Path $Root 'dashboard') -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir 'dashboard.stdout.log') `
    -RedirectStandardError (Join-Path $LogDir 'dashboard.stderr.log') | Out-Null
}

Write-Output "$Profile Gateway: http://127.0.0.1:$($plan.GatewayPort) (optional integrations depend on private .env settings)"
Write-Output "$Profile Dashboard: http://127.0.0.1:$($plan.DashboardPort)/"
Write-Output "$Profile file inbox watcher: disabled"

