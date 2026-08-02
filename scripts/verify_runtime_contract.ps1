param(
    [string] $PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot ".."))
$desktopRoot = Join-Path $repoRoot "desktop\app"

function Get-RequiredText {
    param([string] $Path)

    $value = (Get-Content -LiteralPath $Path -Raw).Trim()
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Required version declaration is empty: $Path"
    }
    return $value
}

$expectedNode = Get-RequiredText (Join-Path $repoRoot ".nvmrc")
$expectedPython = Get-RequiredText (Join-Path $repoRoot ".python-version")
$packageJson = Get-Content -LiteralPath (Join-Path $desktopRoot "package.json") -Raw | ConvertFrom-Json
if ($packageJson.packageManager -notmatch '^npm@(?<version>\d+\.\d+\.\d+)$') {
    throw "package.json must declare an exact npm packageManager version"
}
$expectedNpm = $Matches.version

$actualNode = (& node --version).Trim().TrimStart('v')
if ($LASTEXITCODE -ne 0) { throw "Unable to run node --version" }
if ($actualNode -ne $expectedNode) {
    throw "Node.js version mismatch: expected $expectedNode from .nvmrc, found $actualNode"
}

$actualNpm = (& npm --version).Trim()
if ($LASTEXITCODE -ne 0) { throw "Unable to run npm --version" }
if ($actualNpm -ne $expectedNpm) {
    throw "npm version mismatch: expected $expectedNpm from package.json, found $actualNpm"
}

$actualPython = (& $PythonCommand -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0) { throw "Unable to run $PythonCommand" }
if ($actualPython -ne $expectedPython) {
    throw "Python version mismatch: expected $expectedPython from .python-version, found $actualPython"
}

Write-Host "Runtime contract OK: Python $actualPython / Node.js $actualNode / npm $actualNpm"
