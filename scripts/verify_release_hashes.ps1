param(
    [string] $ReleaseDirectory = "desktop/app/release",
    [string] $ChecksumFile = "SHA256SUMS.txt"
)

$ErrorActionPreference = "Stop"
$releaseDirectory = [System.IO.Path]::GetFullPath($ReleaseDirectory)
if (-not (Test-Path -LiteralPath $releaseDirectory -PathType Container)) {
    throw "Release directory not found: $releaseDirectory"
}

$checksumPath = Join-Path $releaseDirectory $ChecksumFile
if (-not (Test-Path -LiteralPath $checksumPath -PathType Leaf)) {
    throw "Checksum manifest not found: $checksumPath"
}

$releasePrefix = $releaseDirectory.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
$manifestEntries = @{}
$lineNumber = 0
foreach ($line in Get-Content -LiteralPath $checksumPath) {
    $lineNumber++
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    if ($line -notmatch '^(?<hash>[A-Fa-f0-9]{64})  (?<path>[^\r\n]+)$') {
        throw "Invalid checksum manifest entry at line $lineNumber"
    }

    $relativePath = $Matches.path.Replace('\', '/')
    if ($relativePath.StartsWith('/') -or $relativePath -match '(^|/)\.\.(/|$)' -or $relativePath -eq $ChecksumFile) {
        throw "Unsafe checksum manifest path at line ${lineNumber}: $relativePath"
    }
    if ($manifestEntries.ContainsKey($relativePath)) {
        throw "Duplicate checksum manifest path: $relativePath"
    }
    $manifestEntries[$relativePath] = $Matches.hash.ToUpperInvariant()
}

if ($manifestEntries.Count -eq 0) { throw "Checksum manifest is empty: $checksumPath" }

$actualEntries = @{}
Get-ChildItem -LiteralPath $releaseDirectory -File -Recurse | ForEach-Object {
    if ($_.FullName -eq $checksumPath) { return }
    $relativePath = $_.FullName.Substring($releasePrefix.Length).Replace('\', '/')
    $actualEntries[$relativePath] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToUpperInvariant()
}

$missing = @($actualEntries.Keys | Where-Object { -not $manifestEntries.ContainsKey($_) } | Sort-Object)
$unexpected = @($manifestEntries.Keys | Where-Object { -not $actualEntries.ContainsKey($_) } | Sort-Object)
$mismatched = @($actualEntries.Keys | Where-Object {
    $manifestEntries.ContainsKey($_) -and $manifestEntries[$_] -ne $actualEntries[$_]
} | Sort-Object)

if ($missing.Count -or $unexpected.Count -or $mismatched.Count) {
    $parts = @()
    if ($missing.Count) { $parts += "missing=$($missing -join ', ')" }
    if ($unexpected.Count) { $parts += "unexpected=$($unexpected -join ', ')" }
    if ($mismatched.Count) { $parts += "mismatched=$($mismatched -join ', ')" }
    throw "Release checksum verification failed: $($parts -join '; ')"
}

Write-Host "Release checksum verification OK: files=$($actualEntries.Count) manifest=$checksumPath"
