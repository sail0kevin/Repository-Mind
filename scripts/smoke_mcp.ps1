param(
    [Parameter(Mandatory = $true)] [string] $ExePath,
    [string] $PythonCommand = "python",
    [string] $DatabasePath,
    [string] $ExpectedRepositoryAlias
)

$ErrorActionPreference = "Stop"
$exePath = [System.IO.Path]::GetFullPath($ExePath)
if (-not (Test-Path $exePath -PathType Leaf)) { throw "Backend executable not found: $exePath" }

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("RepoMind-MCP-Smoke-" + [guid]::NewGuid().ToString("N"))
$usesExistingDatabase = -not [string]::IsNullOrWhiteSpace($DatabasePath)
if ($usesExistingDatabase) {
    $databasePath = [System.IO.Path]::GetFullPath($DatabasePath)
    if (-not (Test-Path $databasePath -PathType Leaf)) { throw "MCP smoke database not found: $databasePath" }
    $dataDir = Split-Path $databasePath -Parent
}
else {
    $dataDir = Join-Path $tempRoot "data"
    $databasePath = Join-Path $dataDir "repomind.sqlite3"
}
$helperPath = Join-Path $tempRoot "verify_frozen_mcp.py"
$expectedAliasArgument = if ([string]::IsNullOrWhiteSpace($ExpectedRepositoryAlias)) {
    "__REPOMIND_EXPECT_EMPTY_DATABASE__"
}
else {
    $ExpectedRepositoryAlias
}

$helper = @'
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    executable, data_dir, database_path, expected_alias = sys.argv[1:5]
    if expected_alias == "__REPOMIND_EXPECT_EMPTY_DATABASE__":
        expected_alias = ""
    env = dict(os.environ)
    env.update({
        "REPOMIND_PATHS__DATA_DIR": data_dir,
        "REPOMIND_PATHS__DATABASE_PATH": database_path,
        "PYTHONIOENCODING": "utf-8",
    })
    server = StdioServerParameters(command=executable, args=["--mcp"], env=env)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            expected = {
                "list_repositories", "repo_overview", "search_code",
                "get_symbol", "analyze_impact", "find_related_tests",
            }
            assert names == expected, (names, expected)
            result = await session.call_tool("list_repositories", {})
            assert not result.isError, result
            payload = result.structuredContent or json.loads(result.content[0].text)
            assert payload["status"] == "ok", payload
            repositories = payload["data"]["repositories"]
            if expected_alias:
                matches = [item for item in repositories if item["alias"] == expected_alias]
                assert len(matches) == 1, (expected_alias, repositories)
                assert matches[0]["indexed"] is True, matches[0]
                assert matches[0]["snapshot_id"], matches[0]
                assert matches[0]["commit"], matches[0]
                assert matches[0]["file_count"] > 0, matches[0]
            else:
                assert payload["data"] == {"repositories": [], "total": 0, "indexed_count": 0}, payload
    mode = "shared-index" if expected_alias else "empty-database"
    print(f"Frozen MCP stdio OK: tools=6 discovery=ok mode={mode}")


asyncio.run(main())
'@

try {
    New-Item -ItemType Directory -Force -Path $tempRoot, $dataDir | Out-Null
    [System.IO.File]::WriteAllText($helperPath, $helper, [System.Text.UTF8Encoding]::new($false))
    & $PythonCommand $helperPath $exePath $dataDir $databasePath $expectedAliasArgument
    if ($LASTEXITCODE -ne 0) { throw "Frozen MCP smoke failed with exit code $LASTEXITCODE" }
}
finally {
    if (Test-Path $tempRoot) { Remove-Item -Recurse -Force $tempRoot -ErrorAction SilentlyContinue }
}
