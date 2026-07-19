# RepoMind 可验证成果计划

这份文档把简历中的“效果”拆成可以重复运行、可以解释、不会夸大的工程证据。所有对外数字都必须来自本地运行结果；没有测过的指标保留为待办，不写进简历。

## 当前已经可以对外说明的事实

- 内置 Demo 固定在 commit `8c5ac33542fbed5e117bfee19af1457e60bd166c`，无 Chat Key、无 Embedding Key 时可完成 Snapshot/Catalog/词法检索/规则问答、安全审查、依赖影响、Evidence 与 Trace。
- 后端本地测试 136 项通过，桌面端本地测试 63 项通过（11 个测试文件）；桌面端 renderer 与 Electron TypeScript 构建通过。
- 检索测试已覆盖 Recall@5、Recall@10、MRR、FTS5 能力检查、Snapshot 隔离、RRF 去重、结构关系扩展和 Evidence Budget 约束。
- Demo 的无 Key 降级路径已验证：Embedding 不可用时仍可完成 lexical-only 检索和规则回答。

这些数字只能描述当前 Demo 和本地验证，不能表述为“在大量真实仓库上达到的准确率”或“远程 CI 全部通过”。

## 评测目标与指标

### 第一阶段：检索质量

为每个测试仓库建立 10–20 条人工标注问题，每条问题记录：

```json
{
  "query": "修改 TokenService 会影响哪些测试？",
  "relevant_paths": ["src/auth/token_service.py", "tests/test_token_service.py"],
  "relevant_symbols": ["TokenService"],
  "snapshot_commit": "<40-char commit>"
}
```

固定报告以下指标：

- Recall@5 / Recall@10：前 5/10 条证据是否命中至少一个标注目标；
- MRR：第一个相关证据出现的位置；
- Evidence citation accuracy：回答引用的路径、Snapshot 和行号是否对应真实证据；
- Snapshot isolation：旧 commit 的内容是否不会出现在当前 Snapshot 的结果中。

### 第二阶段：成本与延迟

在相同机器、相同仓库、相同查询集下分别记录：

- ingest 总耗时、文件数、chunk 数；
- lexical-only、hybrid、no-key fallback 的端到端耗时；
- 送入模型的 evidence token 数与最大单文件占比；
- Embedding 失败后的降级耗时和成功率。

不使用“提升了 X%”的表述，除非同时保存基线、样本数量、运行环境和原始输出。

### 第三阶段：代码理解差异化

单独准备三类问题，突出 RepoMind 与普通文档 RAG 的差异：

1. 符号定位：函数、类、入口文件和调用关系；
2. 影响分析：修改某个符号后相关调用方和测试；
3. 版本溯源：同一路径在不同 commit 中的内容是否被正确区分。

## 计划中的项目增强

### P0：把现有测试变成公开评测入口（已完成基础版）

- 已将 `backend/tests/fixtures/m3_lexical_baseline.json` 扩展为 10 条查询；
- 已抽出统一的 Recall/MRR 计算模块，避免指标逻辑只存在于测试文件；
- 已新增只读 benchmark 报告命令，输出 JSON 和 Markdown；
- 当前报告包含仓库别名、Snapshot commit、查询数、Recall、MRR 和运行模式；真实耗时字段留到 P2 的统一运行器补充。

验收标准：同一工作区重复运行得到相同排名和相同质量指标；结果文件不包含 API Key、真实用户路径或数据库内容。基础版已通过测试和示例命令验证。

### P1：补充 RepoMind 自身的跨文件评测集（问题集已建立）

- 已新增 `examples/benchmarks/code-understanding-gold.json`，包含 8 条覆盖代码导航、依赖影响和安全审查的问题；
- 每条问题绑定 Snapshot commit、期望文件路径和符号名；
- 下一步将把真实检索排名写入该问题集对应的 capture 文件，再计算跨文件证据命中率；
- 仍需增加“错误证据拒答”和“旧 Snapshot 不串线”的端到端采样记录。

已从仓库内置 Demo 的真实 Trace 整理出一份首个 capture：
`examples/benchmarks/demo-evidence-capture.json`。它覆盖 3 条已有 Demo 问题，评估的是证据路径引用，不评价自然语言答案质量；运行报告时应同时保留其 limitations。

当前 capture 的报告见 `examples/benchmarks/demo-evidence-report.md`：证据引用命中率 **0.667**、引用精确率 **0.667**。其中依赖影响问题命中了错误的 `expected/showcase.json`，说明该能力仍需要修正，不能把该数字表述为整体准确率。该 capture 是修复前基线；修复后需重新运行 Demo 再做前后对比。

修复后的真实 API/Trace capture 与报告已经生成：

- `examples/benchmarks/demo-evidence-capture-post-fix.json`
- `examples/benchmarks/demo-evidence-report-post-fix.md`
- `examples/outputs/repomind-demo-trace.post-fix.json`

三问 synthetic Demo 的修复后结果为 Recall@5 **0.667**、Recall@10 **0.667**、MRR **0.833**、Citation hit rate **1.000**、Citation precision **0.750**；修复前标准 Recall@5/10 为 **0.556**。依赖影响问题的最终 Evidence 覆盖定义、入口引用候选和测试；由于实例方法调用边尚未完整解析，入口与测试只能称为源码引用候选，不能称为已证明的调用边。

验收标准：评测集能够覆盖代码导航、依赖影响、安全线索和版本溯源四条主链路。

### P2：记录可解释的性能结果

- 在 3 个规模档位（小型 Demo、中型开源仓库、大型开源仓库）运行相同评测；
- 记录 P50/P95 ingest、search、ask 延迟，以及 chunk/token 规模；
- 对 lexical-only 与 hybrid 分开报告，不把两者混成一个平均数。

验收标准：每个性能数字都能回到原始 JSON 结果和运行环境说明。

## 简历回填规则

当前只使用“136 项后端测试、63 项桌面测试、无 Key synthetic Demo 三问可复现”等工程事实。

完成 P0 后，可加入 Recall@5、Recall@10、MRR，但必须写明“在 X 条标注查询上的本地评测”。

完成 P2 后，才考虑写“平均延迟”“P95 延迟”“Token 消耗下降”等结果；不得用单次 Demo 运行推导通用性能结论。
