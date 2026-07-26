# RepoMind MCP Server

RepoMind MCP Server 是一个独立的 `stdio` 进程。它把 RepoMind 已建立的仓库索引以只读工具的形式提供给 Claude Code、Codex 和其他遵循标准 `stdio` MCP 协议的客户端。

MCP Server 直接复用 RepoMind 的核心检索、符号分析和 SQLite 存储服务，不通过 FastAPI 转发请求，因此使用 MCP 时不需要保持 FastAPI 服务常驻。

## 安全边界

MCP Server 只查询已经完成的索引：

- 不执行目标仓库代码或测试。
- 不安装目标仓库依赖。
- 不修改目标仓库文件。
- 不提供 Shell、写文件、Git Commit 或 Pull Request 工具。
- 不返回无边界的整份文件；查询文本、结果数量、证据数量和代码片段长度均有上限。

影响分析来自静态代码关系。动态调用、反射和无法确定类型的实例调用可能无法解析，工具会在 `limitations` 中说明这些限制。

## 前置条件

1. 准备 RepoMind 使用的 Python 环境并安装依赖：

   ```powershell
   cd <repo-root>
   python -m pip install -r backend\requirements.txt
   ```

2. 先在 RepoMind 中注册目标仓库并完成一次 ingest。
3. 确认该仓库至少存在一个状态为 `succeeded` 的 Snapshot。
4. 连接后先调用 `list_repositories` 获取 `repo_id`；其余上下文工具都要求显式传入该值。

MCP Server 与完成 ingest 的 RepoMind 实例必须指向同一个数据目录和 SQLite 数据库。

## 本地启动

在后端目录中运行：

```powershell
cd <repo-root>\backend
python -m service.mcp_server
```

该命令启动 `stdio` Server，通常应由 MCP 客户端自动拉起。直接运行时没有 HTTP 地址，也不会出现交互式提示。

## 使用 Windows 安装包中的 MCP Server

通过 Setup 安装或使用 `win-unpacked` 目录时，不需要另外安装 Python。先在桌面端导入并索引仓库，再将安装目录中的冻结后端作为 MCP 命令：

```text
<RepoMind 安装目录>\resources\backend\repomind-backend.exe --mcp
```

桌面版默认数据库位于：

```text
%APPDATA%\repomind-desktop\backend-data\repomind.sqlite3
```

对应的 MCP 配置示例：

```json
{
  "mcpServers": {
    "repomind": {
      "type": "stdio",
      "command": "<RepoMind 安装目录>\\resources\\backend\\repomind-backend.exe",
      "args": ["--mcp"],
      "env": {
        "REPOMIND_PATHS__DATA_DIR": "%APPDATA%\\repomind-desktop\\backend-data",
        "REPOMIND_PATHS__DATABASE_PATH": "%APPDATA%\\repomind-desktop\\backend-data\\repomind.sqlite3",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

部分 MCP 客户端不会展开 JSON `env` 中的 `%APPDATA%`，此时请替换为实际绝对路径。Portable 单文件版会解压到临时目录，不适合作为稳定的 MCP `command` 路径；需要长期接入时使用 Setup 安装版或固定的 `win-unpacked` 目录。

## 通用 MCP 配置

下面的 JSON 适用于支持标准 `stdio` MCP 配置的客户端。请将路径替换为本机实际路径：

```json
{
  "mcpServers": {
    "repomind": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "service.mcp_server"],
      "env": {
        "PYTHONPATH": "<repo-root>\\backend",
        "REPOMIND_PATHS__DATA_DIR": "<data-dir>",
        "REPOMIND_PATHS__DATABASE_PATH": "<data-dir>\\repomind.sqlite3",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

不要依赖非标准的 `cwd` 配置项。通过 `PYTHONPATH` 指向 RepoMind 的 `backend` 目录，可以让客户端从任意工作目录启动 Server。如果 `python` 不是安装 RepoMind 依赖的解释器，请把 `command` 改成该虚拟环境中 Python 可执行文件的绝对路径。

## Claude Code

可以先把上述通用配置保存为单独的 JSON 文件，然后通过严格配置模式检查连接：

```powershell
claude --mcp-config C:\path\to\repomind-mcp.json --strict-mcp-config
```

也可以使用 Claude Code 的 MCP 配置命令注册 Server。具体参数以当前安装版本的 `claude mcp add --help` 为准，并使用与通用配置相同的启动命令和环境变量。

本项目已使用 Claude Code `2.1.218` 真实验证原有 5 个上下文工具：客户端能够连接 Server，并分别取得仓库概览、检索证据、符号定义、影响分析和测试文件候选。新增的 `list_repositories` 已通过真实 `stdio` 客户端自动化与 Windows 打包链验证，但尚未重新进行 Claude Code 客户端实测。首次调用 MCP 工具时，Claude Code 可能要求用户批准权限。

自动化隔离验收曾使用跳过权限确认的模式，但日常使用不应为方便而关闭全部权限检查。`--permission-mode dontAsk` 也不等于自动批准未预先授权的 MCP 工具，可能直接拒绝调用。

## Codex

Codex 等支持标准 `stdio` MCP Server 的客户端可使用与“通用 MCP 配置”相同的命令、参数和环境变量。配置后应先确认客户端能够看到以下 7 个工具，调用 `list_repositories` 取得已完成 ingest 的 `repo_id`；自然语言代码定位优先调用 `locate_code`，再进行补充查询。

本项目已使用 Codex CLI `0.145.0` 完成真实 `stdio` MCP 调用：Codex 能发现工具，并通过 `search_code`、`get_symbol` 等工具取得固定 Snapshot 的代码证据。验证使用本地索引和只读任务，不代表所有 Codex 版本、模型供应商或编辑器环境均已兼容。

项目还提供固定 Commit 的代码定位 A/B。当前一轮在一个隔离的本地 AgentForge 检出上运行 5 条人工标注任务：普通搜索通过 2/5，RepoMind MCP 通过 3/5；MCP 工具结果中的源码字符从 `1,032,948` 降至 `112,971`，但总输入 Token 仅从 `422,444` 降至 `399,563`。这只说明初步的代码定位上下文收益，不代表完整开发任务或普遍节省 Token；样本量、计量方式和 Windows 提示词约束等限制见 [外部代码定位 A/B v3 报告](../examples/benchmarks/external-location-ab-v3-report.md)。

## 只读工具

| 工具 | 用途 | 主要参数 |
| --- | --- | --- |
| `list_repositories` | 发现仓库 ID、索引状态和活动 Snapshot，不返回本机绝对路径 | `limit?` |
| `repo_overview` | 获取文件统计、语言分布、关键文件和推荐阅读顺序 | `repo_id`, `snapshot_id?` |
| `locate_code` | 根据自然语言问题返回独立的候选位置与行号；未知符号、跨文件行为或多位置问题优先使用 | `repo_id`, `question`, `snapshot_id?`, `limit?` |
| `search_code` | 关键词与可选语义混合检索，返回有界代码证据 | `repo_id`, `query`, `snapshot_id?`, `limit?` |
| `get_symbol` | 按名称或限定名查询符号定义、关系和同名候选 | `repo_id`, `symbol_query`, `snapshot_id?` |
| `analyze_impact` | 查询目标定义、已解析调用关系和引用候选 | `repo_id`, `symbol_query`, `snapshot_id?` |
| `find_related_tests` | 定位测试、构建和入口文件候选，但不执行测试 | `repo_id`, `symbol_query?`, `snapshot_id?` |

未传 `snapshot_id` 时，工具使用该仓库当前 active 的 `succeeded` Snapshot。显式传入时，Snapshot 必须属于对应的 `repo_id` 且状态为 `succeeded`。

## 返回结构

所有工具统一返回：

```json
{
  "repo_id": "repo_...",
  "snapshot_id": "snap_...",
  "commit": "...",
  "status": "ok",
  "data": {},
  "evidence": [
    {
      "evidence_id": "...",
      "file_path": "src/example.py",
      "start_line": 10,
      "end_line": 24,
      "snippet": "...",
      "reason": "..."
    }
  ],
  "limitations": []
}
```

`locate_code.data.locations` 的每一项包含 `file_path`、`start_line`、`end_line`、`evidence_id` 和 `reason`。它适合先给出多个独立位置；只有需要验证具体语义时再调用 `search_code` 获取补充片段，避免把同一段源码反复传给外部 Agent。

`status` 可能为：

- `ok`：调用成功且主要能力可用。
- `degraded`：调用成功，但某一路能力不可用，例如 Embedding 不可用时退化为纯关键词检索。
- `not_found`：仓库、Snapshot 或目标符号不存在、Snapshot 尚不可查询，或 `search_code` 没有返回可验证的代码证据。外部 Agent 应改用更具体的符号名、路径或配置键，不能把空结果当作代码事实。
- `error`：参数无效或内部调用失败。

外部 Agent 应同时检查 `status` 和 `limitations`，不能把引用候选、降级结果或证据不足当作已确认事实。

## 常见问题

### Server 无法启动

确认 `PYTHONPATH` 指向 RepoMind 的 `backend` 目录，且 `command` 使用的 Python 环境已经安装 `backend/requirements.txt`。Windows 下建议设置 `PYTHONIOENCODING=utf-8`。

### 返回找不到仓库

先调用 `list_repositories`。如果目标仓库不在结果中，MCP Server 与桌面端没有使用同一数据库；检查 `REPOMIND_PATHS__DATA_DIR` 和 `REPOMIND_PATHS__DATABASE_PATH` 是否与 ingest 时一致。

### 返回没有可用 Snapshot

仓库必须先完成 ingest，并产生 `succeeded` Snapshot。`building` 和 `failed` Snapshot 均不会被查询。

### 显式 Snapshot 被拒绝

确认 `snapshot_id` 属于当前 `repo_id`，并且状态为 `succeeded`。跨仓库使用 Snapshot 会返回 `not_found`。

### `search_code` 返回 `degraded`

查看 `limitations`。Embedding Provider 未配置、当前 Snapshot 没有真实向量，或语义通道零命中时，RepoMind 会保留关键词检索结果并明确报告降级原因。

### Claude Code 没有调用工具

确认工具已在当前会话中获准使用。首次调用可能需要批准；`dontAsk` 模式可能拒绝未预批准的工具，而不是自动放行。

## 兼容性说明

RepoMind MCP Server 使用官方 MCP Python SDK 和标准 `stdio` 传输。它可供遵循该协议并支持相应配置方式的客户端接入，但这不等于已验证所有编辑器或所有客户端版本。当前已真实验证 Claude Code 与 Codex CLI，具体版本和验证边界见上文。
