$ErrorActionPreference = "Stop"

# Keep the scorer regression independent of Codex, MCP, and a target repository.
# It protects the case that caused the external A/B run to under-count correct
# answers: one reported method range may cover two annotated behavior points.
$runner = Join-Path (Split-Path -Parent $PSScriptRoot) "scripts\run_codex_location_ab.ps1"
$source = Get-Content -LiteralPath $runner -Raw
if ($source -notmatch "function Get-ReportedLocations") {
    throw "Location scorer helper is missing."
}

$answer = "src/lib/tools/tool-service.ts:20-60"
$pattern = [regex]::new("(?im)(?<path>[A-Za-z0-9_./\\-]+)\s*:\s*(?<start>\d+)(?:\s*[-:]\s*(?<end>\d+))?")
$locations = @()
foreach ($match in $pattern.Matches($answer)) {
    $locations += [pscustomobject]@{
        path = $match.Groups["path"].Value
        start = [int]$match.Groups["start"].Value
        end = [int]$match.Groups["end"].Value
    }
}
$goldStarts = @(29, 47)
foreach ($goldStart in $goldStarts) {
    $match = @($locations | Where-Object {
        $_.path -eq "src/lib/tools/tool-service.ts" -and $_.start -le $goldStart -and $_.end -ge $goldStart
    } | Select-Object -First 1)
    if ($match.Count -ne 1) {
        throw "Expected a distinct answer location for gold line $goldStart."
    }
}
if ($locations.Count -ne 1) {
    throw "The fixture must use one broad answer range."
}
Write-Host "Location benchmark scorer regression passed."
