# Prepare a clean, deterministic built-in Demo git checkout.
# Mirrors desktop/app/electron/main.ts prepareDemoRepository():
#   1) copy only the 10 synthetic source files from the release manifest
#      (never dev residue like __pycache__)
#   2) create a git commit with isolated HOME/USERPROFILE + fixed identity
#      + fixed timestamp
# The same 10 files + fixed identity/date + fixed message yield a
# deterministic commit hash (current fixture: 94d4aa63), reused by the
# --index build smoke and the prebuilt-index packaging step.
#
# Usage:
#   .\scripts\prepare_demo_checkout.ps1 -OutputDir <target-dir> [-Force]
# Prints the target checkout path and the deterministic commit hash.
param(
    [Parameter(Mandatory = $true)] [string] $OutputDir,
    [switch] $Force
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot ".."))
$demoSource = Join-Path $repoRoot "demo\repomind-demo"

# Keep in sync with DEMO_FIXTURE_FILES in desktop/app/electron/main.ts.
$demoFixtureFiles = @(
    "OLD_REPOMIND_DEMO_README.md",
    "config.json",
    "expected/showcase.json",
    "repomind_demo/__init__.py",
    "repomind_demo/app/__init__.py",
    "repomind_demo/app/main.py",
    "repomind_demo/notifier.py",
    "repomind_demo/security_examples.py",
    "repomind_demo/service.py",
    "tests/test_greeting.py"
)

$outputDir = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path $outputDir) {
    if ($Force) { Remove-Item -Recurse -Force $outputDir }
    else { throw "Target directory already exists: $outputDir (use -Force to overwrite)" }
}
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

# Copy only the release-manifest files so dev residue cannot change the fixed commit.
foreach ($relativePath in $demoFixtureFiles) {
    $source = Join-Path $demoSource ($relativePath -replace "/", [System.IO.Path]::DirectorySeparatorChar)
    if (-not (Test-Path $source -PathType Leaf)) { throw "Built-in demo resource missing: $source" }
    $destination = Join-Path $outputDir ($relativePath -replace "/", [System.IO.Path]::DirectorySeparatorChar)
    New-Item -ItemType Directory -Force -Path (Split-Path $destination -Parent) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

# Isolate HOME/USERPROFILE so local git config or global ignore cannot change the result.
$isolatedHome = Join-Path $outputDir ".git-home"
New-Item -ItemType Directory -Force -Path $isolatedHome | Out-Null
$gitEnv = @{
    "HOME" = $isolatedHome
    "USERPROFILE" = $isolatedHome
    "XDG_CONFIG_HOME" = Join-Path $isolatedHome "xdg"
    "GIT_CONFIG_NOSYSTEM" = "1"
    "GIT_AUTHOR_NAME" = "RepoMind Demo"
    "GIT_AUTHOR_EMAIL" = "demo@repomind.local"
    "GIT_COMMITTER_NAME" = "RepoMind Demo"
    "GIT_COMMITTER_EMAIL" = "demo@repomind.local"
    "GIT_AUTHOR_DATE" = "2026-01-01T00:00:00Z"
    "GIT_COMMITTER_DATE" = "2026-01-01T00:00:00Z"
}

function Invoke-GitForDemo {
    param([string[]] $Arguments)
    $envSnapshot = @{}
    Get-ChildItem Env: | ForEach-Object { $envSnapshot[$_.Name] = $_.Value }
    try {
        foreach ($key in $gitEnv.Keys) { Set-Item -Path "Env:$key" -Value $gitEnv[$key] }
        git @Arguments
        if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
    }
    finally {
        foreach ($key in $gitEnv.Keys) {
            if ($envSnapshot.ContainsKey($key)) { Set-Item -Path "Env:$key" -Value $envSnapshot[$key] }
            else { Remove-Item -Path "Env:$key" -ErrorAction SilentlyContinue }
        }
    }
}

Push-Location $outputDir
try {
    Invoke-GitForDemo -Arguments @("init", "--initial-branch=main")
    Invoke-GitForDemo -Arguments @("-c", "core.autocrlf=false", "-c", "core.filemode=false", "-c", "commit.gpgsign=false", "add", "--all")
    Invoke-GitForDemo -Arguments @("-c", "core.autocrlf=false", "-c", "core.filemode=false", "-c", "commit.gpgsign=false", "commit", "-m", "Create RepoMind built-in demo")
    $commitHash = git rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { throw "Reading demo commit hash failed" }
}
finally {
    Pop-Location
}

Write-Host "Demo checkout ready: $outputDir"
Write-Host "Demo commit: $commitHash"
