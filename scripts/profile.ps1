function Get-LinkProfilePlan {
  param(
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [ValidateSet('sandbox', 'staging')][string]$Profile = 'sandbox'
  )

  $root = [IO.Path]::GetFullPath($ProjectRoot)
  if ($Profile -eq 'staging') {
    $dataRoot = Join-Path $root 'staging-data'
    $gatewayPort = 28000
    $dashboardPort = 28765
  } else {
    $dataRoot = Join-Path $root 'data'
    $gatewayPort = 18000
    $dashboardPort = 18765
  }

  return [pscustomobject]@{
    Profile = $Profile
    ProjectRoot = $root
    DataRoot = $dataRoot
    Database = Join-Path $dataRoot 'sandbox.sqlite3'
    BackupRoot = Join-Path $dataRoot 'backups'
    InboxRoot = Join-Path $dataRoot 'inbox'
    ProcessedRoot = Join-Path $dataRoot 'processed'
    GatewayPort = $gatewayPort
    DashboardPort = $dashboardPort
    ProcessMarker = if ($Profile -eq 'staging') { '--link-memory-profile=staging' } else { '' }
  }
}

function Test-LinkProcessProfile {
  param(
    [string]$CommandLine,
    [ValidateSet('sandbox', 'staging')][string]$Profile = 'sandbox'
  )

  if (-not $CommandLine) { return $false }
  $markers = @([regex]::Matches($CommandLine, '(?i)(?:^|\s)(?:"(?<quoted>--link-memory-profile=[^"]+)"|(?<bare>--link-memory-profile=[^\s"]+))(?=\s|$)') |
    ForEach-Object {
      if ($_.Groups['quoted'].Success) { $_.Groups['quoted'].Value } else { $_.Groups['bare'].Value }
    })
  if ($Profile -eq 'sandbox') { return $markers.Count -eq 0 }
  return $markers.Count -eq 1 -and $markers[0] -ceq '--link-memory-profile=staging'
}

function Test-LinkScriptCommand {
  param(
    [string]$CommandLine,
    [string]$ScriptPath,
    [ValidateSet('sandbox', 'staging')][string]$Profile = 'sandbox'
  )

  if (-not (Test-LinkProcessProfile -CommandLine $CommandLine -Profile $Profile)) { return $false }
  try { $expected = [IO.Path]::GetFullPath($ScriptPath) } catch { return $false }
  $tokenPattern = '"(?<quoted>[^"]+)"|(?<bare>[^\s"]+)'
  $tokens = @([regex]::Matches($CommandLine, $tokenPattern) | ForEach-Object {
    if ($_.Groups['quoted'].Success) { $_.Groups['quoted'].Value } else { $_.Groups['bare'].Value }
  })
  # This project starts Python as `python.exe <script> <arguments>`. Only the
  # first argument is the executed script; later occurrences may be data.
  if ($tokens.Count -lt 2) { return $false }
  try { $candidatePath = [IO.Path]::GetFullPath($tokens[1]) } catch { return $false }
  return [String]::Equals($candidatePath, $expected, [StringComparison]::OrdinalIgnoreCase)
}
