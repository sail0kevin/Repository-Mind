# RepoMind 简历蓝图落地实施计划

本文档是可执行的工程任务清单，目标是让项目真实实现支撑起以下"简历技术亮点"里当前还带占位符的部分：

- 检索方案选型（BM25 vs BM25+Embedding 对比）
- 工具调用鲁棒性（超时/重试/失败降级）
- 评测体系建设（任务完成率、工具调用准确率、响应延迟、Token 成本）
- 可靠性与风险防控（无引用依据时触发拒答）

与 `RESUME_EVIDENCE_PLAN.md` 的关系：那份文档定义了"什么数字可以对外说、什么时候能说"的原则（不夸大、必须有本地可复现依据）；本文档是"具体要改哪些文件、怎么改、怎么验证"的执行清单。两份文档不冲突，本文档的产出最终要回填进那份文档的"简历回填规则"一节。

## 硬性约束（执行时必须遵守）

1. **禁止编造任何数字**。所有指标必须来自本地实际运行结果。跑出来的数字不好看也要如实记录，可以在文档里如实标注局限，不能靠调整评测方法把不好看的数字调好看。
2. **禁止无关重构**。只修改本计划涉及的文件/模块，不要顺手"顺便优化"其他代码。
3. 每个任务完成后必须跑通已有的测试套件（后端 `pytest`、桌面端现有测试），不能因为新功能破坏现有 136+63 项测试。
4. 每新增一项能力，必须配套写单元测试，不能只写实现不写验证。
5. 涉及文档表述的任务（任务 9）要如实反映代码当前行为，不能让文档描述比代码实际能力更超前。

## 任务执行顺序

任务之间存在依赖关系，按以下顺序执行；同一序号内的子步骤可以打包一次性完成。

---

### 任务 1：BM25 vs BM25+Embedding 对比实验

**现状**：`service/core/embeddings/openai_compatible.py`、`service/core/retrieval/semantic.py`、`service/core/retrieval/fusion.py` 三个模块已完整实现，双路 RRF 融合逻辑在 `service/core/retrieval/service.py` 的 `HybridRetriever.retrieve` 中已经跑通。当前 `embedding_provider` 默认是 `disabled`（见 `service/core/embeddings/disabled.py`），纯粹是配置未开启，没有代码缺口。

**步骤**：
1. 选择一个 OpenAI 兼容的 Embedding API（`requirements.txt` 已声明 `openai>=1.12.0,<2`，不需要新增依赖）。
2. 通过 settings 接口将 `embedding_provider` 设为 `openai_compatible`，配置 `embedding_api_key`（走 secret store，不要硬编码或提交到仓库）、`embedding_base_url`、`embedding_model`。
3. 对现有 Demo 仓库（或任务 2 扩容后的评测仓库）重新执行 ingest，确认 `vector_store.has_real_embeddings` 对该 repo/snapshot 返回 `true`。
4. 使用 `scripts/report_retrieval_metrics.py`，分别在 `use_semantic=false`（纯 BM25 基线）与 `use_semantic=true`（BM25+Embedding+RRF）两种模式下各跑一次评测，产出两份报告。
5. 将两份报告的 Recall@5/10、MRR、Citation Hit Rate 并列整理成一份对比文档，存放到 `examples/benchmarks/`，命名参考现有的 `demo-evidence-report-post-fix.md` 风格。

**验收标准**：产出一份双路对比报告，包含两种模式下完整的指标数字与运行环境说明（模型名称、API 提供方、评测集版本）。如果双路提升不明显甚至下降，必须在报告里如实记录并给出可能原因，不能只选择性展示对比结果中好看的部分。

---

### 任务 2：评测集扩容

**现状**：`examples/benchmarks/code-understanding-gold.json` 目前 8 题，覆盖 `symbol_navigation`、`dependency_impact`、`security_review`、`repository_navigation` 四类；只有 3 题被真正跑通真实 pipeline（对应 `demo-evidence-capture-post-fix.json`）。缺少第五类场景 `test_runtime` 的题目。

**步骤**：
1. 补齐 `test_runtime` 类别的题目（针对"这个函数/模块有没有测试覆盖""某测试文件测的是什么"这类问题）。
2. 将现有四类各补充到 6-10 题，五类合计扩到 30-50 题。
3. 每题沿用现有字段格式：`{id, category, query, relevant_paths, relevant_symbols, snapshot_commit}`，并新增 `expected_tools` 字段（用于任务 5 的工具调用准确率评测，参考现有 3 题 demo capture 里已经带的 `expected_tools` 先例）。
4. 每题的 `relevant_paths`/`relevant_symbols` 必须能在目标仓库里实际核实存在，不能凭印象编写。

**验收标准**：扩容后的 gold 文件通过 JSON schema 校验（字段完整），且人工抽查至少 10 道题确认标注路径/符号在仓库中确实存在。

---

### 任务 3：采集脚本泛化

**现状**：`scripts/capture_demo_evidence.py` 里 `DEMO_FILES` 和 `QUESTIONS` 是硬编码常量，只服务于内置 3 题 Demo，无法直接驱动任务 2 扩容后的 gold 文件或其他仓库。

**步骤**：
1. 将脚本改造为通用 runner，输入变成命令行参数：`--gold-file <path>`、`--repo-id <id>`、`--snapshot-id <id>`（不再硬编码 `DEMO_FILES`/`QUESTIONS`）。
2. 保持现有的 Trace 采集逻辑、输出结构（`ranked`/`evidence_paths`/`relevant` 等字段）不变，确保下游 `service/evaluation/*_metrics.py` 的计算模块不需要跟着改。
3. 新增一个针对该脚本本身的测试或校验脚本，验证：用原有 3 题 demo 跑一次，产出结果与改造前的 `demo-evidence-capture-post-fix.json` 一致（防止重构破坏已有可复现性）。

**验收标准**：新脚本可以驱动任务 2 产出的 30-50 题评测集跑出 capture 文件；同时对原有 3 题 demo 重跑一次，确认结果与改造前完全一致。

---

### 任务 4：新增评测维度 —— 任务完成率

**定义**：Router 分发 → 工具执行 → 证据组装 → 答案生成全链路，最终产出"带可验证引用"回答的比例。判定为完成的条件：`answer.confidence` 不是拒答态（见任务 8）、引用列表非空、且引用路径均能在目标仓库中找到对应文件。

**步骤**：
1. 新增 `service/evaluation/task_completion_metrics.py`，风格参照现有 `retrieval_metrics.py` 的纯函数设计：输入是 capture 产出的 answer 记录数组，输出完成率及未完成样本的原因分类。
2. 在 `report_retrieval_metrics.py` 的 `_evaluate()` 中按现有"按存在字段合并结果"的模式接入这一维度。

**验收标准**：新增模块有独立单元测试，覆盖"完成""引用路径不存在""拒答"三种输入场景的正确分类。

---

### 任务 5：新增评测维度 —— 工具调用（Router）准确率

**定义**：对比 Router 实际调用的工具集合（Trace 中已记录的 `route_tools`）与 gold 文件中任务 2 新增的 `expected_tools` 字段，统计"该调用但未调用""不该调用但调用了""完全匹配"三类结果。

**步骤**：
1. 新增 `service/evaluation/tool_selection_metrics.py`，纯函数实现，输入是 capture 记录数组（含 `route_tools` 与对应 gold 里的 `expected_tools`）。
2. 同时统计参数校验通过率：结合任务 6 中新区分出的"参数错误"异常类型，统计工具调用中因参数问题失败的比例。
3. 接入 `report_retrieval_metrics.py` 汇总报告。

**验收标准**：新增模块有独立单元测试；至少能在任务 2 扩容后的评测集上跑出真实的工具选择准确率与参数校验通过率。

---

### 任务 6：新增评测维度 —— 响应延迟与 Token 成本

**现状**：`service/evaluation/timing.py` 已有通用的 P50/P95 延迟摘要函数；`main_agent.py` 的 Trace 记录中已经包含 `token_count` 字段。这两项数据源已经存在，缺的是把它们完整落到 capture 输出并汇总。

**步骤**：
1. 确认 `scripts/capture_demo_evidence.py`（任务 3 泛化后的版本）在采集时完整记录每次问答的耗时（`duration_ms`）和 `token_count`。
2. 在报告生成阶段调用已有的 `summarize_durations` 汇总延迟分布，并新增一个简单的 Token 消耗汇总（均值/最大值/是否超出预算上限 2400）。
3. 接入 `report_retrieval_metrics.py` 汇总报告。

**验收标准**：报告中包含真实的延迟分布（P50/P95）与 Token 消耗统计，运行环境（机器配置、是否启用 Embedding）需在报告中注明，避免不同运行条件的数字被混用比较。

---

### 任务 7：工具调用鲁棒性（超时 / 重试 / 参数校验分类）

**现状**：`main_agent.py` 中工具调用目前只有一层 `try/except Exception`，捕获后统一写入 `limitations` 文字提示。**没有超时包装，没有重试机制，参数错误和系统异常未做区分**。

**步骤**：
1. 为每个 Specialist 工具调用增加超时控制（这些工具目前均为本地数据库查询，可用 `concurrent.futures` 的 `timeout` 参数包装，超时阈值建议 2-3 秒，具体数值需结合实际查询耗时分布调整，不要凭空设定）。
2. 将异常分为至少两类：
   - **参数错误类**（如查询了仓库中不存在的符号名）：不重试，直接记录为业务性失败。
   - **可重试类**（如数据库连接瞬时失败、超时）：重试一次，仍失败则记录降级说明。
3. 更新 Trace 结构，使其能区分"参数错误失败""重试后成功""重试后仍失败""超时"这几种情况，为任务 5 的参数校验通过率统计提供数据源。
4. 新增单元测试，覆盖：模拟工具超时、模拟参数非法输入、模拟一次失败后重试成功三条路径。

**验收标准**：新增至少 4-6 个针对性单测；现有 `test_m4_main_agent.py` 的既有测试保持全部通过；Trace 输出能明确区分上述几类失败原因。

---

### 任务 8：可靠性与风险防控 —— 拒答机制

**现状**：`qa.py` 中的 `_fallback_answer` 在证据为空时只输出一句提示文案，函数仍返回正常的 200 响应和完整 answer 对象，**没有真正意义上的"拒绝生成答案"分支**。现有测试 `test_rule_fallback_never_emits_empty_evidence_reference` 测的是引用格式正确性，与拒答逻辑无关。

**步骤**：
1. 定义"证据不足"的量化判定标准（例如：证据条数为 0，或全部证据的相关性分数低于某个阈值——阈值需要结合实际检索分数分布设定，不能拍脑袋定一个数字后不做验证）。
2. 触发该判定时，`answer.confidence` 设置为专门的状态值（例如 `insufficient_evidence`），与现有的 `low` 置信度区分开。
3. 前端（桌面端）需要针对这个新状态展示明确的引导提示（如"当前证据不足，建议先完成索引或更换更具体的关键词"），而不是展示一个看起来正常但缺乏依据的回答。
4. 新增单元测试，验证空证据/低质量证据场景下系统输出的是新的拒答状态，而不是普通低置信度回答；验证有充分证据时行为不受影响。

**验收标准**：新增单测覆盖拒答触发与不触发两种边界场景；现有测试全部通过；任务 4 的任务完成率统计能正确识别并排除拒答样本。

---

### 任务 9：文档一致性修正

**现状**：`docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md` 第 8 节"执行原则"中提到"设置调用次数、超时和 Token 预算""无证据时澄清或拒答"，这些在任务 7、8 完成前属于**尚未落地的设计目标**，但文档表述容易被误读为已实现的当前能力。

**步骤**：
1. 在任务 7、8 完成前，若该文档仍被引用或展示给外部（如面试材料参考），需要在相关段落补充状态标注（如"设计目标，尚未实现"）。
2. 任务 7、8 完成后，更新该文档，将这两条从"设计目标"改为"已实现"，并注明对应的实现位置和验证方式（关联的测试文件）。

**验收标准**：文档中关于超时/重试/拒答的描述与代码实际行为在任一时间点都保持一致，不允许文档描述超前于代码实现。

---

### 任务 10：整体验证与数据回填

**步骤**：
1. 使用任务 3 泛化后的采集脚本，对任务 2 产出的 30-50 题评测集跑一次完整评测，产出包含五个维度（Recall/MRR、Citation Hit Rate、任务完成率、工具调用准确率、响应延迟与 Token 成本）的完整报告。
2. 汇总任务 1 的 Embedding 对比实验最终结果。
3. 统计任务 7、8 新增的单元测试数量，更新总测试数（当前后端 136 项、桌面端 63 项的基线数字）。
4. 将本次全部产出的真实数字，按 `RESUME_EVIDENCE_PLAN.md` 的"简历回填规则"要求，回填进简历蓝图中的占位符，同时更新面试话术文档（对应仓库内 `对应的项目面试话术/RepoMind/` 目录下的 00-05 号文档），确保新增能力对应的追问（"超时阈值怎么定的""拒答判定标准是什么""评测集怎么扩到 30-50 题的"）都有真实可核实的答案支撑。

**验收标准**：简历蓝图中原有的全部占位符 `[N]`、`[真实值]` 均被替换为可追溯到本文档任务产出的具体报告文件的真实数字；面试话术文档同步更新且无遗留的旧数字/旧表述。

---

## 任务依赖关系摘要

- 任务 1（Embedding 对比）：独立，无前置依赖，可最先执行。
- 任务 2 → 任务 3 → 任务 4/5/6：评测体系这条链路必须按此顺序执行，任务 4/5/6 之间互相独立可并行。
- 任务 7、任务 8：互相独立，可与任务 2-6 并行执行，但任务 5 的"参数校验通过率"统计依赖任务 7 产出的异常分类数据，任务 4 的"任务完成率"统计依赖任务 8 的拒答状态定义。
- 任务 9：依赖任务 7、8 完成后才能定稿为"已实现"，但可以在任何阶段先做"标注为设计目标"的中间态更新。
- 任务 10：依赖以上全部任务完成，是最终收尾步骤。

---

## 执行进度日志（供接手的 AI 参考）

### 2026-07-23 首轮执行

**任务 1（BM25 vs BM25+Embedding 对比）— 完成**
- ✅ BM25 纯词法基线：真实跑通并复现，`scripts/capture_demo_evidence.py` 产出 `examples/benchmarks/demo-evidence-capture-post-fix.json`，指标 Recall@5/10=0.667、MRR=0.833、Citation hit rate=1.000、Citation precision=0.750（3 题 demo，lexical-only）。
- ✅ 启用 Embedding 的采集变体已写好并验证逻辑：`scripts/capture_demo_evidence_hybrid.py`。它从环境变量 `REPOMIND_BENCH_EMBEDDING_KEY` 或 gitignored 文件 `bench-embedding.local.json` 读取 Embedding 配置（Key 绝不进对话/输出/版本库，`.gitignore` 已加 `bench-embedding.local.json`），ingest 后**硬断言** `has_real_embeddings` 为真、**硬断言** trace 检索 mode 为 `hybrid`，产出 `examples/benchmarks/demo-evidence-capture-hybrid.json`。
- ✅ BM25+Embedding 实测数字：已跑通。用本地 Ollama `qwen2.5-coder:7b`（3584 维）启用语义一路，`scripts/capture_demo_evidence_hybrid.py` 产出 `examples/benchmarks/demo-evidence-capture-hybrid.json`（硬断言 `has_real_embeddings`=true、trace mode=`hybrid`）。指标：Recall@5/10=0.667、MRR=0.833、Citation hit rate=1.000、Citation precision=0.750——**与纯 BM25 基线完全一致，一位数字都没变**。
- 📌 诚实结论：在这 3 题 demo 上，加 Embedding 对指标零影响。合理解释是 BM25 已把相关证据召回到前列，RRF 融合语义向量没改变排序；但 **3 题样本无统计意义**，不能据此说"Embedding 没用"或"有用"。真正的对比必须在任务 2 的 40 题评测集上跑（任务 3 泛化采集脚本后进行）。
- ⚠️ 性能说明（不要写进简历当性能指标）：本次 ingest 耗时约十几分钟，但这是**一次性建索引**且用了两个将就办法——(1) 拿 7B 对话模型 `qwen2.5-coder:7b` 当 embedding 用（应换 `nomic-embed-text`/`bge-small` 等专用小模型，快几十倍）；(2) urllib shim 逐条串行发送（绕开 Ollama httpx 502 的权宜之计，未批处理）。查询阶段只 embed 单个问题，是毫秒级，与此无关。此耗时不代表项目真实性能。
- 已排除的坑（留档）：(1) LongCat 只有 `/chat/completions`，调 embeddings 返回 404；(2) 国内直连 Ollama CDN 下 nomic-embed-text 会卡；(3) Ollama 的 OpenAI 兼容 `/v1/embeddings` 在 openai SDK(httpx) 下稳定 502，curl/urllib 正常——已用 urllib 传输 shim 绕过。
- ⚠️ 已知隐患：实际安装的 `openai` SDK 是 2.37.0，而 `requirements.txt` 声明 `<2`。当前 embedding 调用用的是稳定的 `.embeddings.create()` 接口，实测可用，但版本声明与实际不符，后续可考虑对齐。
- 诚实提醒：demo 仅 3 题 10 文件，双路对比数字无统计意义，真正有价值需在任务 2 的评测集上跑。

**任务 2（评测集扩容）— 完成**
- ✅ 决策：评测目标仓库定为 **RepoMind 自身后端**（83 模块/11227 行），而非 10 文件的 demo（demo 太小无法支撑 30-50 题）。
- ✅ 产出 `examples/benchmarks/backend-understanding-gold.json`：**40 题，5 类各 8 题**（symbol_navigation / dependency_impact / security_review / repository_navigation / test_runtime）。快照 commit 钉在 `c92e2f9af153212074da62d2d7fc1418bfbc0d72`。
- ✅ 每题的 `relevant_paths`（39 个唯一路径）、`relevant_symbols`（含测试函数名）均经脚本核实真实存在；`expected_tools` 由 `router.py` 的 if/elif 关键字规则逐条推导（注意 Router 优先级 SECURITY>IMPACT>TEST>OVERVIEW>LANGUAGE，出题已避开关键字误触发陷阱，如"启动"属 TEST、"密钥"属 SECURITY）。
- ✅ 校验：JSON 合法、无重复 ID、路径全部存在、符号全部存在。
- 关键提醒给任务 3：此 gold 文件路径是**仓库根相对**（形如 `backend/service/...`），假设 ingest 时以 `repo-knowledge-assistant` 仓库根为准。任务 3 泛化采集脚本时，若改为只 ingest `backend/` 子目录，需把路径前缀 `backend/` 去掉，或调整 ingest 根。这是任务 3 必须先确认的路径约定。

**下一步**：任务 3（把 `capture_demo_evidence.py` 从硬编码 demo 泛化成读 `--gold-file`/`--repo-id` 的通用 runner），它是让上面 40 题评测集跑出真实指标的前提。

### 2026-07-24 任务 3 执行

**任务 3（采集脚本泛化）— 完成**
- ✅ `scripts/capture_demo_evidence.py` 改造为双模式 CLI：不带 `--gold-file`/`--repo-id` 时走原有内置 3 题 demo 路径（原 `main()` 重命名为 `_run_builtin_demo_capture()`，函数体逐字节未改动）；带上这两个参数则走新的 `_run_generic_capture()`，对一个已经在跑的后端发真实 HTTP 请求（`/ask` + `/traces/{id}`），按 gold 文件的 `queries` 数组逐题采集，输出结构（`ranked`/`evidence_paths`/`relevant` 等字段）与原有 demo capture 完全一致，下游 `service/evaluation/*_metrics.py` 和 `scripts/report_retrieval_metrics.py` 不需要改一行。
- ✅ 新增 `scripts/verify_capture_regression.py`：重跑一次内置 3 题 demo，和改造前保存的 `demo-evidence-capture-post-fix.json`/`repomind-demo-trace.post-fix.json` 比较。剔除 UUID/时间戳等天然易变字段后，capture 文件内容要求逐字段相等；Trace 比较改为结构级（route/retrieval/synthesis 各一步、route_tools 相同、evidence 路径集合相同），不要求列表顺序——因为验证过程中发现 `dependency_impact` 工具在并列分数下的候选排序会随 Python 进程哈希种子变化，这是改造前就有的产品行为，不是本次引入的回归，因此不能拿"顺序完全一致"当回归判据。跑 `python scripts/verify_capture_regression.py` 输出 `PASS`。
- ✅ 用真实 40 题评测集（任务 2 产出的 `backend-understanding-gold.json`，快照 commit `c92e2f9af153212074da62d2d7fc1418bfbc0d72`）对泛化后的脚本做端到端验证：新建 git worktree 固定在该 commit，起一个独立后端实例，注册仓库并 ingest，再用 `python scripts/capture_demo_evidence.py --gold-file examples/benchmarks/backend-understanding-gold.json --repo-id <id> --snapshot-id <id> --base-url http://127.0.0.1:8123/api/v1 --output examples/benchmarks/backend-understanding-capture.json` 跑通全部 40 题，无一题因脚本本身异常中断。
- ✅ 用 `scripts/report_retrieval_metrics.py` 对该 capture 跑出真实指标（写入 `examples/benchmarks/backend-understanding-report.md`）：**Recall@5=0.267、Recall@10=0.379、MRR=0.245、Citation hit rate=0.550、Citation precision=0.166**（40 题，lexical-only，未启用 Embedding）。40 题逐题结果里 18 题 passed、22 题因"引用路径未命中 gold 标注的 relevant_paths"判定 failed；失败集中在 `repository_navigator`（8 题里 6 题 failed）和 `test_runtime`（8 题里 6 题 failed）两类，这两类问题往往期望的是"整体架构/模块分布"这种跨文件综述性答案，而当前 lexical 检索命中的是包含相同关键词的文档/示例文件（如 `docs/`、`examples/` 下的说明文档）而非 gold 标注的源码文件——这是真实的检索短板，不是评测方法出的假象，如实记录，不做美化。
- 📌 诚实结论：40 题规模下 BM25-only 的表现明显弱于 3 题 demo（demo 的 0.667/0.833 具有极大样本偏差，3 题本来就是精心挑选能被 lexical 检索命中的路径）。这组 40 题数字才是有统计意义、可以往简历/面试话术里填的基线；后续任务 1 的 Embedding 对比也应该在这个 40 题集上重跑一次，而不是只用 3 题 demo 的数字（那组对比数字目前记录在案但样本量不足，参见上面任务 1 日志的诚实结论）。
- 🐛 **过程中发现并修复两个与本任务无关但会真实阻断 ingest 的产品 bug**（均已征得用户同意后修复，不算"顺手无关重构"）：
  1. **YAML 布尔 key 排序崩溃**：`.github/workflows/*.yml` 这类文件里裸 `on:` 键被 PyYAML 解析成布尔值，`config_adapter.py` 里 `json.dumps(..., sort_keys=True)` 对着混有 `bool`/`str` 类型的 key 排序时抛 `TypeError`，导致任何带 GitHub Actions workflow 的仓库整体 ingest 被拒绝发布。修复：新增 `ConfigParser._sort_keys_as_str()`，统一按 `str(key)` 排序后重建 dict 再序列化。回归测试：`test_config_parser_handles_yaml_boolean_keys_like_github_workflow_on`（`backend/tests/test_m2_parser_storage.py`）。
  2. **JS/TS 证据 identity 冲突**：`javascript_typescript_parser.py` 的 `_add_exports`/`_add_heritage`/`_add_calls` 三处调用 `_add_evidence()` 时都没传 `identity`，导致同一模块内第二个 `export` 语句、同一函数体内第二次直接调用、同一符号的第二条 extends/implements 目标，会和第一条共享完全相同的 `logical_id`，撞上 DB 的 `UNIQUE(snapshot_id, identity_key)` 约束，整个仓库 ingest 直接失败（`UNIQUE constraint failed: evidence_units.snapshot_id, evidence_units.identity_key`）。修复：新增 `_next_evidence_discriminator(owner_id, kind)` 按 `(owner_id, kind)` 分配自增序号，仿照 `_add_symbol()` 里已有的 `_symbol_ordinals` 模式，把序号作为 `identity` 的一部分传给三处调用。回归测试：`test_repeated_js_ts_export_call_and_heritage_evidence_have_distinct_identity_and_are_persistable`（`backend/tests/test_m2_parser_storage.py`）。用本仓库自身（228 个已跟踪文件）做过端到端复现验证：修复前 63 个重复 `logical_id`、ingest 失败；修复后 0 个失败文件、0 个重复 `logical_id`。
  - 两个修复后，后端全量测试从 136 项增至 **138 项全部通过**（新增 2 个回归测试）。这两个 bug 本身可以作为简历/面试话术的真实素材："搭建评测基础设施时发现并修复了两个会导致真实仓库（带 CI workflow 的仓库、export/call 数量大于 1 的 JS/TS 文件）ingest 失败的产品级 bug"。
- 产出文件：`scripts/capture_demo_evidence.py`（改造）、`scripts/verify_capture_regression.py`（新增）、`backend/service/core/parsing/config_adapter.py`（bug 1 修复）、`backend/service/core/parsing/javascript_typescript_parser.py`（bug 2 修复）、`backend/tests/test_m2_parser_storage.py`（新增 2 个回归测试）、`examples/benchmarks/backend-understanding-capture.json`、`examples/benchmarks/backend-understanding-report.md`。

**下一步**：任务 4（新增"任务完成率"评测维度）。按已建立的模型批次表，任务 4-6 仍在 Sonnet 5 批次内，可以继续用当前模型执行；任务 7-8 开始前需要提醒切换到 Opus 4.8。

