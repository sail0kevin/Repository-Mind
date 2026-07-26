param(
    [string]$RepoId,
    [string]$SnapshotId,
    [string]$Manifest,
    [string]$TaskFile,
    [string]$McpName = "repomind",
    [string]$McpPythonExe,
    [string]$McpBackendPath,
    [string]$McpDatabasePath,
    [string]$McpDataDir,
    [string]$Commit = "540ec0aac47fd648d1c31edd620a3860a5d515ef",
    [string]$RepositoryPath = ".",
    [string]$OutputDir = "e2e-artifacts/codex-location-ab-v2",
    [string]$CodexExe,
    [bool]$BypassSandbox = $true,
    [ValidateSet("all", "baseline", "treatment")][string]$Mode = "all",
    [string[]]$TaskId,
    [string]$Model = "gpt-5.6-terra",
    [ValidateSet("minimal", "low", "medium", "high")][string]$ReasoningEffort = "low",
    [int]$TimeoutSeconds = 120,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$output = Join-Path $root $OutputDir
New-Item -ItemType Directory -Force -Path $output | Out-Null
$resolvedMcpPythonExe = $McpPythonExe
if ([string]::IsNullOrWhiteSpace($resolvedMcpPythonExe)) {
    $resolvedMcpPythonExe = (Get-Command python -ErrorAction Stop).Source
}

if (-not [string]::IsNullOrWhiteSpace($Manifest)) {
    $resolvedManifest = (Resolve-Path $Manifest).Path
    $preflightScript = Join-Path $root "scripts\validate_location_benchmark.py"
    $preflightOutput = & $resolvedMcpPythonExe $preflightScript --manifest $resolvedManifest
    if ($LASTEXITCODE -ne 0) {
        throw "Benchmark manifest preflight failed. The target checkout and MCP index were not used."
    }
    $preflight = ($preflightOutput | ConvertFrom-Json)
    $RepoId = $preflight.repo_id
    $SnapshotId = $preflight.snapshot_id
    $Commit = $preflight.commit
    $RepositoryPath = $preflight.repository_path
    $McpDatabasePath = $preflight.database_path
    $McpDataDir = $preflight.data_dir
    $TaskFile = $preflight.task_file
    Write-Host "Validated isolated benchmark '$($preflight.benchmark_id)' with $($preflight.task_count) tasks."
} elseif ([string]::IsNullOrWhiteSpace($RepoId) -or [string]::IsNullOrWhiteSpace($SnapshotId)) {
    throw "Provide -RepoId and -SnapshotId, or provide a validated -Manifest."
}
$targetRepository = (Resolve-Path $RepositoryPath).Path
$resolvedMcpBackendPath = if ([string]::IsNullOrWhiteSpace($McpBackendPath)) {
    Join-Path $root "backend"
} else {
    (Resolve-Path $McpBackendPath).Path
}
$resolvedMcpDatabasePath = if ([string]::IsNullOrWhiteSpace($McpDatabasePath)) { $null } else {
    (Resolve-Path $McpDatabasePath).Path
}
$resolvedMcpDataDir = if ([string]::IsNullOrWhiteSpace($McpDataDir)) { $null } else {
    (Resolve-Path $McpDataDir).Path
}
if (($resolvedMcpDatabasePath -and -not $resolvedMcpDataDir) -or (-not $resolvedMcpDatabasePath -and $resolvedMcpDataDir)) {
    throw "-McpDatabasePath and -McpDataDir must be provided together so the MCP server uses an isolated index."
}
$mcpProfileName = $null
$mcpProfilePath = $null
if ($resolvedMcpDatabasePath) {
    # Codex parses command-line -c values as scalar values on Windows. A short
    # temporary profile preserves arrays and environment maps as real TOML.
    $mcpProfileName = "repomind-location-ab-$PID"
    $mcpProfilePath = Join-Path $env:USERPROFILE ".codex\$mcpProfileName.config.toml"
    $toml = @"
[mcp_servers."$McpName"]
command = '$resolvedMcpPythonExe'
args = ["-m", "service.mcp_server"]

[mcp_servers."$McpName".env]
PYTHONIOENCODING = "utf-8"
PYTHONPATH = '$resolvedMcpBackendPath'
REPOMIND_PATHS__DATABASE_PATH = '$resolvedMcpDatabasePath'
REPOMIND_PATHS__DATA_DIR = '$resolvedMcpDataDir'
"@
    [System.IO.File]::WriteAllText($mcpProfilePath, $toml, [System.Text.UTF8Encoding]::new($false))
}
$resolvedCodexExe = $CodexExe
if ([string]::IsNullOrWhiteSpace($resolvedCodexExe)) {
    $resolvedCodexExe = Get-ChildItem "$env:LOCALAPPDATA\npm-cache\_npx" -Recurse -Filter codex.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like "*codex-win32-x64*" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if ([string]::IsNullOrWhiteSpace($resolvedCodexExe) -or -not (Test-Path -LiteralPath $resolvedCodexExe -PathType Leaf)) {
    throw "Codex CLI executable was not found. Run 'npm exec --yes --package=@openai/codex -- codex --version' once or pass -CodexExe."
}
$actualCommit = (git -C $targetRepository rev-parse HEAD).Trim()
if ($actualCommit -ne $Commit) {
    throw "Expected repository commit $Commit, found $actualCommit. Use a clean fixed-commit clone."
}

$taskFile = if ([string]::IsNullOrWhiteSpace($TaskFile)) {
    Join-Path $root "examples/benchmarks/codex-location-ab-tasks.json"
} else {
    (Resolve-Path $TaskFile).Path
}
$tasks = Get-Content -LiteralPath $taskFile -Raw -Encoding utf8 | ConvertFrom-Json
$selectedTasks = @($tasks.tasks | Where-Object { -not $TaskId -or $TaskId -contains $_.id })
if ($selectedTasks.Count -eq 0) { throw "No benchmark task matched -TaskId." }
$selectedModes = if ($Mode -eq "all") { @("baseline", "treatment") } else { @($Mode) }

function Test-CompletedRun([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $hasUsage = Select-String -LiteralPath $Path -SimpleMatch '"type":"turn.completed"' -Quiet
    $hasAnswer = Select-String -LiteralPath $Path -SimpleMatch '"type":"agent_message"' -Quiet
    return [bool]($hasUsage -and $hasAnswer)
}

function Get-RunStatus([string]$Path, [string]$ErrorPath) {
    if (Test-CompletedRun $Path) { return "completed" }
    if (Test-Path -LiteralPath $ErrorPath -PathType Leaf) {
        if (Select-String -LiteralPath $ErrorPath -SimpleMatch "timed out" -Quiet) {
            return "timeout"
        }
    }
    if (Test-Path -LiteralPath $Path -PathType Leaf) { return "incomplete" }
    return "not_run"
}

function Get-ReportedLocations([string]$Answer) {
    $locations = @()
    $pattern = [regex]::new("(?im)(?<path>[A-Za-z0-9_./\\-]+)\s*:\s*(?<start>\d+)(?:\s*[-:]\s*(?<end>\d+))?")
    foreach ($match in $pattern.Matches($Answer)) {
        $start = [int]$match.Groups["start"].Value
        $end = if ($match.Groups["end"].Success) { [int]$match.Groups["end"].Value } else { $start }
        $locations += [pscustomobject]@{
            path = $match.Groups["path"].Value.Replace("\\", "/")
            start = $start
            end = $end
            used = $false
        }
    }
    return $locations
}

function Invoke-LocationRun([string]$Mode, $Task) {
    $common = "Read-only code-location task. Do not load skills or project instruction files. At commit $Commit, $($Task.query) Do not modify files. You must complete the task with a final answer after any search or MCP tool returns; never end the turn immediately after a tool call. Return only one or more locations in the form PATH:START_LINE-END_LINE, one per line."
    if ($Mode -eq "baseline") {
        $prompt = "$common Use only git grep or PowerShell search/read commands in this repository; RepoMind MCP is disabled and rg.exe is unavailable."
        # Isolated benchmark runs do not load the temporary MCP profile in the
        # baseline cohort. Adding an `enabled = false` override without a server
        # definition makes current Codex CLI versions reject the config.
        $extra = @()
    } else {
        if (-not $resolvedMcpDatabasePath) {
            throw "Treatment runs require -McpDatabasePath and -McpDataDir. Refusing to use an implicit user-level MCP index."
        }
        $prompt = "$common Do not use shell or local file reads. Use only the $McpName MCP tools with repo_id $RepoId and snapshot $SnapshotId."
        # The profile defines an MCP server that is bound to this exact index.
        # It is deleted when the benchmark ends and never changes global config.
        $extra = @("-p", $mcpProfileName)
    }
    $path = Join-Path $output "$Mode-$($Task.id).jsonl"
    if (-not $Force -and (Test-CompletedRun $path)) {
        Write-Host "Skipping completed run: $Mode/$($Task.id)"
        return
    }
    $promptPath = Join-Path $output "$Mode-$($Task.id).prompt.txt"
    $errorPath = Join-Path $output "$Mode-$($Task.id).stderr.log"
    Set-Content -LiteralPath $promptPath -Value $prompt -Encoding utf8
    $args = @("--disable", "plugins", "--disable", "remote_plugin", "--disable", "multi_agent", "--model", $Model,
        "--config", "model_reasoning_effort=`"$ReasoningEffort`"") +
        $extra + @("exec", "--ephemeral", "--json")
    # The Windows read-only sandbox cancels local stdio MCP child processes.
    # Both cohorts use the same process mode; their available tools remain
    # constrained by the prompt and the baseline MCP disable override.
    if ($BypassSandbox) {
        $args += "--dangerously-bypass-approvals-and-sandbox"
    } else {
        $args += @("--sandbox", "read-only")
    }
    $args += "-"
    $process = Start-Process -FilePath $resolvedCodexExe -ArgumentList $args -WorkingDirectory $targetRepository `
        -RedirectStandardInput $promptPath -RedirectStandardOutput $path -RedirectStandardError $errorPath `
        -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        # A killed Codex process can briefly retain the redirected stderr handle
        # on Windows. The timeout outcome is still valid even when the note
        # cannot be appended, so never let diagnostic logging abort the cohort.
        try {
            Add-Content -LiteralPath $errorPath -Value "Codex run timed out after $TimeoutSeconds seconds." -ErrorAction Stop
        } catch {
            Write-Warning "Timed out and could not append stderr log: $Mode/$($Task.id)"
        }
        Write-Warning "Timed out: $Mode/$($Task.id)"
        return
    }
    $process.Refresh()
    if ($process.ExitCode -ne 0) {
        if (Test-CompletedRun $path) {
            Write-Warning "Codex exited with code $($process.ExitCode) after a complete turn: $Mode/$($Task.id)"
        } else {
            Write-Warning "Incomplete Codex run: $Mode/$($Task.id); see $errorPath."
        }
    }
}

try {
    Push-Location $targetRepository
    try {
        foreach ($task in $selectedTasks) {
            foreach ($selectedMode in $selectedModes) {
                Invoke-LocationRun $selectedMode $task
            }
        }
    } finally {
        Pop-Location
    }
} finally {
    if ($mcpProfilePath -and (Test-Path -LiteralPath $mcpProfilePath -PathType Leaf)) {
        Remove-Item -LiteralPath $mcpProfilePath -Force
    }
}

$rows = @()
foreach ($task in $selectedTasks) {
    foreach ($mode in @("baseline", "treatment")) {
        $path = Join-Path $output "$mode-$($task.id).jsonl"
        $errorPath = Join-Path $output "$mode-$($task.id).stderr.log"
        $status = Get-RunStatus $path $errorPath
        if ($status -ne "completed") {
            $rows += [ordered]@{
                task_id = $task.id
                mode = $mode
                status = $status
                input_tokens = 0
                cached_input_tokens = 0
                output_tokens = 0
                source_characters_received = 0
                answer = ""
                location_checks = @()
                passed = $false
            }
            continue
        }
        $events = Get-Content -LiteralPath $path -Encoding utf8 | ForEach-Object {
            try { $_ | ConvertFrom-Json } catch { $null }
        }
        $usage = @($events | Where-Object { $_.type -eq "turn.completed" } | Select-Object -Last 1).usage
        $messages = @($events | Where-Object { $_.type -eq "item.completed" -and $_.item.type -eq "agent_message" })
        $text = ($messages | Select-Object -Last 1).item.text
        $normalized = ($text -replace "`r|`n", " ").Trim()
        $expectedLocations = @($task.expected_locations)
        if ($expectedLocations.Count -eq 0 -and $task.expected_path) {
            $expectedLocations = @([pscustomobject]@{
                path = $task.expected_path
                line_start = $task.line_start
                line_end = $task.line_end
            })
        }
        $reportedLocations = @(Get-ReportedLocations $normalized)
        $locationChecks = @()
        foreach ($expected in $expectedLocations) {
            $expectedPath = ([string]$expected.path).Replace("\\", "/")
            $goldStart = [int]$expected.line_start
            # A complete method range legitimately covers multiple annotated behavior
            # points inside that method. One reported location may therefore satisfy
            # more than one gold location; this benchmark evaluates code location, not
            # the number of lines repeated in the final answer.
            $reported = @(
                $reportedLocations | Where-Object {
                    $_.path -ieq $expectedPath -and $_.start -le $goldStart -and $_.end -ge $goldStart
                } | Select-Object -First 1
            )
            if ($reported.Count -gt 0) {
                $reportedStart = $reported[0].start
                $reportedEnd = $reported[0].end
                $locationPassed = $true
            } else {
                $reportedStart = 0
                $reportedEnd = 0
                $locationPassed = $false
            }
            $locationChecks += [ordered]@{
                path = $expected.path
                gold_start = $goldStart
                gold_end = [int]$expected.line_end
                reported_start = $reportedStart
                reported_end = $reportedEnd
                passed = $locationPassed
            }
        }
        $passed = $locationChecks.Count -gt 0 -and (@($locationChecks | Where-Object { -not $_.passed }).Count -eq 0)
        $sourceCharacters = 0
        foreach ($event in $events) {
            if ($event.type -eq "item.completed" -and $event.item.type -eq "command_execution") {
                $sourceCharacters += ([string]$event.item.aggregated_output).Length
            }
            if ($event.type -eq "item.completed" -and $event.item.type -eq "mcp_tool_call") {
                $content = $event.item.result.content
                foreach ($part in @($content)) { $sourceCharacters += ([string]$part.text).Length }
            }
        }
        $rows += [ordered]@{
            task_id = $task.id
            mode = $mode
            status = "completed"
            input_tokens = [int]($usage.input_tokens)
            cached_input_tokens = [int]($usage.cached_input_tokens)
            output_tokens = [int]($usage.output_tokens)
            source_characters_received = $sourceCharacters
            answer = $normalized
            location_checks = $locationChecks
            passed = $passed
        }
    }
}
$rows | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output "results.json") -Encoding utf8
$codexVersion = (& $resolvedCodexExe --version 2>$null | Select-Object -First 1).Trim()
$metadata = [ordered]@{
    benchmark_id = if ($preflight) { $preflight.benchmark_id } else { $null }
    codex_version = $codexVersion
    model = $Model
    reasoning_effort = $ReasoningEffort
    bypass_sandbox = $BypassSandbox
    timeout_seconds = $TimeoutSeconds
    modes = $selectedModes
    commit = $Commit
    repository_path = $targetRepository
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
}
$metadata | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $output "run-metadata.json") -Encoding utf8
Write-Host "Location A/B raw runs and results written to $output"
