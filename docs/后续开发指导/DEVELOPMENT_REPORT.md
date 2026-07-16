# RepoMind 开发报告

更新时间：2026-07-16

## 1. 项目定位

RepoMind 是一个面向 Windows 的本地 Git 仓库知识助手。它把仓库的 Git commit 构建为不可变知识快照，并通过结构解析、SQLite FTS5/BM25、可选 Embedding、证据预算和 Main Agent，提供仓库浏览、检索、代码关系查询与可追溯问答。

项目固定边界：

- 只读分析目标仓库；
- 不执行目标仓库代码；
- 不安装目标仓库依赖；
- 不修改目标仓库；
- 不自动提交代码、推送分支或创建 PR；
- 本轮正式支持 Windows，不宣称跨平台交付。

## 2. 总体完成状态

| 里程碑 | 状态 | 主要结果 |
| --- | --- | --- |
| M0 基线与安全 | 已完成 | API 契约、版本化迁移、DPAPI SecretStore、Job 状态、健康身份 |
| M1 Snapshot | 已完成 | commit Snapshot、稳定 ID、幂等 ingest、active Snapshot 切换 |
| M2 结构解析 | 已完成 | ParserAdapter、结构 Evidence、symbols、relations、diagnostics |
| M3 检索与 Catalog | 已完成 | FTS5/BM25、可选 Embedding、RRF、Evidence Bundle、Catalog |
| M4 Main Agent | 已完成 | 条件路由、Specialist Tools、持久化 Agent Trace、Legacy 兼容 |
| M5 桌面与发布 | 已完成（远端 CI 待运行） | 知识工作区、证据导航、PyInstaller、Electron、NSIS、Portable、Windows workflow |

“已完成”表示代码、自动化验证或本地运行路径已经实现；GitHub Actions 是否全绿必须以代码推送后的远端运行结果为准。

## 3. M0：测试基线、契约、迁移与安全

### 已实现

- FastAPI API 统一保留 `/api/v1`。
- 健康接口返回：
  - API 版本；
  - 实际数据库 Schema；
  - 代码支持的 Schema；
  - 后端 Contract 版本；
  - RepoMind 实例 ID；
  - 单次启动 Session ID；
  - 实际数据库路径。
- SQLite 使用版本化迁移和迁移校验，当前实际 Schema 为 7。
- 迁移版本序列为 `1,2,3,4,6,7`；版本 5 保留未使用，不得复用。
- 旧数据库迁移前执行同目录备份；迁移失败不会静默替换为空库。
- Windows API Key 使用当前用户 DPAPI 加密保存。
- Chat 与 Embedding Key 独立管理，设置响应不返回完整密钥。
- Job 支持明确的运行状态和失败状态；启动时处理中断任务。
- 目标仓库始终作为只读输入。

### 验证结果

- 后端测试：`87 passed`。
- 健康接口测试确认实际数据库 Schema 7，而不是只报告代码支持版本。
- 临时数据库验证通过 SQLite integrity、foreign key 和迁移序列检查。

## 4. M1：不可变 Snapshot 与索引生命周期

### 已实现

- `repos` 表示逻辑仓库，Snapshot 绑定 `repo_id + commit_sha`。
- 每次成功索引形成不可变 Snapshot。
- 文件、Evidence、Catalog、检索、问答和 Trace 均绑定 Snapshot。
- 只有构建成功的 Snapshot 才能成为 active Snapshot。
- 新 Snapshot 失败时保留上一个成功版本。
- 同一 commit 重复 ingest 保持幂等。
- 未显式传 Snapshot 的兼容 API 默认使用 active succeeded Snapshot。
- 首次 ingest 和 refresh 要求仓库存在 HEAD commit 且工作树干净。
- 索引期间出现 HEAD、分支或文件内容漂移时拒绝发布 Snapshot。

### 使用限制

- 未提交或未跟踪文件不会被当作正式 Snapshot 内容。
- 公开 GitHub URL 通过浅克隆接入；当前不处理私有仓库认证。

## 5. M2：ParserAdapter、结构 Evidence 与可靠关系

### 已实现

统一解析入口位于 `backend/service/core/parsing/`，包括：

- Python AST Parser；
- JavaScript/TypeScript tree-sitter Parser；
- Markdown 标题 Parser；
- JSON/YAML/TOML 配置 Parser；
- fallback 文本 Parser。

解析结果统一输出：

- Evidence Units；
- Symbols；
- Relations；
- Parser Diagnostics。

结构切片规则：

- Python/JS/TS 尽量按 module、class、function、method、interface 等符号切片；
- Markdown 按标题层级切片；
- 配置文件按结构和键路径切片；
- 无法可靠解析时才使用 fallback，并明确记录诊断。

关系模型包含来源、类型、置信度和 observed/inferred 语义，不再使用同文件函数全连接的虚假 `maybe_call`。

## 6. M3：FTS5/BM25、Embedding、混合检索与 Catalog

### 词法检索

- SQLite FTS5 建立 Evidence 索引。
- 使用 BM25 排序。
- 支持内容、符号、路径、语言和配置键相关检索信号。
- 构建和 smoke 会执行真实 FTS5 建表、写入和 MATCH 查询；缺少 FTS5 时构建失败，不静默伪装为 BM25。

### 可选 Embedding

- Embedding Provider 与 Chat Provider 分离。
- Embedding 使用独立 Base URL、模型和 API Key。
- 默认关闭。
- 未配置或调用失败时 ingest 仍可成功，并明确报告 `lexical-only`。
- 向量绑定 Evidence、provider、model、dimensions 和 content hash。

### Hybrid Retriever 与 Evidence Bundle

检索流程包括：

1. Query Planning；
2. 词法召回；
3. 可选语义召回；
4. RRF 融合；
5. 去重与结构扩展；
6. Token 预算 Evidence Bundle。

Evidence Bundle 记录选择原因、检索信号和裁剪原因，并限制总预算、单条证据和单文件占比。

### Repository Catalog

已实现规则优先的分层 Catalog，包括仓库、目录、文件和符号相关视图。LLM 增强失败不会破坏规则 Catalog。

## 7. M4：Main Agent 与 Specialist Tools

### 主流程

`/repos/{repo_id}/ask` 保持旧 API 兼容，内部执行：

1. 解析指定或 active Snapshot；
2. 构建 Retrieval Plan；
3. 组装 Evidence Bundle；
4. 判断证据充分度；
5. 条件式路由 Specialist Tool；
6. 生成模型回答或无 Key 规则回答；
7. 保存引用和 Agent Trace。

### 路由约束

- 简单概览、文件或函数解释：通常不调用工具；
- 变更影响：调用 Dependency Impact Tool；
- 安全、认证、密钥、权限问题：调用 Security Review Tool；
- 测试与运行问题：调用 Test Runtime Tool；
- 宽泛导航或证据不足：调用 Repository Navigator Tool；
- 单次请求最多调用两个工具；
- 工具超时或失败时返回带 limitation 的部分回答，不直接返回 500。

### Trace

Trace 持久化保存：

- 路由决策；
- 检索和 Evidence 选择；
- 工具调用原因、耗时、状态与 Evidence IDs；
- 最终综合过程。

桌面端可以通过 Trace ID 查询并展示执行轨迹。

### Legacy 多角色协作

`/collaborate` 保留兼容并标记为高级/Legacy 路径。普通 `/ask` 不自动进入固定多角色链。

## 8. M5：桌面知识工作区

### 已实现

- Electron + React + TypeScript + Vite。
- 仓库注册与最近仓库切换。
- Snapshot 列表、选择和刷新。
- Catalog、目录树、文件内容和源码证据浏览。
- Snapshot-aware 搜索与问答。
- Evidence 卡片打开生成答案时持久化的 chunk 内容，不使用变化后的工作区文件冒充历史证据。
- 精确行号展示。
- Main Agent Trace 展示。
- Chat 与 Embedding 独立设置。
- Legacy 协作移动到高级入口。
- Renderer API client 测试 20 项，加仓库注册测试 2 项，共 22 项通过。
- Renderer production build 与 Electron TypeScript build 通过。

### Electron 后端生命周期

- 正式打包模式只运行：
  `resources/backend/repomind-backend.exe`。
- 缺少内置后端时直接阻止业务窗口启动，不回退系统 Python。
- 开发模式仍可使用 Python 启动后端。
- 每次启动分配动态 localhost 端口和 Session ID。
- Electron 验证后端：实例 ID、API v1、Contract、Schema、数据库路径和 Session ID。
- userData 身份固定为 `%APPDATA%\repomind-desktop`。
- 应用身份保持：
  - package name：`repomind-desktop`
  - appId：`com.repomind.app`
  - productName：`RepoMind`
- 关闭时先请求正常终止，再清理 Windows 进程树。

## 9. Windows 构建与发布

### 正式构建链

根脚本：

```text
scripts/package_windows.ps1
```

链路包括：

1. 身份契约检查；
2. 构建 Python FTS5 检查；
3. 后端测试；
4. `backend/repomind-backend.spec` PyInstaller 构建；
5. 源冻结后端 smoke；
6. `npm ci`；
7. 桌面端测试与构建；
8. Electron `win-unpacked`；
9. 源后端和内置后端 SHA-256 对比；
10. 内置后端 smoke；
11. 可选 NSIS 与 Portable；
12. SHA-256 清单。

### 冻结后端 smoke

使用临时 `APPDATA`、临时数据库、随机端口、随机 Session ID 和空 Key 环境，验证：

- `/api/v1/health`；
- 后端身份与 API v1；
- 实际 Schema 7；
- 数据库路径隔离；
- 迁移序列 `1,2,3,4,6,7`；
- integrity 与 foreign key；
- 真实 FTS5 查询；
- Evidence/Trace 关键表；
- Chat 和 Embedding 均无 Key；
- 退出后进程树消失且 EXE 文件锁释放。

### 2026-07-16 本地发布验证

已实际生成：

```text
desktop/app/release/RepoMind-0.1.0-x64-setup.exe
desktop/app/release/RepoMind-0.1.0-x64-portable.exe
desktop/app/release/SHA256SUMS.txt
```

本次本地 SHA-256：

```text
DC613F08375090D7C10FF0617B4325024448B59D72F8E589F3CA869FD603AEAA  RepoMind-0.1.0-x64-setup.exe
FE162DDD9F565396BEC02B26AF57A273765F5408F43EECAE3161285F76E07711  RepoMind-0.1.0-x64-portable.exe
```

源冻结后端与 Electron 内置后端哈希一致：

```text
2A5975660D00D68690C414786C602C1FF687DF8798154C7C9B8A902B3D077FD4
```

最终内置后端运行观察：

```text
schema=7 fts5=ok migrations=1,2,3,4,6,7
Frozen backend smoke OK: schema=7 fts5=ok no-key=ok
Final embedded backend verification OK
```

### 本地构建环境说明

本机 Node 为 24/npm 11，因此 npm 报告了与项目要求 Node 20/npm 10 不一致的 `EBADENGINE` 警告，但本次安装、22 项桌面测试和构建均完成。正式 CI 固定 Node 20.18.0 和 Python 3.12。

本机 Windows 未授予 Electron Builder 解压符号链接所需权限，因此本地最终发布验证使用：

```text
--config.win.signAndEditExecutable=false
```

它只跳过 Windows EXE 图标/资源编辑，不跳过应用文件、后端嵌入、NSIS/Portable 内容和内置后端验证。正式 CI 保持标准配置，不加入该参数。

项目当前没有正式应用图标和代码签名证书，因此仍使用 Electron 默认图标，安装时可能出现未知发布者提示。

## 10. Windows CI 与 Release

### CI

`.github/workflows/ci-windows.yml` 在以下情况运行：

- push 到 `main` 或 `master`；
- pull request；
- 手动触发。

环境固定：

- Windows latest；
- Python 3.12 x64；
- Node.js 20.18.0；
- npm lockfile 安装。

### Release

`.github/workflows/release-windows.yml` 支持：

- `v*` Tag；
- 手动触发。

Tag 发布会校验 Tag 版本与 `desktop/app/package.json` 一致，然后构建并上传 Setup、Portable 和 SHA-256 清单。

### 尚未完成的远端验证

工作流文件和参数已完成本地检查，但尚未在 GitHub Actions 远端实际运行。因此当前不能声明“Windows CI 全绿”。代码推送后，应把首次远端 CI/Release 结果补充到本报告。

## 11. 最终验收矩阵

| 验收项 | 结果 | 证据或说明 |
| --- | --- | --- |
| `/api/v1` 兼容 | PASS | 路由保留，身份脚本通过 |
| 实际数据库 Schema | PASS | health 和 frozen smoke 均为 7 |
| 数据库隔离 | PASS | smoke 使用临时 APPDATA 和数据库路径 |
| SQLite FTS5 | PASS | 构建前检查及 frozen 真实 MATCH 查询通过 |
| 迁移序列 | PASS | `1,2,3,4,6,7` |
| 无 Key 启动 | PASS | frozen 和内置后端 smoke 通过 |
| Chat/Embedding 分离 | PASS | 独立设置、独立 SecretStore key |
| lexical-only 降级 | PASS | Embedding disabled/failure 不阻断主链路 |
| Snapshot 绑定 | PASS | 文件、Evidence、问答和 Trace 均绑定 Snapshot |
| 历史证据内容 | PASS | 桌面端按答案 Snapshot 读取持久化 chunk |
| Main Agent Trace | PASS | Trace API、存储和桌面展示已接入 |
| Legacy 兼容 | PASS | `/collaborate` 保留，移至高级入口 |
| 后端测试 | PASS | 87 passed |
| 桌面测试 | PASS | 22 passed |
| Renderer/Electron build | PASS | production build 与 tsc 通过 |
| 正式 PyInstaller EXE | PASS | formal spec 构建成功 |
| 源冻结后端 smoke | PASS | Schema/FTS5/no-Key/路径/Session 通过 |
| Electron `win-unpacked` | PASS | 目录包生成成功 |
| 内置后端一致性 | PASS | 源/内置 SHA-256 相同 |
| 内置后端运行 | PASS | 最终 embedded smoke 通过 |
| 后端进程树清理 | PASS | smoke 后无残留进程并验证文件锁释放 |
| NSIS Setup | PASS | `RepoMind-0.1.0-x64-setup.exe` 已生成 |
| Portable | PASS | `RepoMind-0.1.0-x64-portable.exe` 已生成 |
| SHA-256 清单 | PASS | `SHA256SUMS.txt` 已生成 |
| GitHub Actions | NOT RUN | 已配置，等待推送后远端运行 |
| 正式图标与代码签名 | NOT IMPLEMENTED | 当前使用默认图标且无签名证书 |

## 12. 当前已知限制

- 仅正式支持 Windows。
- 公开 GitHub URL 不支持私有仓库授权。
- Embedding 默认关闭，需要用户自行配置兼容服务。
- 大仓库索引时间、磁盘占用和增量性能仍可继续优化。
- 静态调用关系和安全线索不等于运行时事实或完整安全审计。
- 模型 Token 统计依赖供应商 usage；缺失时只能估算。
- 费用估算不代表模型供应商官方账单。
- 当前缺少正式应用图标、代码签名和发布者证书。
- GitHub Actions 尚待远端真实运行。

## 13. 后续建议

1. 推送代码并运行 Windows CI，记录首个远端全绿结果。
2. 使用 `v0.1.0` Tag 验证 Release workflow 和 GitHub Release 附件。
3. 增加正式 `.ico` 图标和 Windows 代码签名。
4. 扩展发布 smoke：创建临时 Git 仓库，通过冻结 HTTP API 完成 register → ingest → search → ask → trace。
5. 持续扩充检索评测集，记录 Recall@5/10、MRR、引用准确率和延迟。
6. 优化大型仓库的增量 ingest 和磁盘复用。

## 14. 重要开发纪律

- 不提交 API Key、真实用户数据库、克隆缓存或 release 二进制。
- 不以真实用户数据库执行 runtime smoke。
- 不把尚未在远端运行的 GitHub Actions 写成“已全绿”。
- 不把静态图谱描述为运行时真实调用链。
- 不把无 Key 规则回答描述为 LLM 回答。
- 保留用户已经整理好的目录意图：
  - `docs/后续开发指导/` 作为公开的当前文档；
  - `docs/旧的文件/` 作为本地历史归档，不上传公开 GitHub。
- 对外公开前应确认 Git 历史不包含仅供个人使用的面试材料、个人绝对路径或不希望公开的作者邮箱。
