param()

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot ".."))
$packagePath = Join-Path $repoRoot "desktop\app\package.json"
$builderPath = Join-Path $repoRoot "desktop\app\electron-builder.yml"
$electronMainPath = Join-Path $repoRoot "desktop\app\electron\main.ts"
$backendMainPath = Join-Path $repoRoot "backend\service\main.py"

$packageJson = Get-Content $packagePath -Raw | ConvertFrom-Json
if ($packageJson.name -ne "repomind-desktop") { throw "Unexpected package name" }

$builderYaml = [System.IO.File]::ReadAllText($builderPath)
if (-not $builderYaml.Contains("appId: com.repomind.app")) { throw "Unexpected appId" }
if (-not $builderYaml.Contains("productName: RepoMind")) { throw "Unexpected productName" }

$electronMain = [System.IO.File]::ReadAllText($electronMainPath)
if (-not $electronMain.Contains('USER_DATA_BASENAME = "repomind-desktop"')) { throw "Unexpected userData basename" }
if (-not $electronMain.Contains('APP_ID = "com.repomind.app"')) { throw "Unexpected AppUserModelId" }

$backendMain = [System.IO.File]::ReadAllText($backendMainPath)
if (-not $backendMain.Contains('"/api/v1/health"')) { throw "Missing API v1 health endpoint" }
if (-not $backendMain.Contains('prefix="/api/v1"')) { throw "Missing API v1 router prefix" }

Write-Host "Identity contract OK: repomind-desktop / com.repomind.app / RepoMind / api-v1"
