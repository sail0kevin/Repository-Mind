$ErrorActionPreference = "Stop"

# Keep the scorer regression independent of Codex, MCP, and a target repository.
# It protects the case that caused the external A/B run to under-count correct
# answers: two annotated ranges in one file must use two reported ranges.
$runner = Join-Path (Split-Path -Parent $PSScriptRoot) "scripts\run_codex_location_ab.ps1"
$source = Get-Content -LiteralPath $runner -Raw
if ($source -notmatch "function Get-ReportedLocations") {
    throw "Location scorer helper is missing."
}

$answer = "src/lib/tools/tool-service.ts:29-32 src/lib/tools/tool-service.ts:47-53"
$pattern = [regex]::new("(?im)(?<path>[A-Za-z0-9_./\\-]+)\s*:\s*(?<start>\d+)(?:\s*[-:]\s*(?<end>\d+))?")
$locations = @()
foreach ($match in $pattern.Matches($answer)) {
    $locations += [pscustomobject]@{
        path = $match.Groups["path"].Value
        start = [int]$match.Groups["start"].Value
        end = [int]$match.Groups["end"].Value
        used = $false
    }
}
$goldStarts = @(29, 47)
foreach ($goldStart in $goldStarts) {
    $match = @($locations | Where-Object {
        -not $_.used -and $_.path -eq "src/lib/tools/tool-service.ts" -and $_.start -le $goldStart -and $_.end -ge $goldStart
    } | Select-Object -First 1)
    if ($match.Count -ne 1) {
        throw "Expected a distinct answer location for gold line $goldStart."
    }
    $match[0].used = $true
}
if (@($locations | Where-Object used).Count -ne 2) {
    throw "The scorer reused one answer location for multiple gold locations."
}
Write-Host "Location benchmark scorer regression passed."
