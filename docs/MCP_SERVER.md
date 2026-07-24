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
4. 记录注册结果中的 `repo_id`。所有 MCP 工具都要求显式传入该值。

MCP Server 与完成 ingest 的 RepoMind 实例必须指向同一个数据目录和 SQLite 数据库。

## 本地启动

在后端目录中运行：

```powershell
cd <repo-root>\backend
python -m service.mcp_server
```

该命令启动 `stdio` Server，通常应由 MCP 客户端自动拉起。直接运行时没有 HTTP 地址，也不会出现交互式提示。

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

本项目已使用 Claude Code `2.1.218` 真实验证：客户端能够连接 Server、列出全部 5 个工具，并分别调用这些工具取得仓库概览、检索证据、符号定义、影响分析和测试文件候选。首次调用 MCP 工具时，Claude Code 可能要求用户批准权限。

自动化隔离验收曾使用跳过权限确认的模式，但日常使用不应为方便而关闭全部权限检查。`--permission-mode dontAsk` 也不等于自动批准未预先授权的 MCP 工具，可能直接拒绝调用。

## Codex

Codex 等支持标准 `stdio` MCP Server 的客户端可使用与“通用 MCP 配置”相同的命令、参数和环境变量。配置后应先确认客户端能够看到以下 5 个工具，再用一个已完成 ingest 的 `repo_id` 进行查询。

当前开发环境中的 Codex CLI 因本机执行权限问题无法启动，因此本项目尚未完成 Codex 客户端的真实端到端验证。这里说明的是基于标准 MCP 协议的配置方式，不将其表述为已验证兼容。

## Phase 1 工具

| 工具 | 用途 | 主要参数 |
| --- | --- | --- |
| `repo_overview` | 获取文件统计、语言分布、关键文件和推荐阅读顺序 | `repo_id`, `snapshot_id?` |
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

`status` 可能为：

- `ok`：调用成功且主要能力可用。
- `degraded`：调用成功，但某一路能力不可用，例如 Embedding 不可用时退化为纯关键词检索。
- `not_found`：仓库、Snapshot 或目标符号不存在，或 Snapshot 尚不可查询。
- `error`：参数无效或内部调用失败。

外部 Agent 应同时检查 `status` 和 `limitations`，不能把引用候选、降级结果或证据不足当作已确认事实。

## 常见问题

### Server 无法启动

确认 `PYTHONPATH` 指向 RepoMind 的 `backend` 目录，且 `command` 使用的 Python 环境已经安装 `backend/requirements.txt`。Windows 下建议设置 `PYTHONIOENCODING=utf-8`。

### 返回找不到仓库

传入的 `repo_id` 必须来自与 MCP Server 相同 SQLite 数据库中的 RepoMind 仓库记录。检查 `REPOMIND_PATHS__DATA_DIR` 和 `REPOMIND_PATHS__DATABASE_PATH` 是否与 ingest 时一致。

### 返回没有可用 Snapshot

仓库必须先完成 ingest，并产生 `succeeded` Snapshot。`building` 和 `failed` Snapshot 均不会被查询。

### 显式 Snapshot 被拒绝

确认 `snapshot_id` 属于当前 `repo_id`，并且状态为 `succeeded`。跨仓库使用 Snapshot 会返回 `not_found`。

### `search_code` 返回 `degraded`

查看 `limitations`。Embedding Provider 未配置、当前 Snapshot 没有真实向量，或语义通道零命中时，RepoMind 会保留关键词检索结果并明确报告降级原因。

### Claude Code 没有调用工具

确认工具已在当前会话中获准使用。首次调用可能需要批准；`dontAsk` 模式可能拒绝未预批准的工具，而不是自动放行。

## 兼容性说明

RepoMind MCP Server 使用官方 MCP Python SDK 和标准 `stdio` 传输。它可供遵循该协议并支持相应配置方式的客户端接入，但这不等于已验证所有编辑器或所有客户端版本。当前已真实验证 Claude Code；Codex 的当前环境验证限制见上文。
