param(
    [string] $PythonCommand = "python",
    [string] $WorkDirectory = "",
    [string] $DistributionDirectory = ""
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot ".."))
$backendRoot = Join-Path $repoRoot "backend"
$specPath = Join-Path $backendRoot "repomind-backend.spec"
if ([string]::IsNullOrWhiteSpace($WorkDirectory)) {
    $WorkDirectory = Join-Path $repoRoot "backend-build"
}
if ([string]::IsNullOrWhiteSpace($DistributionDirectory)) {
    $DistributionDirectory = Join-Path $repoRoot "backend-dist"
}
$WorkDirectory = [System.IO.Path]::GetFullPath($WorkDirectory)
$DistributionDirectory = [System.IO.Path]::GetFullPath($DistributionDirectory)
$exePath = Join-Path $DistributionDirectory "repomind-backend.exe"

if (Test-Path $WorkDirectory) { Remove-Item -Recurse -Force $WorkDirectory }
if (Test-Path $DistributionDirectory) { Remove-Item -Recurse -Force $DistributionDirectory }
New-Item -ItemType Directory -Force -Path $WorkDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $DistributionDirectory | Out-Null
$buildStartedAt = Get-Date

Push-Location $backendRoot
try {
    & $PythonCommand -m PyInstaller --clean --noconfirm --workpath $WorkDirectory --distpath $DistributionDirectory $specPath
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}

if (-not (Test-Path $exePath -PathType Leaf)) { throw "Backend executable was not created: $exePath" }
$exe = Get-Item $exePath
if ($exe.Length -le 0) { throw "Backend executable is empty: $exePath" }
if ($exe.LastWriteTime -lt $buildStartedAt.AddSeconds(-2)) { throw "Backend executable is stale: $exePath" }
Write-Host "Backend build OK -> $exePath"
