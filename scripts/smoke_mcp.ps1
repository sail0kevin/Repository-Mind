param(
    [Parameter(Mandatory = $true)] [string] $ExePath,
    [string] $PythonCommand = "python",
    [string] $DatabasePath,
    [string] $ExpectedRepositoryAlias,
    # 提供本地 Git 检出路径时，先用冻结 exe 的 --index 建库，再验证 MCP 能发现它。
    # 用法：smoke_mcp.ps1 -ExePath <exe> -IndexRepo <git-path> -ExpectedRepositoryAlias <alias>
    [string] $IndexRepo
)

$ErrorActionPreference = "Stop"
$exePath = [System.IO.Path]::GetFullPath($ExePath)
if (-not (Test-Path $exePath -PathType Leaf)) { throw "Backend executable not found: $exePath" }

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("RepoMind-MCP-Smoke-" + [guid]::NewGuid().ToString("N"))
$buildIndex = -not [string]::IsNullOrWhiteSpace($IndexRepo)
$usesExistingDatabase = (-not $buildIndex) -and (-not [string]::IsNullOrWhiteSpace($DatabasePath))
# 预建模式：不给 DatabasePath、不给 IndexRepo，期望 exe 自带的预建 demo 索引可直接发现。
$prebuiltMode = (-not $buildIndex) -and (-not $usesExistingDatabase)
if ($buildIndex) {
    # --index 模式总是用全新的临时数据目录，避免污染用户现有数据库。
    if ([string]::IsNullOrWhiteSpace($ExpectedRepositoryAlias)) {
        throw "ExpectedRepositoryAlias is required when IndexRepo is provided"
    }
    $dataDir = Join-Path $tempRoot "data"
    $databasePath = Join-Path $dataDir "repomind.sqlite3"
}
elseif ($usesExistingDatabase) {
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
$prebuiltModeArgument = if ($prebuiltMode) { "1" } else { "0" }

$helper = @'
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    executable, data_dir, database_path, prebuilt_mode, expected_alias = sys.argv[1:6]
    if expected_alias == "__REPOMIND_EXPECT_EMPTY_DATABASE__":
        expected_alias = ""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if prebuilt_mode != "1":
        # 预建模式下不注入数据目录环境变量，让 exe 使用自带的捆绑索引；
        # 其他模式（共享库/空库/--index）显式指向本次 smoke 的数据库。
        env.update({
            "REPOMIND_PATHS__DATA_DIR": data_dir,
            "REPOMIND_PATHS__DATABASE_PATH": database_path,
        })
    server = StdioServerParameters(command=executable, args=["--mcp"], env=env)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            expected = {
                "list_repositories", "repo_overview", "search_code",
                "locate_code", "get_symbol", "analyze_impact", "find_related_tests",
            }
            assert names == expected, (names, expected)
            result = await session.call_tool("list_repositories", {})
            assert not result.isError, result
            payload = result.structuredContent or json.loads(result.content[0].text)
            assert payload["status"] == "ok", payload
            repositories = payload["data"]["repositories"]
            if prebuilt_mode == "1":
                # 冻结 exe 自带预建索引：至少暴露一个已索引仓库。
                indexed = [item for item in repositories if item["indexed"]]
                assert indexed, ("prebuilt index must expose an indexed repo", repositories)
                if expected_alias:
                    matches = [item for item in repositories if item["alias"] == expected_alias]
                    assert len(matches) == 1, (expected_alias, repositories)
                    assert matches[0]["indexed"] is True, matches[0]
            elif expected_alias:
                matches = [item for item in repositories if item["alias"] == expected_alias]
                assert len(matches) == 1, (expected_alias, repositories)
                assert matches[0]["indexed"] is True, matches[0]
                assert matches[0]["snapshot_id"], matches[0]
                assert matches[0]["commit"], matches[0]
                assert matches[0]["file_count"] > 0, matches[0]
            else:
                assert payload["data"] == {"repositories": [], "total": 0, "indexed_count": 0}, payload
    if prebuilt_mode == "1":
        mode = "prebuilt-index"
    elif expected_alias:
        mode = "shared-index"
    else:
        mode = "empty-database"
    print(f"Frozen MCP stdio OK: tools=7 discovery=ok mode={mode}")


asyncio.run(main())
'@

if ($buildIndex) {
    Write-Host "Building index via --index: $ExePath --index --repo $IndexRepo --data-dir $dataDir"
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
    # --index 会打印预计耗时与进度；这里保留这些输出，但以进程退出码作为通过/失败信号。
    & $ExePath --index --repo $IndexRepo --data-dir $dataDir --alias $ExpectedRepositoryAlias 2>&1 |
        ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { throw "Frozen --index build failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path $databasePath -PathType Leaf)) { throw "MCP smoke: --index did not produce $databasePath" }
}

try {
    New-Item -ItemType Directory -Force -Path $tempRoot, $dataDir | Out-Null
    [System.IO.File]::WriteAllText($helperPath, $helper, [System.Text.UTF8Encoding]::new($false))
    # The frozen MCP SDK can emit cleanup diagnostics on stderr after a successful stdio session.
    # Keep those diagnostics visible, but use the native process exit code as the pass/fail signal.
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $PythonCommand $helperPath $exePath $dataDir $databasePath $prebuiltModeArgument $expectedAliasArgument 2>&1 |
            ForEach-Object { Write-Host $_ }
        $nativeExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($nativeExitCode -ne 0) { throw "Frozen MCP smoke failed with exit code $nativeExitCode" }
}
finally {
    if (Test-Path $tempRoot) { Remove-Item -Recurse -Force $tempRoot -ErrorAction SilentlyContinue }
}
