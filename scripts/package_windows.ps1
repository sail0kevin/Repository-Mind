param(
    [string] $PythonCommand = "python",
    [switch] $Release
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot ".."))
$backendRoot = Join-Path $repoRoot "backend"
$desktopRoot = Join-Path $repoRoot "desktop\app"
$backendExe = Join-Path $repoRoot "backend-dist\repomind-backend.exe"
$releaseRoot = Join-Path $desktopRoot "release"
$currentStage = "initialization"

trap {
    $message = $_.Exception.Message
    $annotation = $message.Replace("%", "%25").Replace("`r", "%0D").Replace("`n", "%0A")
    Write-Host "::error title=RepoMind package stage failed ($currentStage)::$annotation"
    throw
}

$currentStage = "identity contract"
& (Join-Path $scriptRoot "verify_identity_contract.ps1")
if (-not $?) { throw "Identity verification failed" }

$currentStage = "Python FTS5 capability"
$ftsCheckPath = Join-Path ([System.IO.Path]::GetTempPath()) ("repomind-fts5-check-" + [guid]::NewGuid().ToString("N") + ".py")
$ftsCheck = @'
import sqlite3

connection = sqlite3.connect(":memory:")
connection.execute("CREATE VIRTUAL TABLE t USING fts5(content)")
connection.execute("INSERT INTO t VALUES ('needle')")
assert connection.execute("SELECT count(*) FROM t WHERE t MATCH 'needle'").fetchone()[0] == 1
print("FTS5 OK")
'@
try {
    # Windows PowerShell 5.1 may damage nested quotes passed through `python -c`, so use a temporary script.
    [System.IO.File]::WriteAllText($ftsCheckPath, $ftsCheck, [System.Text.UTF8Encoding]::new($false))
    & $PythonCommand $ftsCheckPath
    if ($LASTEXITCODE -ne 0) { throw "Build Python does not support FTS5" }
}
finally {
    Remove-Item -LiteralPath $ftsCheckPath -Force -ErrorAction SilentlyContinue
}

$currentStage = "backend tests"
Push-Location $backendRoot
try {
    & $PythonCommand -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Backend tests failed" }
}
finally {
    Pop-Location
}

$currentStage = "frozen backend build"
& (Join-Path $scriptRoot "build_backend.ps1") -PythonCommand $PythonCommand
$currentStage = "frozen backend HTTP smoke"
& (Join-Path $scriptRoot "smoke_backend.ps1") -ExePath $backendExe
$currentStage = "frozen backend MCP smoke"
& (Join-Path $scriptRoot "smoke_mcp.ps1") -ExePath $backendExe -PythonCommand $PythonCommand

function Invoke-NativeBuildStep {
    param(
        [scriptblock] $Command,
        [string] $FailureMessage
    )

    # Windows PowerShell 5.1 会把 npm/electron-builder 写入 stderr 的 warning 包装成
    # NativeCommandError。仅在原生命令执行期间放宽错误策略，最后仍严格检查退出码。
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Command 2>&1 | ForEach-Object { Write-Host $_ }
        $nativeExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($nativeExitCode -ne 0) { throw "$FailureMessage (exit code $nativeExitCode)" }
}

Push-Location $desktopRoot
try {
    $currentStage = "desktop dependency install"
    Invoke-NativeBuildStep { npm ci } "npm ci failed"
    $currentStage = "desktop tests"
    Invoke-NativeBuildStep { npm test } "Desktop tests failed"
    $currentStage = "desktop build"
    Invoke-NativeBuildStep { npm run build } "Desktop build failed"
    $currentStage = "Electron directory package"
    if (Test-Path $releaseRoot) { Remove-Item -Recurse -Force $releaseRoot }
    if ($env:REPOMIND_SKIP_WINDOWS_EXE_METADATA -eq "1") {
        # 网络受限的本地/CI 环境可跳过 PE 元数据编辑，避免下载 winCodeSign；正式 Release 不使用此开关。
        Invoke-NativeBuildStep {
            npx electron-builder --config electron-builder.yml --win dir --config.win.signAndEditExecutable=false
        } "Electron directory package failed"
    }
    else {
        Invoke-NativeBuildStep { npm run package:dir } "Electron directory package failed"
    }

    $currentStage = "packaged backend integrity"
    $packagedBackend = Join-Path $releaseRoot "win-unpacked\resources\backend\repomind-backend.exe"
    if (-not (Test-Path $packagedBackend -PathType Leaf)) { throw "Packaged backend is missing" }
    $sourceHash = (Get-FileHash $backendExe -Algorithm SHA256).Hash
    $packagedHash = (Get-FileHash $packagedBackend -Algorithm SHA256).Hash
    if ($sourceHash -ne $packagedHash) { throw "Packaged backend does not match the current build" }
    $currentStage = "packaged backend HTTP smoke"
    & (Join-Path $scriptRoot "smoke_backend.ps1") -ExePath $packagedBackend
    $currentStage = "packaged backend MCP smoke"
    & (Join-Path $scriptRoot "smoke_mcp.ps1") -ExePath $packagedBackend -PythonCommand $PythonCommand

    $currentStage = "packaged Demo integrity"
    $packagedDemo = Join-Path $releaseRoot "win-unpacked\resources\demo\repomind-demo"
    if (-not (Test-Path $packagedDemo -PathType Container)) { throw "Packaged demo is missing" }

    # 小白说明：-Force 能看见 .git 这类隐藏目录，-Recurse 会检查 Demo 的每一层子目录。
    $packagedDemoEntries = @(Get-ChildItem -LiteralPath $packagedDemo -Force -Recurse)
    $pollutedDemoEntries = @($packagedDemoEntries | Where-Object {
        $_.Name -eq "__pycache__" -or
        $_.Name -eq ".git" -or
        (-not $_.PSIsContainer -and $_.Extension -in @(".pyc", ".pyo"))
    })
    if ($pollutedDemoEntries.Count -gt 0) {
        $pollutedPaths = ($pollutedDemoEntries | ForEach-Object { $_.FullName }) -join "; "
        throw "Packaged demo contains cache, bytecode, or Git pollution: $pollutedPaths"
    }

    # 小白说明：只统计文件，不把文件夹算进去；干净的内置 Demo 必须始终恰好是 10 个文件。
    $packagedDemoFiles = @($packagedDemoEntries | Where-Object { -not $_.PSIsContainer })
    if ($packagedDemoFiles.Count -ne 10) {
        throw "Packaged demo must contain exactly 10 files, found $($packagedDemoFiles.Count)"
    }

    if ($Release) {
        $currentStage = "Windows release package"
        Invoke-NativeBuildStep { npm run package:release } "Windows release package failed"
    }
}
finally {
    Pop-Location
}

$currentStage = "release hashes"
$hashLines = Get-ChildItem $releaseRoot -File -ErrorAction SilentlyContinue | ForEach-Object {
    $fileHash = Get-FileHash $_.FullName -Algorithm SHA256
    "$($fileHash.Hash)  $($_.Name)"
}
if ($hashLines) { $hashLines | Set-Content (Join-Path $releaseRoot "SHA256SUMS.txt") -Encoding ascii }
Write-Host "RepoMind Windows package chain OK -> $releaseRoot"
