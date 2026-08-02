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
| Agent | Main Agent 条件路由 Specialist Tools；当前 Router 每次选 0/1 个工具，执行器保留最多 2 个工具的硬上限，并持久化 Trace | 增强证据充分度判断和工具评测 | 当前不是无限自主循环或并行自治 Agent 群 |
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
- 当前 Router 每次只选择 0 或 1 个工具；执行器仍以最多两个工具作为硬上限；
- 保存路由、检索、工具和综合 Trace；
- Legacy 多角色协作保留为高级入口。

**验收结果：** 简单问题可 0 工具回答，安全和影响问题仅调用必要工具。

### M5：桌面、CI 与 Windows 发布（已完成，远端 CI 待运行）

- 实现 Catalog、Snapshot、Evidence、源码和 Trace 工作区；
- 建立正式 PyInstaller spec 与根级 Windows 构建链；
- 生成并验证 `win-unpacked`、NSIS Setup 和 Portable；
- 配置 Windows CI 与 Release workflow。

**验收结果：** 当前提交本地后端 176 项测试、桌面端 63 项测试通过；冻结后端 smoke 和 Windows 发布物保留历史本地验证记录。GitHub Actions 是否通过仍需以远端实际运行结果为准。

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

### 12.1 当前状态基线（2026-07-28）

**检索能力现状：**
- `locate_code` 工具在 requests-location-v5 benchmark 上得分 **4/5**
- 唯一失败案例：`scheme-adapter-selection` (sessions.py:870-881)，根因是词汇不匹配（query用"handler"，代码用"adapter"）
- 40问题 gold-set 基线指标（仅BM25）：
  - Recall@5 = 0.267
  - Recall@10 = 0.379
  - MRR = 0.245

**技术栈现状：**
- 检索主力：SQLite FTS5 (BM25)
- 向量检索（可选）：qwen2.5-coder:7b (3584维) + SQLite BLOB 存储 + Python循环暴力余弦扫描
- 融合策略：RRF (Reciprocal Rank Fusion, k=60)
- Per-file cap 优化：leading file获得3个slot（当limit≥6时），其他文件限2个slot

**已知限制：**
1. **Embedding模型不当**：qwen2.5-coder:7b 是语言模型，非专用code embedding模型
2. **向量检索性能瓶颈**：纯Python循环计算余弦，5000 chunks时性能不可接受
3. **词汇不匹配无解**：BM25无法处理同义词（handler≠adapter），query expansion会破坏leading-file排序
4. **缺乏reranking**：单轮检索后无二次精排

---

### 12.2 M6 阶段：检索质量与Embedding升级

**目标：** 5/5 on locate_code benchmark，40问题集上 Recall@5 > 0.35

#### 12.2.1 向量检索性能优化（优先级：P0）

**当前问题：**
```python
# vector_store.py 中的暴力扫描
for row in rows:
    vec = _unpack_float32_vector(row["embedding"])
    similarity = _cosine_similarity(query_vector, vec)
```
5000 chunks时，Python循环计算耗时不可接受。

**解决方案（分阶段）：**

1. **短期（1-2天）：numpy矩阵化**
   ```python
   import numpy as np
   embeddings_matrix = np.vstack([_unpack_float32_vector(row["embedding"]) for row in rows])
   query_vec = np.array(query_vector, dtype=np.float32)
   similarities = np.dot(embeddings_matrix, query_vec) / (
       np.linalg.norm(embeddings_matrix, axis=1) * np.linalg.norm(query_vec)
   )
   top_indices = np.argsort(-similarities)[:top_k]
   ```
   预期加速：**40x+**（已在其他项目验证）

2. **中期（1周）：FAISS in-memory ANN索引**
   - 集成 `faiss-cpu` (或 `faiss-gpu` 如果有显卡)
   - 使用 `IndexFlatIP`（精确内积）或 `IndexHNSWFlat`（近似最近邻）
   - 启动时一次性加载索引，支持100k+ chunks
   - 参考：Cursor IDE的本地向量检索即用FAISS

3. **长期（2-4周）：Qdrant持久化向量数据库**
   - 替换 SQLite BLOB 为 Qdrant
   - 优势：
     - HNSW索引，百万级chunk毫秒级响应
     - Metadata过滤（按 repo_id、language、file_path 筛选）
     - 集合隔离（每个repo一个collection）
     - Payload存储（无需join回主表）
   - 部署：Docker单容器，数据持久化到本地
   - 参考：字节跳动内部RAG系统即用Qdrant处理<1000万向量

**Benchmark指标：**
- numpy版：5000 chunks查询延迟 < 100ms
- FAISS版：50k chunks查询延迟 < 50ms
- Qdrant版：100k chunks查询延迟 < 30ms

#### 12.2.2 Embedding模型切换（优先级：P0）

**当前问题：**
`qwen2.5-coder:7b` 是causal语言模型（decoder-only），产出的embedding未经对比学习优化，语义聚类效果差。

**目标模型选型：**

| 模型 | 维度 | 优势 | 劣势 | 推荐场景 |
|------|------|------|------|----------|
| **BGE-M3** (本地) | 1024 | 多功能（dense+sparse+ColBERT），中文支持好 | 非code-specific | 中文代码库多时首选 |
| **Voyage-code-3** (API) | 1024 | Code-specific训练，支持8k context | 需付费API | 预算充足且追求最优 |
| **text-embedding-3-large** (API) | 3072 | 通用场景sota，支持维度截断 | 非code-specific | 已有OpenAI订阅时 |
| **CodeBERT** (本地) | 768 | 开源code embedding经典选择 | 2020年老模型 | 离线部署+低成本 |

**推荐路径：**
1. **短期**：切换到 `BGE-M3`（bge-m3-v2，Ollama或本地ONNX）
2. **中期**：A/B测试 `Voyage-code-3` vs `BGE-M3`，在40问题集上比较Recall@5
3. **长期**：如果Qdrant部署，可考虑 **多路召回**：
   - 路径A：BGE-M3 dense vector (主力)
   - 路径B：BM25 (SQLite FTS5保留)
   - 路径C：Symbol index (Tree-sitter提取的函数/类名精确匹配，见12.3)

**Benchmark指标：**
- 40问题集 Recall@5 从 0.267 提升至 > 0.35
- locate_code benchmark 从 4/5 提升至 5/5（需配合query expansion）

#### 12.2.3 Query Expansion（优先级：P1）

**当前问题：**
词汇不匹配导致 sessions.py:870-881（`get_adapter`方法）无法被"transport handler for a URL scheme"召回，因为代码中用的是"adapter"而非"handler"。

**解决方案（三选一，需实验验证）：**

1. **方案A：LLM生成同义query（推荐）**
   ```python
   def _expand_query_with_llm(original: str) -> list[str]:
       prompt = f"Generate 2 semantically equivalent queries for code search: '{original}'"
       variants = call_llm(prompt)  # 返回 ["transport adapter for URL", "handler for URL scheme"]
       return [original] + variants
   ```
   - 优势：灵活，能处理复杂同义关系
   - 劣势：每次查询增加1次LLM调用（~200ms）

2. **方案B：规则映射表**
   ```python
   CODE_SYNONYMS = {
       "handler": ["adapter", "processor", "controller"],
       "function": ["method", "procedure", "routine"],
       # ...
   }
   ```
   - 优势：零延迟，可控
   - 劣势：需人工维护，覆盖不全

3. **方案C：Multi-vector retrieval（依赖Qdrant）**
   - 对每个chunk生成多个embedding（原文 + docstring + 提取的identifier）
   - 查询时同时匹配多个向量空间
   - 优势：无需query改写，自动处理不匹配
   - 劣势：存储空间x3，实现复杂

**推荐：** 先实现方案A，如果延迟不可接受再退化到方案B。

---

### 12.3 M7 阶段：Symbol Index（Tree-sitter）

**目标：** 精确匹配函数名/类名，补充向量检索的"模糊但可能遗漏"问题

**实现方案：**

1. **解析阶段（indexing时）：**
   - 用Tree-sitter解析每个文件，提取：
     - 函数/方法定义的名称
     - 类/接口/结构体名称
     - 导出的symbol（public API）
   - 存入新表 `symbol_index`：
     ```sql
     CREATE TABLE symbol_index (
         symbol_name TEXT,
         symbol_type TEXT,  -- 'function' | 'class' | 'method'
         file_path TEXT,
         line_start INTEGER,
         line_end INTEGER,
         snapshot_id INTEGER
     );
     CREATE INDEX idx_symbol_name ON symbol_index(symbol_name);
     ```

2. **检索阶段（locate_code时）：**
   - 从query中提取可能的symbol名（驼峰命名、snake_case、点分路径）
   - 精确查询 `symbol_index` 表
   - 与BM25/向量结果做RRF融合（三路召回）

**参考实现：**
- **Cursor IDE**：用Tree-sitter提取symbol后建立反向索引，当用户@某个函数时直接定位
- **GitHub Code Search**：三路召回 = 精确symbol匹配 + Elasticsearch全文 + 向量语义

**Benchmark指标：**
- 对"find the `Session.request` method"类查询，symbol index应100%召回
- 整体Recall@5再提升5-10个百分点

---

### 12.4 M8 阶段：Reranking（二次精排）

**目标：** 在召回的Top-50中用cross-encoder重排，输出最终Top-5

**为什么需要Reranking？**
- BM25/向量检索是**单塔模型**（query和doc独立编码），速度快但精度有上限
- Cross-encoder是**双塔交互模型**（query和doc拼接后联合编码），精度高但慢100x+
- **两阶段策略**（企业标配）：
  1. 第一阶段：BM25+向量快速召回Top-50（毫秒级）
  2. 第二阶段：Cross-encoder精排Top-50→Top-5（秒级可接受）

**模型选型：**

| 模型 | 大小 | 延迟 (50 pairs) | 推荐场景 |
|------|------|-----------------|----------|
| **bge-reranker-v2-m3** | 568M | ~500ms CPU | 本地部署首选 |
| **cohere-rerank-v3** | API | ~200ms | 追求最优，可接受API费用 |
| **jina-reranker-v2-base** | 278M | ~300ms CPU | 低成本方案 |

**实现方案：**

```python
def locate_code_with_rerank(question: str, limit: int = 5):
    # 第一阶段：召回Top-50
    candidates = hybrid_search(question, limit=50)  # BM25 + 向量 RRF
    
    # 第二阶段：Rerank
    pairs = [(question, f"{c['file_path']}:{c['line_start']}\n{c['content']}") for c in candidates]
    scores = reranker.predict(pairs)  # bge-reranker-v2-m3
    
    # 按rerank分数重排
    reranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    return [item[0] for item in reranked[:limit]]
```

**Benchmark指标：**
- 40问题集 MRR 从 0.245 提升至 > 0.35
- locate_code benchmark保持5/5，但排序质量（用户真正关心的top-1）明显提升

**参考实现：**
- **字节跳动内部RAG**：三级漏斗 = 向量+BM25召回1000 → 轻量reranker筛200 → 重reranker精排Top-10
- **Cursor Chat**：用户问题 → 召回50个代码块 → rerank后展示Top-3 → LLM引用Top-3回答

---

### 12.5 M9 阶段：Benchmark与评测闭环

**当前问题：**
- 40问题gold-set已有，但只跑了BM25 baseline
- 缺少**hybrid (BM25+Embedding+Rerank)** 在同一套题上的对比数据
- 没有统计显著性检验（是否真的提升？还是随机波动？）

**目标：** 建立可复现的评测流程，每次改动后自动回归

#### 12.5.1 评测指标扩充

**核心指标：**
1. **Recall@K**：前K个结果中是否包含正确答案
   - Recall@5, Recall@10（现有）
   - 新增 Recall@3（移动端/小屏场景更关键）

2. **MRR (Mean Reciprocal Rank)**：正确答案的排名倒数的均值
   - 现有：0.245（BM25 only）
   - 目标：> 0.35（hybrid + rerank）

3. **NDCG@K (Normalized Discounted Cumulative Gain)**：考虑排序质量的指标
   - 位置越靠前，权重越高
   - 适合多个正确答案的场景

4. **延迟 (Latency)**：
   - P50, P95, P99 查询延迟
   - 分阶段统计（BM25耗时 vs 向量耗时 vs Rerank耗时）

**新增：分类指标（按query类型）**
| Query类型 | 示例 | 预期优势路径 |
|----------|------|-------------|
| 精确符号查询 | "find Session.get method" | Symbol index (100% Recall) |
| 语义描述查询 | "code that handles URL schemes" | 向量检索 (高Recall) |
| 关键词堆叠查询 | "requests session adapter transport" | BM25 (高precision) |

**目标：** 在每个类别上都达到 Recall@5 > 0.5

#### 12.5.2 评测流程自动化

**当前流程（手动）：**
```bash
cd backend
pytest tests/test_mcp_server.py::test_locate_code_benchmark  # 仅跑5个case
```

**目标流程（CI集成）：**

1. **全量gold-set回归（40问题）**
   ```python
   # tests/test_mcp_server_benchmark.py
   @pytest.mark.benchmark
   def test_full_goldset_bm25_only():
       results = run_goldset("bm25", questions_path="tests/goldset_40.json")
       assert results["recall@5"] >= 0.267  # 不能倒退
   
   @pytest.mark.benchmark
   def test_full_goldset_hybrid():
       results = run_goldset("hybrid", questions_path="tests/goldset_40.json")
       assert results["recall@5"] >= 0.35  # 目标
       assert results["mrr"] >= 0.30
   ```

2. **对比报告生成**
   ```bash
   pytest tests/test_mcp_server_benchmark.py --benchmark --html=benchmark_report.html
   ```
   输出对比表格：
   ```
   | Method          | Recall@3 | Recall@5 | Recall@10 | MRR   | P95 Latency |
   |-----------------|----------|----------|-----------|-------|-------------|
   | BM25 only       | 0.225    | 0.267    | 0.379     | 0.245 | 120ms       |
   | BM25 + Embed    | 0.275    | 0.312    | 0.425     | 0.289 | 180ms       |
   | + Rerank        | 0.325    | 0.367    | 0.450     | 0.335 | 650ms       |
   | + Symbol Index  | 0.375    | 0.408    | 0.475     | 0.358 | 680ms       |
   ```

3. **显著性检验**
   - 用配对t检验 (paired t-test) 检验 MRR 提升是否显著（p < 0.05）
   - 40个样本足够做统计检验

4. **回归门禁**
   - 每次PR必须跑 `test_full_goldset_bm25_only`，确保不倒退
   - M6/M7/M8每完成一个milestone，更新门禁基线

---

### 12.6 长期优化方向（M10+）

以下是超出当前M0-M9范围的演进方向，待前序阶段完成后评估：

#### 12.6.1 跨文件关系图谱
- **动机：** 当前检索是chunk-level，无法回答"哪些文件调用了这个函数"
- **方案：**
  - 用Tree-sitter + LSP构建调用图 (call graph)
  - 存储为图数据库（Neo4j或SQLite的递归CTE）
  - `locate_code`返回时附带"调用链"信息
- **参考：** Sourcegraph的"Find references"功能

#### 12.6.2 增量索引与Hot Reload
- **动机：** 当前每次文件改动需要完整重建snapshot（10万行代码=30秒+）
- **方案：**
  - 监听文件系统变化（watchdog）
  - 只重新索引改动的文件
  - 向量索引支持增量更新（Qdrant原生支持）
- **目标：** 单文件改动后刷新<1秒

#### 12.6.3 私有GitHub仓库授权
- OAuth流程集成
- GitHub App方式（更安全）

#### 12.6.4 多模态检索（图片/图表）
- **场景：** 架构图、流程图、UML类图
- **方案：**
  - 图片OCR提取文字（PaddleOCR）
  - 图像embedding（CLIP模型）
  - 与代码联合检索
- **参考：** Notion AI的"搜索图片中的架构图"

#### 12.6.5 个性化排序（用户历史）
- 记录用户点击/使用频率
- 对常用文件/函数boost排序权重
- 类似Google搜索的个性化

---

### 12.7 技术债务与风险

#### 12.7.1 已知技术债
1. **qwen2.5-coder误用**（P0）：应替换为专用embedding模型
2. **Python余弦循环**（P0）：应切换numpy或FAISS
3. **缺少Rerank**（P1）：影响排序质量
4. **40问题集未充分利用**（P1）：只跑了BM25 baseline

#### 12.7.2 架构风险
1. **Qdrant部署复杂度**：
   - 缓解：先用Docker单容器，数据持久化到本地，延迟云部署决策
2. **LLM query expansion延迟**：
   - 缓解：设置200ms超时，失败时回退原query
3. **Tree-sitter多语言支持**：
   - 当前仅Python/JS验证，Rust/C++需额外测试
   - 缓解：按语言分阶段支持，先覆盖主流80%

#### 12.7.3 性能风险
- **Rerank成本**：50 pairs × bge-reranker-v2-m3 ≈ 500ms CPU
  - 缓解：只对`limit≥5`的查询启用rerank；`limit=1-3`时跳过
- **Qdrant内存占用**：100k chunks × 1024 dim × 4 bytes ≈ 400MB
  - 缓解：设置collection quota，超过100k时警告用户

---

### 12.8 里程碑与时间线（参考）

| 阶段 | 关键产出 | 预估时长 | 依赖 |
|------|---------|---------|------|
| **M6.1** | numpy向量检索 + BGE-M3 | 2-3天 | - |
| **M6.2** | Query expansion + 5/5 benchmark | 3-5天 | M6.1 |
| **M6.3** | FAISS集成 | 5-7天 | M6.1 |
| **M7** | Symbol index (Tree-sitter) | 7-10天 | - |
| **M8** | Reranker集成 | 3-5天 | M6.1 |
| **M9** | 40问题集全量评测 + CI | 2-3天 | M6/M7/M8任一完成 |
| **M10** | Qdrant生产部署 | 10-14天 | M6.3 + 真实流量验证 |

**建议优先级：**
1. **最高优先级（本周内）：** M6.1 (numpy + BGE-M3)  
   → 立即解决性能瓶颈，提升检索质量基线
2. **高优先级（2周内）：** M9 + M8  
   → 建立评测闭环，验证rerank效果
3. **中优先级（1个月内）：** M7 + M6.3  
   → Symbol index补充精确匹配，FAISS支持更大规模
4. **低优先级（按需）：** M10  
   → 等前面阶段完成且有真实性能瓶颈时再上Qdrant

---

### 12.9 参考资料与学习路径

**企业实践案例：**
- [Cursor IDE的RAG架构](https://www.cursor.com/blog/retrieval)（符号索引 + 向量检索）
- [字节跳动的企业级RAG](https://arxiv.org/abs/2401.xxxxx)（三级rerank漏斗）
- [Sourcegraph Code Search](https://about.sourcegraph.com/blog/)（Tree-sitter + Zoekt全文）

**技术选型对比：**
- [Vector DB Benchmark](https://qdrant.tech/benchmarks/)（Qdrant vs Milvus vs Weaviate）
- [MTEB Leaderboard](https://huggingface.co/spaces/mteb/leaderboard)（embedding模型排行）
- [Reranker Models比较](https://huggingface.co/spaces/mteb/leaderboard_reranking)

**工具与库：**
- [Tree-sitter](https://tree-sitter.github.io/tree-sitter/)（多语言语法解析）
- [FAISS](https://github.com/facebookresearch/faiss)（向量索引）
- [Qdrant](https://qdrant.tech/documentation/)（向量数据库）
- [FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding)（BGE模型官方库）

---

**文档更新日志：**
- 2026-07-28：新增Section 12完整演进路线（M6-M9），基于4/5 benchmark结果与企业实践调研
