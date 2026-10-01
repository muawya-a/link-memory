$ErrorActionPreference = 'SilentlyContinue'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartScript = Join-Path $Root 'scripts\start.ps1'
$GatewayScript = Join-Path $Root 'gateway\server.py'

if (Test-Path -LiteralPath $GatewayScript) {
  $gatewayProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine.ToLowerInvariant().Contains($GatewayScript.ToLowerInvariant())
  })
  foreach ($process in $gatewayProcesses) {
    try {
      $started = (Get-Process -Id ([int]$process.ProcessId) -ErrorAction Stop).StartTime
      if ((Get-Item -LiteralPath $GatewayScript).LastWriteTime -gt $started) {
        Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction SilentlyContinue
      }
    } catch {}
  }
}

if (Test-Path -LiteralPath $StartScript) {
  $pwsh = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source
  if (-not $pwsh) { $pwsh = (Get-Command powershell.exe -ErrorAction Stop).Source }
  $startArguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', $StartScript)
  $bundledPython = Join-Path $Root 'runtime\python.exe'
  if (Test-Path -LiteralPath $bundledPython -PathType Leaf) {
    $startArguments += @('-PythonPath', $bundledPython)
  }
  Start-Process -FilePath $pwsh -ArgumentList $startArguments -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
}

Start-Process 'http://127.0.0.1:18765/react/#overview'
