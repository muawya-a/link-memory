$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$startScript = Join-Path $root 'scripts\start.ps1'
$fixturePath = Join-Path ([IO.Path]::GetTempPath()) ("link-memory-env-test-{0}.env" -f [guid]::NewGuid())
$protectedKeys = @(
  'MEMORY_GATEWAY_DATA', 'MEMORY_GATEWAY_DB', 'MEMORY_GATEWAY_BACKUP_DIR',
  'MEMORY_GATEWAY_INBOX', 'MEMORY_GATEWAY_PROCESSED',
  'MEMORY_GATEWAY_HOST', 'MEMORY_GATEWAY_PORT',
  'MEMORY_DASHBOARD_HOST', 'MEMORY_DASHBOARD_PORT',
  'MEMORY_GATEWAY_URL', 'MEMORY_GATEWAY_CORS_ORIGINS', 'MEMORY_GATEWAY_ALLOW_LAN_CORS'
)
$keysToCheck = $protectedKeys + @(
  'MODEL_PROVIDER', 'MODEL_NAME', 'MODEL_BASE_URL', 'MODEL_API_KEY',
  'OPENMEMORY_ENABLED', 'OPENMEMORY_URL', 'MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED'
)
$oldValues = @{}
foreach ($key in $keysToCheck) {
  $oldValues[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}

try {
  foreach ($key in $keysToCheck) {
    [Environment]::SetEnvironmentVariable($key, $null, 'Process')
  }

  $startSource = Get-Content -LiteralPath $startScript -Raw
  if ($startSource -notmatch 'function\s+Import-SandboxEnvironmentFile' -or
      $startSource -notmatch 'EnvironmentImportOnly') {
    throw 'Sandbox environment import helper/guard is missing; refusing to dot-source launcher.'
  }

  $fixtureLines = @(
    'MODEL_PROVIDER=synthetic-provider',
    'MODEL_NAME=synthetic-model',
    'MODEL_BASE_URL=https://provider.example.invalid/v1',
    'MODEL_API_KEY=synthetic-test-marker',
    'OPENMEMORY_ENABLED=true',
    'OPENMEMORY_URL=http://127.0.0.1:19001',
    'MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED=true',
    'MEMORY_GATEWAY_DATA=C:\outside\data',
    'MEMORY_GATEWAY_DB=C:\outside\gateway.sqlite3',
    'MEMORY_GATEWAY_BACKUP_DIR=C:\outside\backups',
    'MEMORY_GATEWAY_INBOX=C:\outside\inbox',
    'MEMORY_GATEWAY_PROCESSED=C:\outside\processed',
    'MEMORY_GATEWAY_HOST=0.0.0.0',
    'MEMORY_GATEWAY_PORT=18001',
    'MEMORY_DASHBOARD_HOST=0.0.0.0',
    'MEMORY_DASHBOARD_PORT=18766',
    'MEMORY_GATEWAY_URL=http://outside.example.invalid:18001',
    'MEMORY_GATEWAY_CORS_ORIGINS=https://outside.example.invalid',
    'MEMORY_GATEWAY_ALLOW_LAN_CORS=true'
  )
  Set-Content -LiteralPath $fixturePath -Value $fixtureLines -Encoding UTF8

  . $startScript -EnvironmentImportOnly -EnvironmentFile $fixturePath

  foreach ($key in $protectedKeys) {
    $actual = [Environment]::GetEnvironmentVariable($key, 'Process')
    if (-not [string]::IsNullOrEmpty($actual)) {
      throw "Protected key was imported: $key [$actual]"
    }
  }
  $expectedValues = @{
    MODEL_PROVIDER = 'synthetic-provider'
    MODEL_NAME = 'synthetic-model'
    MODEL_BASE_URL = 'https://provider.example.invalid/v1'
    MODEL_API_KEY = 'synthetic-test-marker'
    OPENMEMORY_ENABLED = 'true'
    OPENMEMORY_URL = 'http://127.0.0.1:19001'
    MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED = 'true'
  }
  foreach ($key in $expectedValues.Keys) {
    $actual = [Environment]::GetEnvironmentVariable($key, 'Process')
    if ($actual -cne $expectedValues[$key]) {
      throw "Optional key was not imported as expected: $key"
    }
  }
  Write-Output 'PASS: sandbox-critical environment overrides are ignored; optional model/provider settings are imported.'
}
finally {
  Remove-Item -LiteralPath $fixturePath -Force -ErrorAction SilentlyContinue
  foreach ($key in $keysToCheck) {
    [Environment]::SetEnvironmentVariable($key, $oldValues[$key], 'Process')
  }
}
