param(
    [string] $ISCCPath = "",
    [string] $Version = "0.1.0"
)

# Builds the RepoMind Windows Setup installer with Inno Setup.
#
# Usage:
#   .\scripts\build_installer.ps1                                   # auto-detect ISCC.exe
#   .\scripts\build_installer.ps1 -ISCCPath "C:\...\ISCC.exe" -Version "0.2.0"
#
# Requires: backend-dist\repomind-backend.exe (produced by build_backend.ps1,
# carries the prebuilt demo index from build_prebuilt_index.ps1).
#
# ISCC.exe detection order:
#   1. $env:INNO_SETUP_ISCC            (GitHub Actions sets this)
#   2. "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
#   3. "C:\Program Files\Inno Setup 6\ISCC.exe"
#
# For a portable/unmanaged build (e.g. an ISCC extracted without admin rights),
# pass -ISCCPath "C:\...\ISCC.exe" explicitly. Machine-specific locations must
# never be hard-coded here so the public repo does not leak local paths.
#
# The .iss is compiled with 6.0.5 on the dev machine and is compatible with
# any newer Inno Setup 6.x (CI ships the latest).
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot ".."))
$issPath = Join-Path $repoRoot "installer\RepoMind_Setup.iss"

if ([string]::IsNullOrWhiteSpace($ISCCPath)) {
    $candidates = @(
        $env:INNO_SETUP_ISCC,
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $ISCCPath = $candidate
            break
        }
    }
}

if ([string]::IsNullOrWhiteSpace($ISCCPath) -or -not (Test-Path -LiteralPath $ISCCPath -PathType Leaf)) {
    throw "ISCC.exe not found. Install Inno Setup or pass -ISCCPath."
}

# ISCC expands AppVersion from the /D#define; the .iss reads #MyAppVersion.
& $ISCCPath $issPath "/DMyAppVersion=$Version"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed (exit $LASTEXITCODE)" }

$outputExe = Join-Path $repoRoot "installer-output\RepoMindSetup-$Version.exe"
if (-not (Test-Path -LiteralPath $outputExe -PathType Leaf)) {
    throw "Expected installer output missing: $outputExe"
}
Write-Host "RepoMind installer OK -> $outputExe"
