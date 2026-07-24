param(
    [Parameter(Mandatory = $true)] [string] $ExePath
)

$ErrorActionPreference = "Stop"
$exePath = [System.IO.Path]::GetFullPath($ExePath)
if (-not (Test-Path $exePath -PathType Leaf)) { throw "RepoMind executable not found: $exePath" }
if ([System.IO.Path]::GetFileName($exePath) -ne "RepoMind.exe" -or $exePath -notmatch "win-unpacked") {
    throw "Packaged E2E requires win-unpacked/RepoMind.exe"
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git is required for the built-in Demo" }

$projectRoot = Split-Path $PSScriptRoot -Parent
$desktopRoot = Join-Path $projectRoot "desktop\app"
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("RepoMind-E2E-" + [guid]::NewGuid().ToString("N"))
$userDataPath = Join-Path $tempRoot "user-data"
$exportDir = Join-Path $userDataPath "e2e-exports"
$runtimeArtifacts = Join-Path $tempRoot "runtime-artifacts"
$publicArtifacts = Join-Path $projectRoot "e2e-artifacts"
$testSucceeded = $false

function Copy-SanitizedLog([string] $Source, [string] $Destination) {
    if (-not (Test-Path $Source -PathType Leaf)) { return }
    $text = Get-Content $Source -Raw
    if ($null -eq $text) { return }
    $text = $text.Replace($tempRoot, "[TEMP_PATH]").Replace($userDataPath, "[USER_DATA]")
    $text = [regex]::Replace($text, '(?i)(api[_-]?key|token|authorization|password|secret)(\s*[:=]\s*)\S+', '$1$2[REDACTED]')
    if ($text.Length -gt 200000) { $text = $text.Substring($text.Length - 200000) }
    [System.IO.File]::WriteAllText($Destination, $text, [System.Text.UTF8Encoding]::new($false))
}

try {
    New-Item -ItemType Directory -Force -Path $exportDir, $runtimeArtifacts | Out-Null
    $environmentValues = @{
        REPOMIND_E2E = "1"
        REPOMIND_E2E_APP_PATH = $exePath
        REPOMIND_USER_DATA_PATH = $userDataPath
        REPOMIND_E2E_EXPORT_DIR = $exportDir
        REPOMIND_E2E_ARTIFACT_DIR = $runtimeArtifacts
        REPOMIND_LLM_API_KEY = ""
        REPOMIND_CHAT__API_KEY = ""
        REPOMIND_EMBEDDING_API_KEY = ""
        REPOMIND_EMBEDDING__API_KEY = ""
        OPENAI_API_KEY = ""
        HTTP_PROXY = ""
        HTTPS_PROXY = ""
        ALL_PROXY = ""
        NO_PROXY = "127.0.0.1,localhost"
    }
    foreach ($item in $environmentValues.GetEnumerator()) {
        [System.Environment]::SetEnvironmentVariable($item.Key, $item.Value, "Process")
    }

    Push-Location $desktopRoot
    try {
        npm run test:e2e:packaged
        if ($LASTEXITCODE -ne 0) { throw "Packaged Electron E2E failed with exit code $LASTEXITCODE" }
    }
    finally { Pop-Location }
    $testSucceeded = $true
    Write-Host "Packaged Electron E2E OK"
}
finally {
    # 不扫描或强制终止未知进程；Electron 正式桥接负责关闭本次启动的后端。
    # 若仍有残留，保留诊断信息并让后续人工/隔离 CI 处理，绝不影响用户其他程序。
    $remaining = @()
    if (-not $testSucceeded) {
        New-Item -ItemType Directory -Force -Path $publicArtifacts | Out-Null
        $playwrightResults = Join-Path $desktopRoot "test-results"
        if (Test-Path $playwrightResults) {
            $destination = Join-Path $publicArtifacts "test-results"
            if (Test-Path $destination) { Remove-Item -Recurse -Force $destination }
            Copy-Item -Recurse -Force $playwrightResults $destination
            Get-ChildItem -Path $playwrightResults -Filter "error-context.md" -Recurse -File | ForEach-Object {
                $diagnostic = Get-Content $_.FullName -Raw
                $diagnostic = $diagnostic.Replace($tempRoot, "[TEMP_PATH]").Replace($userDataPath, "[USER_DATA]")
                $diagnostic = [regex]::Replace($diagnostic, '(?i)(api[_-]?key|token|authorization|password|secret)(\s*[:=]\s*)\S+', '$1$2[REDACTED]')
                Write-Host "=== Playwright failure context ==="
                Write-Host $diagnostic
                $annotation = $diagnostic.Replace("%", "%25").Replace("`r", "%0D").Replace("`n", "%0A")
                if ($annotation.Length -gt 6000) { $annotation = $annotation.Substring(0, 6000) }
                Write-Host "::error title=Packaged Electron E2E failure::$annotation"
            }
        }
        Copy-SanitizedLog (Join-Path $userDataPath "repomind-backend-logs.txt") (Join-Path $publicArtifacts "backend-redacted.log")
        Copy-SanitizedLog (Join-Path $runtimeArtifacts "renderer-console.txt") (Join-Path $publicArtifacts "renderer-console.txt")
    }

    if ($remaining.Count -gt 0) { Write-Warning "E2E reported remaining processes; leaving diagnostic artifacts." }

    foreach ($key in @(
        "REPOMIND_E2E", "REPOMIND_E2E_APP_PATH", "REPOMIND_USER_DATA_PATH",
        "REPOMIND_E2E_EXPORT_DIR", "REPOMIND_E2E_ARTIFACT_DIR", "REPOMIND_LLM_API_KEY",
        "REPOMIND_CHAT__API_KEY", "REPOMIND_EMBEDDING_API_KEY", "REPOMIND_EMBEDDING__API_KEY",
        "OPENAI_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"
    )) { [System.Environment]::SetEnvironmentVariable($key, $null, "Process") }

    if (Test-Path $tempRoot) { Remove-Item -Recurse -Force $tempRoot -ErrorAction SilentlyContinue }
}
