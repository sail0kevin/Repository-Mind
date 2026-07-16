# RepoMind 未来架构与开发路线图

> 定位：GitHub 仓库知识库 RAG 与智能问答系统
> 原则：事实优先、证据可追溯、渐进式理解、Token 可控、按需调用 Agent。

## 1. 产品目标

RepoMind 的目标不是默认让多个角色重复分析同一个仓库，而是把一个版本确定的 GitHub 仓库转换为详细、结构化、可检索、可压缩的知识库，使人或任意 AI 能够：

1. 用少量 Token 获得准确的仓库总览；
2. 逐层查看子系统、目录、文件和符号；
3. 针对问题检索原始代码证据并回答；
4. 只有在复杂任务中才调用专业分析工具；
5. 将结论定位到 commit、文件路径和代码行号。

## 2. 当前状态与后续目标

| 能力 | 当前实现 | 后续目标 | 不得夸大 |
|---|---|---|---|
| 桌面启动 | Electron 使用动态 localhost 端口启动 bundled backend，并校验实例、API、Schema、数据库路径与 Session | 增加更细的启动进度和可视化故障诊断 | 不能说是云端分布式服务 |
| 仓库输入 | 本地 Git 仓库或公开 GitHub URL；索引绑定 commit Snapshot，支持 refresh 和历史快照读取 | 私有仓库授权和更细的增量复用 | 未实现私有仓库授权 |
| 切片 | ParserAdapter 提供 Python、JS/TS、Markdown、配置结构切片，并保留文本 fallback | 扩展更多语言并优化超长符号切分 | fallback 不等于完整语义解析 |
| Embedding | 独立、可选的 OpenAI-compatible Embedding Provider；默认关闭，失败时 lexical-only | 增加更多 Provider 和大规模向量索引优化 | 默认模式不是必然启用语义向量 |
| 检索 | SQLite FTS5/BM25 + 可选 Embedding + RRF + 结构扩展 + Evidence Bundle | 扩充评测集、调优召回与重排 | 静态检索质量不等于完全理解仓库 |
| 仓库摘要 | 已实现符号、文件、目录和仓库层级的规则优先 Catalog | 增强子系统聚类和可选 LLM 摘要质量 | Catalog 不是源码真相的替代品 |
| Agent | Main Agent 条件路由 Specialist Tools，单次最多调用两个工具，并持久化 Trace | 增强证据充分度判断和工具评测 | 当前不是无限自主循环或并行自治 Agent 群 |
| 代码结构 | 多语言 symbols/relations、静态调用、import、继承、测试和配置关系 | 扩展跨语言 linker 与关系准确率评测 | 静态关系不是运行时精确调用图 |
| 分析报告 | 规则优先并绑定 Snapshot/Evidence，Legacy 多角色保留为高级入口 | 提升证据覆盖和报告评测 | 静态安全线索不等于完整安全审计 |

## 3. 核心术语

- **Repository Snapshot**：由仓库 URL、ref 和 commit SHA 唯一确定的不可变快照。
- **Evidence Unit**：可引用的最小知识单元，如文件、符号、文档章节、配置、测试、依赖或源码片段。
- **Repository Catalog**：用于逐层导航的压缩知识目录，不是源码真相的替代品。
- **Retrieval Plan**：根据问题选择检索粒度、检索器和结构扩展策略。
- **Evidence Bundle**：在指定 Token 预算内交给模型的去重、重排证据集合。
- **Main Agent**：唯一面向用户的问答与路由协调者。
- **Specialist Tool/Subagent**：仅在特定问题需要时运行并返回结构化证据的专业能力。

## 4. 本地处理与大模型的分工

### 4.1 优先本地确定性处理

以下工作不应为了“使用 AI”而调用模型：

- Git clone/fetch、commit 和文件哈希；
- `.gitignore`、依赖目录、二进制和生成文件过滤；
- AST/Parser 解析函数、类、import、route、配置键；
- 代码按符号和文档按章节切片；
- FTS/BM25 索引；
- 稳定 ID、来源路径和行号管理。

原因：本地处理速度快、成本低、可重复、可测试，不会因模型随机性改变事实。

### 4.2 大模型适用范围

- 符号、文件、目录和仓库的分层摘要；
- 模糊问题的查询规划或意图判断；
- 候选证据重排（必要时）；
- 基于证据生成自然语言回答；
- 复杂问题中对子 Agent 结构化结果进行综合。

模型输出必须绑定输入证据和版本信息。

## 5. 目标知识表示

### 5.1 节点

`Repository / Snapshot / Directory / File / Symbol / Chunk / DocumentSection / Test / Dependency / ConfigItem`

### 5.2 关系

`contains / defines / imports / exports / calls / references / tests / configures / depends_on / generated_from`

每条关系保存：

- 来源 Evidence ID；
- 提取方法；
- `observed / inferred / unknown` 状态；
- 置信度；
- parser 版本与 commit SHA。

旧版 all-to-all `maybe_call` 已移除；无法可靠解析的关系保留为 unresolved/ambiguous 或诊断信息，不作为事实展示。

## 6. 分层低 Token Repository Catalog

自底向上构建：

1. **Symbol Card**：职责、签名、输入输出、副作用、引用位置；
2. **File Card**：文件职责、公开接口、依赖、重要符号、测试位置；
3. **Directory/Subsystem Card**：模块边界、数据流、对外接口；
4. **Repository Overview**：项目目的、入口、主要模块、运行/测试方式、关键依赖；
5. **Reading Guide**：按问题类型提供推荐阅读路径。

每份摘要保存：

- 来源 Evidence IDs；
- 摘要层级和父子关系；
- 模型/Prompt/版本；
- Token 数和预算；
- commit SHA；
- freshness 状态；
- 已知未知项。

Catalog 负责快速导航；代码级问题仍必须回到源码证据。

## 7. RAG 检索链路

```text
GitHub URL/ref
  → Repository Snapshot
  → 文件过滤与语言解析
  → 符号/章节感知切片
  → Catalog + FTS/BM25 + Embedding + 结构索引
  → 查询理解与检索粒度选择
  → 多路召回、融合、去重、重排
  → Token-budget Evidence Bundle
  → Main Agent 证据回答
  → 引用 commit / path / line
```

### 三类检索信号

1. **词法检索**：标识符、文件名、错误、配置键和技术名词；
2. **语义检索**：同义表达、概念描述和自然语言问题；
3. **结构检索**：从已命中的符号扩展 import、测试、配置和依赖邻居。

### Evidence Bundle 策略

- 根据问题选择 repo/subsystem/file/symbol/chunk 粒度；
- 优先高相关、高可信、不同来源的证据；
- 限制重复片段和每个文件占用；
- 预留回答 Token；
- 每个证据说明“为何被选中”。

## 8. Main Agent 与按需工具

### 直接回答

项目概览、入口定位、文件职责、某函数解释等普通问题，主 Agent 完成检索后直接回答，不调用子 Agent。

### 条件调用

| 工具/子 Agent | 触发条件 |
|---|---|
| Repository Navigator | 问题宽泛、歧义或首次召回不足 |
| Dependency/Impact Analyst | 变更影响、多跳依赖、测试关联 |
| Test/Runtime Analyst | 启动、配置、测试、故障问题 |
| Security Reviewer | 用户明确提出安全审查或认证/密钥风险 |
| Language Code Analyst | 需要特定语言 Parser 或结构分析 |

执行原则：

1. 先检索，再判断是否需要工具；
2. 子 Agent 只返回结构化发现与 Evidence IDs；
3. 设置调用次数、超时和 Token 预算；
4. 主 Agent 统一生成最终答案；
5. 无证据时澄清或拒答。

## 9. LangChain / LangGraph 决策

M0–M3 不为简历关键词强行引入框架。先稳定领域接口：

`ParserAdapter / CatalogBuilder / Retriever / EvidenceAssembler / Router / SpecialistTool / LLMClient`

M4 出现以下需求时再评估 LangGraph：

- 持久共享 State；
- 条件分支、循环、重试和失败恢复；
- 人工审批；
- 可视化执行轨迹；
- 长任务中断与恢复。

若接入，必须有真实 `StateGraph`、节点、条件边、工具调用、持久化与测试，并通过 ADR 记录收益；完成前不得加入简历技术栈。

## 10. 历史实施里程碑与完成状态

以下内容记录 RepoMind 从原型升级到当前 M0–M5 架构的实施路径，不再表示尚未开始的未来任务。

### M0：文档、契约与安全基线（已完成）

- 建立后端与桌面端自动化测试；
- 实现版本化数据库迁移、备份和完整性检查；
- 修复 API 契约、Job 状态和密钥存储；
- 保持无 Key 模式和旧 API 兼容。

**验收结果：** Schema 7、DPAPI SecretStore、健康身份和测试基线已落地。

### M1：版本化快照与增量基础（已完成）

- 建立 commit 级不可变 Snapshot；
- 使用稳定 ID 与内容哈希；
- 同一 commit 幂等 ingest；
- 失败快照不替换 active succeeded Snapshot。

**验收结果：** 回答、Evidence、Catalog 和 Trace 均可绑定 Snapshot。

### M2：结构感知切片（已完成）

- 建立 ParserAdapter；
- 支持 Python、JS/TS、Markdown 和配置解析；
- 提取 symbols、relations、Evidence 和 diagnostics；
- 删除虚假的同文件 all-to-all 调用边。

**验收结果：** 测试夹具可验证符号、关系、原文位置和 fallback 诊断。

### M3：Catalog 与混合检索（已完成）

- 实现 SQLite FTS5/BM25；
- 实现可选独立 Embedding Provider；
- 使用 RRF、结构扩展和 Token 预算 Evidence Bundle；
- 建立规则优先的分层 Repository Catalog。

**验收结果：** Embedding 关闭或失败时可明确降级为 lexical-only，主链路不受阻断。

### M4：Main Agent 路由（已完成）

- 将普通问答接入 Main Agent；
- 使用确定性 Router 条件调用 Specialist Tools；
- 单次请求最多调用两个工具；
- 保存路由、检索、工具和综合 Trace；
- Legacy 多角色协作保留为高级入口。

**验收结果：** 简单问题可 0 工具回答，安全和影响问题仅调用必要工具。

### M5：桌面、CI 与 Windows 发布（已完成，远端 CI 待运行）

- 实现 Catalog、Snapshot、Evidence、源码和 Trace 工作区；
- 建立正式 PyInstaller spec 与根级 Windows 构建链；
- 生成并验证 `win-unpacked`、NSIS Setup 和 Portable；
- 配置 Windows CI 与 Release workflow。

**验收结果：** 本地后端 87 项测试、桌面端 22 项测试、冻结后端 smoke 和 Windows 发布物验证通过；GitHub Actions 仍需推送后在远端实际运行。

## 11. 当前实现地图

### 核心入口

- `backend/service/main.py`
- `backend/service/api/v1/repos.py`
- `backend/service/core/ingest_service.py`
- `backend/service/core/agent/main_agent.py`
- `desktop/app/renderer/src/main.tsx`
- `desktop/app/electron/main.ts`

### 主要领域模块

- `backend/service/core/parsing/`
- `backend/service/core/retrieval/`
- `backend/service/core/evidence/`
- `backend/service/core/catalog/`
- `backend/service/core/embeddings/`
- `backend/service/core/agent/`
- `backend/service/storage/migrations/`
- `desktop/app/renderer/src/features/`

## 12. 后续演进方向

- 私有 GitHub 仓库授权；
- 更大规模仓库的增量复用和性能优化；
- 跨语言 linker 与结构关系准确率评测；
- 更完整的 Recall@K、MRR、引用准确率和延迟门禁；
- 正式 Windows 图标、代码签名和远端 Release 验收；
- 只有出现真实持久状态图、循环和人工审批需求时，再评估 LangGraph。
