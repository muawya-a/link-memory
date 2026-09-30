$ErrorActionPreference = 'Stop'

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$backupScript = Join-Path $repoRoot 'scripts\backup.ps1'
$backupSource = Get-Content -LiteralPath $backupScript -Raw
if ($backupSource -notmatch '(?m)^param\([\s\S]*\[switch\]\$PlanOnly') {
  throw 'backup.ps1 must expose a no-service PlanOnly mode before the test can invoke it.'
}
$planOnlyIndex = $backupSource.IndexOf('if ($PlanOnly)', [StringComparison]::Ordinal)
$directoryCreationIndex = $backupSource.IndexOf('New-Item', [StringComparison]::Ordinal)
$gatewayCallIndex = $backupSource.IndexOf('Invoke-RestMethod', [StringComparison]::Ordinal)
if ($planOnlyIndex -lt 0 -or $directoryCreationIndex -lt 0 -or $gatewayCallIndex -lt 0 -or
    $planOnlyIndex -gt $directoryCreationIndex -or $planOnlyIndex -gt $gatewayCallIndex) {
  throw 'PlanOnly must return before creating directories or contacting a Gateway.'
}

function Assert-Equal($Expected, $Actual, [string]$Message) {
  if ($Expected -ne $Actual) {
    throw "$Message (expected: '$Expected'; actual: '$Actual')"
  }
}

$sandbox = & $backupScript -PlanOnly
$staging = & $backupScript -Profile staging -PlanOnly

Assert-Equal 'sandbox' $sandbox.Profile 'Backup plan must default to sandbox'
Assert-Equal (Join-Path $repoRoot 'data') $sandbox.DataRoot 'Sandbox backup plan must use data'
Assert-Equal (Join-Path $repoRoot 'data\backups') $sandbox.BackupRoot 'Sandbox backup plan must use data backups'
Assert-Equal (Join-Path $repoRoot 'data\backup.log') $sandbox.Log 'Sandbox backup plan must use the sandbox log'
Assert-Equal 'http://127.0.0.1:18000/v1/backup' $sandbox.Endpoint 'Sandbox backup plan must target the sandbox Gateway'

Assert-Equal 'staging' $staging.Profile 'Explicit staging backup plan must retain its profile'
Assert-Equal (Join-Path $repoRoot 'staging-data') $staging.DataRoot 'Staging backup plan must use staging-data'
Assert-Equal (Join-Path $repoRoot 'staging-data\backups') $staging.BackupRoot 'Staging backup plan must use staging backups'
Assert-Equal (Join-Path $repoRoot 'staging-data\backup.log') $staging.Log 'Staging backup plan must use the staging log'
Assert-Equal 'http://127.0.0.1:28000/v1/backup' $staging.Endpoint 'Staging backup plan must target the staging Gateway'

Write-Output 'PASS: backup plan is profile-scoped without contacting a Gateway or creating files.'
