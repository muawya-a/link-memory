$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$DataDir = Join-Path $Root 'data'
$LogFile = Join-Path $DataDir 'autostart.log'
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

function Write-Log([string]$Message) {
  Add-Content -LiteralPath $LogFile -Value ("{0} {1}" -f (Get-Date -Format s), $Message) -Encoding utf8
}

function Test-SandboxService([string]$ScriptPath) {
  $needle = [IO.Path]::GetFullPath($ScriptPath).ToLowerInvariant()
  return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine.ToLowerInvariant().Contains($needle)
  }).Count -gt 0
}

Write-Log 'Sandbox automatic startup started'
try {
  & (Join-Path $PSScriptRoot 'start.ps1') 2>&1 | ForEach-Object { Write-Log $_ }
} catch {
  Write-Log ("Sandbox startup failed: " + $_.Exception.Message)
}

# Watch only this copy's Gateway and dashboard processes. Never probe Ollama,
# MCP clients, provider ports, Docker, or the original project's endpoints.
$managed = @(
  (Join-Path $Root 'gateway\server.py'),
  (Join-Path $Root 'dashboard\serve.py'),
  (Join-Path $Root 'scripts\watch_inbox.py')
)
while ($true) {
  $missing = @($managed | Where-Object { -not (Test-SandboxService $_) })
  if ($missing.Count -gt 0) {
    Write-Log 'A sandbox process is missing; requesting sandbox-only recovery'
    try {
      & (Join-Path $PSScriptRoot 'start.ps1') 2>&1 | ForEach-Object { Write-Log $_ }
    } catch {
      Write-Log ("Sandbox recovery failed: " + $_.Exception.Message)
    }
  }
  Start-Sleep -Seconds 30
}
