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
    # Windows PowerShell 5.1 会把 PyInstaller 写入 stderr 的普通 INFO 日志包装成
    # NativeCommandError。仅在执行原生命令期间临时允许该非终止错误，最终仍以真实退出码判断。
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $PythonCommand -m PyInstaller --clean --noconfirm --workpath $WorkDirectory --distpath $DistributionDirectory $specPath 2>&1 |
            ForEach-Object { Write-Host $_ }
        $pyInstallerExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($pyInstallerExitCode -ne 0) { throw "PyInstaller failed with exit code $pyInstallerExitCode" }
}
finally {
    Pop-Location
}

if (-not (Test-Path $exePath -PathType Leaf)) { throw "Backend executable was not created: $exePath" }
$exe = Get-Item $exePath
if ($exe.Length -le 0) { throw "Backend executable is empty: $exePath" }
if ($exe.LastWriteTime -lt $buildStartedAt.AddSeconds(-2)) { throw "Backend executable is stale: $exePath" }
Write-Host "Backend build OK -> $exePath"
