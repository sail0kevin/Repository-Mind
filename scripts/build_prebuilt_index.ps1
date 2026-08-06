# Build the deterministic prebuilt Demo index bundled into the frozen backend.
# Pipeline:
#   1) prepare a clean deterministic Demo git checkout (fixed identity/date -> commit 94d4aa63)
#   2) build the index with NO UI via `python -m service.launcher --index` (lexical mode)
#   3) write index.marker describing the fixture
# Output lands in backend/resources/prebuilt/ and is added to the PyInstaller
# one-file datas by backend/repomind-backend.spec (phase A2).
#
# Usage:
#   .\scripts\build_prebuilt_index.ps1 [-PythonCommand python]
param(
    [string] $PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot ".."))
$backendRoot = Join-Path $repoRoot "backend"
$outputDir = Join-Path $backendRoot "resources\prebuilt"
$databasePath = Join-Path $outputDir "repomind.sqlite3"
$markerPath = Join-Path $outputDir "index.marker"

if (Test-Path $outputDir) { Remove-Item -Recurse -Force $outputDir }
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

# 1) Deterministic demo checkout in a fresh temp directory.
$checkout = Join-Path ([System.IO.Path]::GetTempPath()) ("RepoMind-Prebuilt-Demo-" + [guid]::NewGuid().ToString("N"))
& (Join-Path $scriptRoot "prepare_demo_checkout.ps1") -OutputDir $checkout -Force
if ($LASTEXITCODE -ne 0) { throw "Preparing demo checkout failed" }

# 2) Build the index with no UI (lexical, no keys), synchronously.
$demoAlias = "RepoMind " + (-join [char[]](0x5185, 0x7F6E)) + " Demo"
Push-Location $backendRoot
try {
    & $PythonCommand -m service.launcher --index --repo $checkout --data-dir $outputDir --alias $demoAlias 2>&1 |
        ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { throw "Prebuilt index build failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}
if (-not (Test-Path $databasePath -PathType Leaf)) { throw "Prebuilt index missing: $databasePath" }

# Migration may leave a .backup-* copy; the bundled datas must carry only the index.
Get-ChildItem -LiteralPath $outputDir -Filter "repomind.sqlite3.backup-*" -ErrorAction SilentlyContinue |
    Remove-Item -Force

# 3) Record the fixture identity so docs and runtime marker checks stay honest.
$commitHash = git -C $checkout rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw "Reading demo commit hash failed" }
$marker = @{
    fixture_commit = $commitHash
    alias = $demoAlias
    mode = "lexical"
    files = 10
    built_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
} | ConvertTo-Json
[System.IO.File]::WriteAllText($markerPath, $marker, [System.Text.UTF8Encoding]::new($false))

Write-Host "Prebuilt index ready: $outputDir"
Write-Host "Prebuilt index commit: $commitHash"
