param(
  [Parameter(Mandatory = $true)][string]$StageRoot,
  [Parameter(Mandatory = $true)][string]$PythonRuntimeRoot
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$StageRoot = [IO.Path]::GetFullPath($StageRoot)
$TempRoots = @([IO.Path]::GetTempPath())
if ($env:RUNNER_TEMP) { $TempRoots += $env:RUNNER_TEMP }
$isSafeStagePath = $false
foreach ($tempRoot in $TempRoots) {
  $tempPrefix = [IO.Path]::GetFullPath($tempRoot).TrimEnd([char[]]@('\', '/')) + [IO.Path]::DirectorySeparatorChar
  if ($StageRoot.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    $isSafeStagePath = $true
    break
  }
}
if (-not $isSafeStagePath) {
  throw 'StageRoot must be inside the current user temporary directory or the GitHub Actions runner temporary directory.'
}

$PythonRuntimeRoot = [IO.Path]::GetFullPath($PythonRuntimeRoot)
if (-not (Test-Path -LiteralPath (Join-Path $PythonRuntimeRoot 'python.exe') -PathType Leaf)) {
  throw 'The extracted embeddable Python runtime must contain python.exe.'
}
if (-not (Get-ChildItem -LiteralPath $PythonRuntimeRoot -Filter 'python*._pth' -File)) {
  throw 'The extracted embeddable Python runtime is missing its ._pth file.'
}
if (-not (Test-Path -LiteralPath (Join-Path $PythonRuntimeRoot 'LICENSE.txt') -PathType Leaf)) {
  throw 'The extracted Python runtime is missing its license notice.'
}
$BuiltDashboard = Join-Path $ProjectRoot 'dashboard\react'
if (-not (Test-Path -LiteralPath (Join-Path $BuiltDashboard 'index.html') -PathType Leaf) -or
    -not (Get-ChildItem -LiteralPath (Join-Path $BuiltDashboard 'assets') -Filter '*.js' -File)) {
  throw 'The prebuilt dashboard is missing. Run npm ci and npm run build in dashboard-react first.'
}

if (Test-Path -LiteralPath $StageRoot) { throw "StageRoot already exists; choose a fresh temporary directory: $StageRoot" }
New-Item -ItemType Directory -Path $StageRoot -Force | Out-Null

$excludedSegments = @(
  '.git', '.venv', '.venv-reranker', 'node_modules', '__pycache__',
  'data', 'staging-data', 'backups', 'inbox', 'processed', 'exports',
  'private', 'secrets'
)
$excludedExtensions = @('.bak', '.backup', '.db', '.har', '.jsonl', '.key', '.log', '.p12', '.pem', '.pfx', '.sqlite', '.sqlite3', '.tmp', '.trace')
function Copy-InstallSourceDirectory([string]$Name) {
  $source = Join-Path $ProjectRoot $Name
  $destination = Join-Path $StageRoot $Name
  $sourcePrefix = [IO.Path]::GetFullPath($source).TrimEnd([char[]]@('\', '/')) + [IO.Path]::DirectorySeparatorChar
  New-Item -ItemType Directory -Path $destination -Force | Out-Null
  foreach ($file in Get-ChildItem -LiteralPath $source -File -Recurse -Force) {
    if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
    $relativePath = $file.FullName.Substring($sourcePrefix.Length)
    $segments = $relativePath -split '[\\/]'
    $excluded = $false
    foreach ($segment in $segments) {
      if ($excludedSegments -contains $segment) { $excluded = $true; break }
    }
    if ($excluded) { continue }
    if ($file.Name -match '^\.env(?:\..*)?$' -and $file.Name -ine '.env.example') { continue }
    if ($excludedExtensions -contains $file.Extension.ToLowerInvariant()) { continue }
    $target = Join-Path $destination $relativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target
  }
}

foreach ($directory in @('dashboard', 'deployment', 'gateway', 'scripts')) {
  Copy-InstallSourceDirectory $directory
}
$runtimeDestination = Join-Path $StageRoot 'runtime'
New-Item -ItemType Directory -Path $runtimeDestination -Force | Out-Null
Copy-Item -Path (Join-Path $PythonRuntimeRoot '*') -Destination $runtimeDestination -Recurse -Force
$pythonPathFile = Get-ChildItem -LiteralPath $runtimeDestination -Filter 'python*._pth' -File | Select-Object -First 1
if (-not $pythonPathFile) { throw 'The staged Python runtime is missing its ._pth file.' }
$pythonPathEntries = @(Get-Content -LiteralPath $pythonPathFile.FullName)
if ($pythonPathEntries -notcontains '..') {
  Add-Content -LiteralPath $pythonPathFile.FullName -Value '..' -Encoding Ascii
}
if ($pythonPathEntries -notcontains '..\gateway') {
  Add-Content -LiteralPath $pythonPathFile.FullName -Value '..\gateway' -Encoding Ascii
}

$rootFiles = @(
  '.env.example', 'CLIENT_INTEGRATIONS.md', 'DEPENDENCY_LICENSE_INVENTORY.csv',
  'IMPORTING_DATA.md', 'LICENSE', 'OPTIONAL_INTEGRATIONS.md', 'PRIVACY.md',
  'PROVIDER_API_DISCOVERY.md', 'README.md', 'SECURITY.md', 'SOURCE_PROVENANCE.md',
  'Start-Link-Memory.ps1', 'Start-Link-Memory.vbs', 'Stop-Link-Memory.vbs', 'THIRD_PARTY_NOTICES.md'
)
$rootFiles += @(Get-ChildItem -LiteralPath $ProjectRoot -File -Filter 'requirements*.txt' | ForEach-Object Name)
foreach ($file in $rootFiles | Sort-Object -Unique) {
  $source = Join-Path $ProjectRoot $file
  if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "Required staged file is missing: $file"
  }
  Copy-Item -LiteralPath $source -Destination $StageRoot
}

Write-Output "Staged Link Memory for Windows installer: $StageRoot"

