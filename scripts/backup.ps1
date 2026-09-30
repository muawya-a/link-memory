param(
  [ValidateSet('sandbox', 'staging')][string]$Profile = 'sandbox',
  [switch]$PlanOnly
)

$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
. (Join-Path $PSScriptRoot 'profile.ps1')
$profilePlan = Get-LinkProfilePlan -ProjectRoot $Root -Profile $Profile
$Log = Join-Path $profilePlan.DataRoot 'backup.log'
$Endpoint = "http://127.0.0.1:$($profilePlan.GatewayPort)/v1/backup"

if ($PlanOnly) {
  return [pscustomobject]@{
    Profile = $Profile
    DataRoot = $profilePlan.DataRoot
    BackupRoot = $profilePlan.BackupRoot
    Log = $Log
    Endpoint = $Endpoint
  }
}

New-Item -ItemType Directory -Force -Path $profilePlan.BackupRoot | Out-Null
try {
  $result = Invoke-RestMethod $Endpoint -Method Post -ContentType 'application/json' -Body '{}' -TimeoutSec 30
  Add-Content -LiteralPath $Log -Value ("{0} {1}" -f (Get-Date -Format s), ($result | ConvertTo-Json -Compress)) -Encoding utf8
} catch {
  Add-Content -LiteralPath $Log -Value ("{0} backup failed: {1}" -f (Get-Date -Format s), $_.Exception.Message) -Encoding utf8
  exit 1
}
