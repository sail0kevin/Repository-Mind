param(
    [Parameter(Mandatory = $true)][string]$RepoId,
    [Parameter(Mandatory = $true)][string]$SnapshotId,
    [string]$McpName = "repomind",
    [string]$Commit = "32fd00f0c2b212e04de890d928722717766cd670",
    [string]$RepositoryPath = ".",
    [string]$OutputDir = "e2e-artifacts/codex-location-ab"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$output = Join-Path $root $OutputDir
New-Item -ItemType Directory -Force -Path $output | Out-Null
$targetRepository = (Resolve-Path $RepositoryPath).Path
$actualCommit = (git -C $targetRepository rev-parse HEAD).Trim()
if ($actualCommit -ne $Commit) {
    throw "Expected repository commit $Commit, found $actualCommit. Use a clean fixed-commit clone."
}

$taskFile = Join-Path $root "examples/benchmarks/codex-location-ab-tasks.json"
$tasks = Get-Content -LiteralPath $taskFile -Raw -Encoding utf8 | ConvertFrom-Json

function Invoke-LocationRun([string]$Mode, $Task) {
    $common = "Read-only code-location task. Do not load skills or project instruction files. At commit $Commit, $($Task.query) Do not modify files."
    if ($Mode -eq "baseline") {
        $prompt = "$common Use only shell search/read commands in this repository; RepoMind MCP is disabled. Return only PATH:START_LINE-END_LINE."
        $extra = @("-c", "mcp_servers.$McpName.enabled=false")
    } else {
        $prompt = "$common Do not use shell or local file reads. Use only the $McpName MCP tools with repo_id $RepoId and snapshot $SnapshotId. Return only PATH:START_LINE-END_LINE."
        $extra = @()
    }
    $path = Join-Path $output "$Mode-$($Task.id).jsonl"
    $args = @("-y", "@openai/codex", "--disable", "plugins", "--disable", "remote_plugin", "--disable", "multi_agent") +
        $extra + @("exec", "--ephemeral", "--json", "--sandbox", "read-only", $prompt)
    & npx @args | Set-Content -LiteralPath $path -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "Codex $Mode run failed for $($Task.id)." }
}

Push-Location $targetRepository
try {
    foreach ($task in $tasks.tasks) {
        Invoke-LocationRun "baseline" $task
        Invoke-LocationRun "treatment" $task
    }
} finally {
    Pop-Location
}

$rows = @()
foreach ($task in $tasks.tasks) {
    foreach ($mode in @("baseline", "treatment")) {
        $path = Join-Path $output "$mode-$($task.id).jsonl"
        $events = Get-Content -LiteralPath $path -Encoding utf8 | ForEach-Object {
            try { $_ | ConvertFrom-Json } catch { $null }
        }
        $usage = @($events | Where-Object { $_.type -eq "turn.completed" } | Select-Object -Last 1).usage
        $messages = @($events | Where-Object { $_.type -eq "item.completed" -and $_.item.type -eq "agent_message" })
        $text = ($messages | Select-Object -Last 1).item.text
        $normalized = ($text -replace "`r|`n", " ").Trim()
        $passed = $normalized.Contains($task.expected_path) -and
            [regex]::IsMatch($normalized, "(?<!\d)$($task.line_start)(?:\s*[-:]\s*\d+)?")
        $rows += [ordered]@{
            task_id = $task.id
            mode = $mode
            input_tokens = [int]($usage.input_tokens)
            cached_input_tokens = [int]($usage.cached_input_tokens)
            output_tokens = [int]($usage.output_tokens)
            answer = $normalized
            passed = $passed
        }
    }
}
$rows | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output "results.json") -Encoding utf8
Write-Host "Location A/B raw runs and results written to $output"
