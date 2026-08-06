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

### 首次使用需要先建索引

RepoMind 不做"边扫边答"——它先把仓库解析成符号、关系和证据，建成可检索的 SQLite 索引（FTS5 词法 + 可选向量），之后的查询全部走索引。**不建索引，`list_repositories` 为空，任何工具都无法返回结果。**

首次建索引耗时（实测，词法/无 Key 模式，数据来源：`index_location_benchmark.py` 与 `runtime-manifest.local.json`）：

| 场景 | 规模 | 实测耗时 |
| --- | --- | --- |
| 内置 demo 仓库 | 10 文件 / 159 chunks | 约 1.5 秒 |
| 中型仓库 | 196 文件 / 8,386 chunks | 约 61 秒 |

启用语义索引（embedding）会显著变慢：每个 chunk 都要调用 embedding 模型生成向量（网络 + 计算密集），同样 196 文件仓库实测约 5~20 分钟（依赖 provider 延迟），因此默认不启用。索引建立后，后续查询直接复用，不再重复建。

1. 准备 RepoMind 使用的 Python 环境并安装依赖：

   ```powershell
   cd <repo-root>
   python -m pip install -r backend\requirements.txt
   ```

2. 注册目标仓库并完成一次 ingest（安装版已内置 demo 预建索引，可先跳过本步直接用内置 demo 验证）：
   - 桌面端导入：在 RepoMind 桌面端注册并索引目标仓库。
   - 命令行导入：`backend-dist\repomind-backend.exe --index --repo <git路径> --data-dir <目录>`。该命令会先打印预计耗时，再提示"正在建索引，请不要中断"，最后打印实际耗时与 `repo_id`。
3. 确认该仓库至少存在一个状态为 `succeeded` 的 Snapshot。
4. 连接后先调用 `list_repositories` 获取 `repo_id`；其余上下文工具都要求显式传入该值。

MCP Server 与完成 ingest 的 RepoMind 实例必须指向同一个数据目录和 SQLite 数据库。

## 零配置一键接入

目标是：下载 → 安装 → 重开 Claude Code / Codex 会话 → `/mcp` 里直接看到 `repomind` 并可用 7 个只读工具。

- **安装器用户**：Windows Setup 安装版内置 demo 预建索引，安装完成后自动注册到 Claude Code 与 Codex。重开会话即可在 `/mcp` 看到 `repomind`，`list_repositories` 直接返回内置 demo 仓库。
- **源码用户**：在仓库根目录运行 `python scripts/setup_mcp.py`，脚本会自动写入 Claude Code 全局配置（`.claude.json` 的 `mcpServers` + `settings.json` 的自动放行）和 Codex 全局配置（`.codex/config.toml`）。它会 **merge 不覆盖**、先写 `.bak` 备份、原子写入；`--dry-run` 只打印将写入什么。写完后必须重开会话。

一键脚本不会删除你已有的其他 MCP 配置，也不会把 `required` 设为 `true`（Codex 的 server 配置若设成 `required=true`，server 挂了连 Codex 都起不来）。

## 本地启动

在后端目录中运行：

```powershell
cd <repo-root>\backend
python -m service.mcp_server
```

该命令启动 `stdio` Server，通常应由 MCP 客户端自动拉起。直接运行时没有 HTTP 地址，也不会出现交互式提示。

## 查看在线检索指标

`search_code` 和 `locate_code` 的每次 MCP 调用会在同一 RepoMind SQLite 数据库中记录一条遥测数据。记录只保留仓库/Snapshot、工具、检索模式、结果数、分数和耗时等聚合所需元数据，**不会保存原始查询文本**。MCP 本身保持 `stdio` 和只读工具边界；指标通过 HTTP 后端的 `GET /api/v1/metrics` 查看，因此需要另外启动 FastAPI：

```powershell
cd <repo-root>\backend
python -m service.main
```

默认近 7 天的请求量、top-score、低分数量和平均/P50/P95 延迟：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/metrics
```

可以传入 `days=1..30` 和已知的 `repo_id`，只查看单个仓库：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/metrics?days=30&repo_id=repo_xxx"
```

响应中的 `breakdown` 按 `tool_name + retrieval_mode` 分组，可判断慢查询来自 `search_code` 或 `locate_code`，以及 `hybrid` 或 `lexical` 路径。若启动时设置了 `REPOMIND_API_TOKEN`，请求必须附带 `X-RepoMind-API-Token`；Electron 会在其自身请求中自动携带该 token。指标不改变 MCP 返回、离线 benchmark 或目标仓库文件。

遥测只应用于真实 MCP 使用后的产品决策：先以 schema `9` 的桌面包索引真实仓库，再让已配置到同一用户数据库的 MCP 客户端自然产生 `search_code` 或 `locate_code` 请求，最后读取聚合指标。不得用单元测试、benchmark、合成 MCP 请求或直接写 SQLite 的方式填充 `retrieval_metrics`；这些操作会污染真实使用趋势，且不能替代离线检索评测。

注意：安装版自带的**预建 demo 索引是只读的**，查询它不会写入遥测记录。要测量你自己仓库的真实检索趋势，请先把它索引到自己的可写数据目录（桌面端导入或 `--index`），再让 MCP 指向该目录。

## 使用 Windows 安装包中的 MCP Server

通过 Setup 安装或使用 `win-unpacked` 目录时，不需要另外安装 Python。安装版已内置 demo 预建索引，开箱即用；索引你自己的仓库可选：①桌面端导入，②`repomind-backend.exe --index --repo <路径>`。将安装目录中的冻结后端作为 MCP 命令：

```text
<RepoMind 安装目录>\resources\backend\repomind-backend.exe --mcp
```

不设置 `REPOMIND_PATHS__*` 环境变量时，冻结后端直接使用自带的预建 demo 索引（只读，安装版开箱即查 demo）；只有你想查询自己索引的仓库时，才需要像下面这样显式指定数据目录。

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

项目还保留固定 Commit 的外部代码定位 A/B。隔离的本地 AgentForge 检出上，5 条人工标注任务的历史一轮结果是：普通搜索通过 2/5，RepoMind MCP 通过 3/5；MCP 工具结果中的源码字符从 `1,032,948` 降至 `112,971`，但总输入 Token 仅从 `422,444` 降至 `399,563`。这只说明外部 Agent 在当时提示词、工具选择和 Windows 限制下的初步上下文收益，不代表完整开发任务、普遍节省 Token，也不能作为 MCP 工具本身的召回率。

工具级质量以独立的固定 manifest 基准为准：生产 `locate_code` 在同一组 5 个标注代码位置上的 lexical 回归为 5/5，gold-location coverage 为 `1.000`，mean gold-location reciprocal rank 为 `0.578`。该基准直接评估工具返回的位置；它与外部 Agent A/B 的最终采纳行为、上下文消耗和任务完成率测量对象不同，不能将两组数字混为同一指标。完整条件和历史 A/B 细节见 [外部代码定位 A/B v3 报告](../examples/benchmarks/2026-07-26_EXTERNAL_LOCATION_AB_V3_REPORT_外部代码定位对比报告V3.md)；当前实现与后续执行关口见 [改进方案 V2.1](./后续开发指导/2026-08-01_IMPROVEMENT_PLAN_V2_当前改进执行计划.md)。

## 只读工具

| 工具 | 用途 | 主要参数 |
| --- | --- | --- |
| `list_repositories` | 发现仓库 ID、索引状态和活动 Snapshot，不返回本机绝对路径 | `limit?` |
| `repo_overview` | 获取文件统计、语言分布、关键文件和推荐阅读顺序 | `repo_id`, `snapshot_id?` |
| `locate_code` | 根据自然语言问题返回独立的候选位置与行号；未知符号、跨文件行为或多位置问题优先使用 | `repo_id`, `question`, `snapshot_id?`, `limit?`, `compact?` |
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

### Coding Agent 紧凑定位

对 Coding Agent 的普通代码定位任务，调用 `locate_code(..., compact=true)`。成功时它只返回
`repo_id`、`snapshot_id`、`commit`、`status` 和 `locations`；每个位置仅含
`path`、`start_line`、`end_line`。这让 Agent 可以直接给出路径和行号，而不会重复接收问题文本、
evidence ID、解释和常规限制说明。只有需要细节审计或补充源码片段时，才使用默认详细结果或
`search_code`。

当结果是 `degraded` 或 `not_found` 时，紧凑结果仍会包含 `retrieval_mode` 和 `limitations`，不能把
紧凑格式误解为更强的检索保证。

对于固定到单一已索引仓库和 Snapshot 的外部 Coding Agent，可启动更小的 profile：

```powershell
$env:REPOMIND_MCP_REPO_ID = "repo_..."
$env:REPOMIND_MCP_SNAPSHOT_ID = "snap_..."
python -m service.mcp_server --profile coding-agent
```

该 profile 只暴露 `locate_code(question, limit?)`，并始终使用紧凑返回。它不暴露仓库发现、通用搜索、
符号或影响分析工具，也不要求 Agent 重复传入 `repo_id` 或 `snapshot_id`；适合受 manifest 绑定的
benchmark 或单仓库工作会话。缺少 `REPOMIND_MCP_REPO_ID` 时调用会明确失败，不会退回用户默认数据库。

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
