param()

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$verifier = Join-Path $scriptRoot "verify_release_hashes.ps1"
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("RepoMind-ReleaseHashes-" + [guid]::NewGuid().ToString("N"))
$releaseDirectory = Join-Path $tempRoot "release"
$manifestPath = Join-Path $releaseDirectory "SHA256SUMS.txt"

function Write-Manifest {
    $rootPrefix = $releaseDirectory.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    $lines = @(
        Get-ChildItem -LiteralPath $releaseDirectory -File -Recurse |
            Where-Object { $_.FullName -ne $manifestPath } |
            ForEach-Object {
                $relativePath = $_.FullName.Substring($rootPrefix.Length).Replace('\', '/')
                $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
                [PSCustomObject]@{ RelativePath = $relativePath; Line = "$hash  $relativePath" }
            } |
            Sort-Object RelativePath |
            ForEach-Object { $_.Line }
    )
    $lines | Set-Content -LiteralPath $manifestPath -Encoding ascii
}

function Assert-Rejected {
    param(
        [scriptblock] $Action,
        [string] $ExpectedMessage
    )

    try {
        & $Action
    }
    catch {
        if ($_.Exception.Message -notmatch $ExpectedMessage) {
            throw "Expected rejection matching '$ExpectedMessage', got: $($_.Exception.Message)"
        }
        return
    }
    throw "Expected release checksum verification to reject input matching '$ExpectedMessage'"
}

try {
    New-Item -ItemType Directory -Force -Path (Join-Path $releaseDirectory "nested") | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $releaseDirectory "artifact.txt"), "stable artifact", [Text.UTF8Encoding]::new($false))
    [System.IO.File]::WriteAllText((Join-Path $releaseDirectory "nested\asset.bin"), "nested artifact", [Text.UTF8Encoding]::new($false))

    Write-Manifest
    & $verifier -ReleaseDirectory $releaseDirectory

    [System.IO.File]::AppendAllText((Join-Path $releaseDirectory "artifact.txt"), " tampered", [Text.UTF8Encoding]::new($false))
    Assert-Rejected { & $verifier -ReleaseDirectory $releaseDirectory } "mismatched=artifact.txt"

    Write-Manifest
    [System.IO.File]::WriteAllText((Join-Path $releaseDirectory "new-file.txt"), "not listed", [Text.UTF8Encoding]::new($false))
    Assert-Rejected { & $verifier -ReleaseDirectory $releaseDirectory } "missing=new-file.txt"

    Set-Content -LiteralPath $manifestPath -Encoding ascii -Value ("{0}  ../outside.txt" -f ("0" * 64))
    Assert-Rejected { & $verifier -ReleaseDirectory $releaseDirectory } "Unsafe checksum manifest path"

    Write-Host "Release checksum verifier tests OK"
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
