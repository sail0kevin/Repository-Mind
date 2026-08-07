param(
    [string] $BackendExe = "",
    [switch] $DryRun,
    [switch] $Force
)

# RepoMind MCP post-install registration (Windows PowerShell 5.1).
# Pure ASCII on purpose: UTF-8 scripts without BOM are mis-read as GBK on
# Chinese Windows, so Chinese text is emitted via [char] code points.
#
# Writes three user-config files (merge, never overwrite whole file):
#   %USERPROFILE%\.claude.json          top-level mcpServers.repomind (stdio)
#   %USERPROFILE%\.claude\settings.json permissions.allow += "mcp__repomind__*"
#   %USERPROFILE%\.codex\config.toml    [mcp_servers.repomind]
#
# Behaviour mirrors scripts/setup_mcp.py so source and installer users get
# the same config. The Inno Setup installer runs this with -Force so a
# reinstall updates the stored command path to the current install dir.
# Unlike the .py version this script always exits 0 (best-effort): it writes
# a status file next to itself ({app}\registration-status.txt) which the
# installer reads to decide the honest text on the finish page.
$ErrorActionPreference = "Stop"

function Write-Zh {
    param([int[]] $Codes)
    -join ($Codes | ForEach-Object { [char] $_ })
}

function Get-Timestamp {
    Get-Date -Format "yyyyMMddTHHmmss"
}

function Backup-File {
    param([string] $Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    $backupPath = "$Path.bak-$(Get-Timestamp)"
    Copy-Item -LiteralPath $Path -Destination $backupPath -Force
    Write-Host "  backed-up original -> $backupPath"
}

function Read-JsonOrEmpty {
    # Returns an empty PSCustomObject when the file is missing/blank so all
    # later merge code follows one path. Throws on invalid JSON on purpose.
    param([string] $Path)
    if (-not (Test-Path -LiteralPath $Path)) { return [PSCustomObject] @{} }
    $raw = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    if ([string]::IsNullOrWhiteSpace($raw)) { return [PSCustomObject] @{} }
    return ($raw | ConvertFrom-Json -ErrorAction Stop)
}

function Atomic-WriteJson {
    # Write to a temp file in the same directory then move over the target,
    # so a crash mid-write can never leave a half-written config file.
    param([string] $Path, [object] $Data)
    $dir = [System.IO.Path]::GetDirectoryName($Path)
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $tmp = Join-Path $dir (([System.IO.Path]::GetFileName($Path)) + ".tmp-" + [guid]::NewGuid().ToString("N"))
    try {
        $json = $Data | ConvertTo-Json -Depth 50
        [System.IO.File]::WriteAllText($tmp, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
        # The temp file is fully written above, so moving it into place can
        # never leave a half-written config behind (PS 5.1 .NET Framework has
        # no atomic-overwrite File.Move overload; Move-Item -Force suffices).
        Move-Item -LiteralPath $tmp -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
    }
}

function Format-TomlString {
    # Escape a string into a TOML literal (backslash and double quote).
    param([string] $Value)
    return '"' + $Value.Replace('\', '\\').Replace('"', '\"') + '"'
}

function Format-CodexBlock {
    # NOTE: the parameter is named ArgList, not Args, because $Args is an
    # automatic variable in PowerShell and would be empty if used as a name.
    param([string] $Command, [string[]] $ArgList, [hashtable] $EnvMap)
    $argItems = ($ArgList | ForEach-Object { Format-TomlString $_ }) -join ", "
    $envItems = ($EnvMap.GetEnumerator() | Sort-Object Name | ForEach-Object {
        (Format-TomlString $_.Name) + " = " + (Format-TomlString $_.Value)
    }) -join ", "
    # required is always false: a dead server must not take Codex down with it.
    $lines = @(
        "[mcp_servers.repomind]"
        "command = $(Format-TomlString $Command)"
        "args = [$argItems]"
        "env = { $envItems }"
        'default_tools_approval_mode = "auto"'
        "enabled = true"
        "required = false"
    )
    return ($lines -join "`n")
}

function Test-JsonObjectRoot {
    # Fail (return $false) when the root is an array or a scalar; we only
    # ever merge into JSON objects, and must not rewrite a weird file.
    param([object] $Data)
    return ($Data -is [System.Management.Automation.PSCustomObject])
}

function Merge-ClaudeJson {
    param([string] $Path, [string] $Name, [object] $Entry)
    $data = Read-JsonOrEmpty -Path $Path
    if (-not (Test-JsonObjectRoot $data)) {
        Write-Host "  ERROR: $Path is not a JSON object; refusing to touch it."
        return "failed"
    }
    if ($null -eq $data.mcpServers) {
        $data | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject] @{})
    }
    $servers = $data.mcpServers
    if ($servers -is [System.Array] -or $servers -is [string]) {
        Write-Host "  ERROR: $Path mcpServers is not an object; refusing to touch it."
        return "failed"
    }
    $hasName = $servers.PSObject.Properties.Name -contains $Name
    if ($hasName -and -not $Force) {
        Write-Host "  " (Write-Zh @(0x8DF3, 0x8FC7)) ": $Path already has mcpServers.$Name"
        return "skipped"
    }
    Backup-File -Path $Path
    if ($hasName) {
        $servers.$Name = $Entry
    }
    else {
        $servers | Add-Member -NotePropertyName $Name -NotePropertyValue $Entry
    }
    Atomic-WriteJson -Path $Path -Data $data
    Write-Host "  wrote $Path -> mcpServers.$Name"
    return "written"
}

function Merge-ClaudeSettings {
    param([string] $Path, [string] $AllowEntry)
    $data = Read-JsonOrEmpty -Path $Path
    if (-not (Test-JsonObjectRoot $data)) {
        Write-Host "  ERROR: $Path is not a JSON object; refusing to touch it."
        return "failed"
    }
    if ($null -eq $data.permissions) {
        $data | Add-Member -NotePropertyName "permissions" -NotePropertyValue ([PSCustomObject] @{})
    }
    $perms = $data.permissions
    if ($perms -is [System.Array] -or $perms -is [string]) {
        Write-Host "  ERROR: $Path permissions is not an object; refusing to touch it."
        return "failed"
    }
    if ($null -eq $perms.allow) {
        $perms | Add-Member -NotePropertyName "allow" -NotePropertyValue @()
    }
    $allow = $perms.allow
    if ($allow -is [string]) { $allow = @($allow) }
    if ($allow -contains $AllowEntry) {
        Write-Host "  " (Write-Zh @(0x8DF3, 0x8FC7)) ": $Path already has permissions.allow '$AllowEntry'"
        return "skipped"
    }
    Backup-File -Path $Path
    $perms.allow = @($allow) + $AllowEntry
    Atomic-WriteJson -Path $Path -Data $data
    Write-Host "  wrote $Path -> permissions.allow += '$AllowEntry'"
    return "written"
}

function Merge-CodexConfig {
    param([string] $Path, [string] $Section, [string] $Block)
    $lines = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $Path) {
        $content = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
        foreach ($piece in ($content -split "`r?`n")) { [void] $lines.Add($piece) }
    }
    $sectionRegex = '^\s*\[' + [regex]::Escape($Section) + '\]\s*$'
    $exists = $false
    foreach ($line in $lines) { if ($line -match $sectionRegex) { $exists = $true; break } }
    if ($exists -and -not $Force) {
        Write-Host "  " (Write-Zh @(0x8DF3, 0x8FC7)) ": $Path already has [$Section]"
        return "skipped"
    }
    Backup-File -Path $Path
    if ($exists) {
        # Drop the old section (from its header up to the next [header]).
        $out = [System.Collections.Generic.List[string]]::new()
        $inSection = $false
        foreach ($line in $lines) {
            if ($line -match '^\s*\[') {
                if ($inSection) { $inSection = $false }
                if ($line -match $sectionRegex) { $inSection = $true; continue }
            }
            if (-not $inSection) { [void] $out.Add($line) }
        }
        $lines = $out
    }
    while ($lines.Count -gt 0 -and [string]::IsNullOrWhiteSpace($lines[$lines.Count - 1])) {
        $lines.RemoveAt($lines.Count - 1)
    }
    $result = ($lines -join "`n")
    if ($result -ne "") { $result += "`n" }
    $result += "`n" + $Block + "`n"
    $dir = [System.IO.Path]::GetDirectoryName($Path)
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    [System.IO.File]::WriteAllText($Path, $result, [System.Text.UTF8Encoding]::new($false))
    Write-Host "  wrote $Path -> [$Section]"
    return "written"
}

# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($BackendExe)) {
    # Installed layout: {app}\scripts\register_repomind.ps1 -> {app}\repomind-backend.exe
    $appRoot = Split-Path -Parent $PSScriptRoot
    $BackendExe = Join-Path $appRoot "repomind-backend.exe"
}
$BackendExe = [System.IO.Path]::GetFullPath($BackendExe)
if (-not (Test-Path -LiteralPath $BackendExe -PathType Leaf)) {
    Write-Host "WARNING: backend exe not found at $BackendExe; registration will still write the entry."
}

$claudeJson = Join-Path $env:USERPROFILE ".claude.json"
$claudeSettings = Join-Path $env:USERPROFILE ".claude\settings.json"
$codexConfig = Join-Path $env:USERPROFILE ".codex\config.toml"

Write-Host "RepoMind MCP registration -> command = $BackendExe --mcp"
Write-Host "  targets:"
Write-Host "    $claudeJson"
Write-Host "    $claudeSettings"
Write-Host "    $codexConfig"

if ($DryRun) {
    Write-Host "[dry-run] nothing was written. (Restart the Claude Code / Codex session for it to take effect.)"
    exit 0
}

$entry = [ordered] @{
    command = $BackendExe
    args    = @("--mcp")
    env     = [ordered] @{ PYTHONIOENCODING = "utf-8" }
}
$envMap = @{ PYTHONIOENCODING = "utf-8" }
$block = Format-CodexBlock -Command $BackendExe -ArgList @("--mcp") -EnvMap $envMap

$results = [ordered] @{}
$results["claude_json"] = Merge-ClaudeJson -Path $claudeJson -Name "repomind" -Entry $entry
$results["claude_settings"] = Merge-ClaudeSettings -Path $claudeSettings -AllowEntry "mcp__repomind__*"
$results["codex_config"] = Merge-CodexConfig -Path $codexConfig -Section "mcp_servers.repomind" -Block $block

# Status file for the installer finish page. Lives in {app} (script's parent).
$statusPath = Join-Path (Split-Path -Parent $PSScriptRoot) "registration-status.txt"
$overall = "ok"
foreach ($k in $results.Keys) { if ($results[$k] -eq "failed") { $overall = "failed" } }
$statusLines = @("overall=$overall")
foreach ($k in @("claude_json", "claude_settings", "codex_config")) {
    $statusLines += "$k=$($results[$k])"
}
[System.IO.File]::WriteAllLines($statusPath, $statusLines, [System.Text.UTF8Encoding]::new($false))

Write-Host "  status -> $statusPath (overall=$overall)"
Write-Host (Write-Zh @(0x5B8C, 0x6210)) ". Please restart the Claude Code / Codex session for it to take effect (MCP server only loads at session start)."
exit 0
