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

& (Join-Path $scriptRoot "verify_identity_contract.ps1")
if (-not $?) { throw "Identity verification failed" }

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

Push-Location $backendRoot
try {
    & $PythonCommand -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Backend tests failed" }
}
finally {
    Pop-Location
}

& (Join-Path $scriptRoot "build_backend.ps1") -PythonCommand $PythonCommand
& (Join-Path $scriptRoot "smoke_backend.ps1") -ExePath $backendExe

Push-Location $desktopRoot
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    npm test
    if ($LASTEXITCODE -ne 0) { throw "Desktop tests failed" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Desktop build failed" }
    if (Test-Path $releaseRoot) { Remove-Item -Recurse -Force $releaseRoot }
    npm run package:dir
    if ($LASTEXITCODE -ne 0) { throw "Electron directory package failed" }

    $packagedBackend = Join-Path $releaseRoot "win-unpacked\resources\backend\repomind-backend.exe"
    if (-not (Test-Path $packagedBackend -PathType Leaf)) { throw "Packaged backend is missing" }
    $sourceHash = (Get-FileHash $backendExe -Algorithm SHA256).Hash
    $packagedHash = (Get-FileHash $packagedBackend -Algorithm SHA256).Hash
    if ($sourceHash -ne $packagedHash) { throw "Packaged backend does not match the current build" }
    & (Join-Path $scriptRoot "smoke_backend.ps1") -ExePath $packagedBackend

    if ($Release) {
        npm run package:release
        if ($LASTEXITCODE -ne 0) { throw "Windows release package failed" }
    }
}
finally {
    Pop-Location
}

$hashLines = Get-ChildItem $releaseRoot -File -ErrorAction SilentlyContinue | ForEach-Object {
    $fileHash = Get-FileHash $_.FullName -Algorithm SHA256
    "$($fileHash.Hash)  $($_.Name)"
}
if ($hashLines) { $hashLines | Set-Content (Join-Path $releaseRoot "SHA256SUMS.txt") -Encoding ascii }
Write-Host "RepoMind Windows package chain OK -> $releaseRoot"
