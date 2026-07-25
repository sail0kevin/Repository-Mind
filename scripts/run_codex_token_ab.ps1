param(
    [Parameter(Mandatory = $true)][string]$RepoId,
    [Parameter(Mandatory = $true)][string]$SnapshotId,
    [string]$McpName = "repomind",
    [string]$Commit = "32fd00f0c2b212e04de890d928722717766cd670",
    [string]$RepositoryPath = ".",
    [string]$OutputDir = "e2e-artifacts/codex-token-ab"
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

$tasks = @(
    @{ Id = "evidence-budget"; Limit = 120; Question = "explain how EvidenceBudget constrains evidence and name the two most relevant implementation files" },
    @{ Id = "main-agent-flow"; Limit = 150; Question = "summarize the Main Agent route-retrieve-tool-synthesis flow, including the maximum specialist-tool calls, and name the primary implementation file" },
    @{ Id = "route-impact"; Limit = 150; Question = "identify what code and tests are most likely affected if route_question behavior changes; give repository-relative paths" }
)

function Invoke-CodexRun([string]$Mode, [hashtable]$Task) {
    $common = "Read-only code-understanding task. Do not load skills or project instruction files. At commit $Commit, $($Task.Question). Answer in no more than $($Task.Limit) Chinese characters. Do not modify files."
    if ($Mode -eq "baseline") {
        $prompt = "$common Use only shell search/read commands in this repository; RepoMind MCP is disabled."
        $extra = @("-c", "mcp_servers.$McpName.enabled=false")
    } else {
        $prompt = "$common Do not use shell or local file reads. Use only the $McpName MCP tools with repo_id $RepoId and snapshot $SnapshotId."
        $extra = @()
    }
    $path = Join-Path $output "$Mode-$($Task.Id).jsonl"
    $args = @("-y", "@openai/codex", "--disable", "plugins", "--disable", "remote_plugin", "--disable", "multi_agent") +
        $extra + @("exec", "--ephemeral", "--json", "--sandbox", "read-only", $prompt)
    & npx @args | Set-Content -LiteralPath $path -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "Codex $Mode run failed for $($Task.Id)." }
}

Push-Location $targetRepository
try {
    foreach ($task in $tasks) {
        Invoke-CodexRun "baseline" $task
        Invoke-CodexRun "treatment" $task
    }
} finally {
    Pop-Location
}

Write-Host "Raw runs written to $output"
