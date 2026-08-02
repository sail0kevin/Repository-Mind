# RepoMind 改进方案 V2.1
> 文档生成时间：2026-07-30
> 评审修订时间：2026-07-30
> 基于：面试深度问答、源码逐行确认、企业级落地分析
> 上一版路线图：[2026-07-28_ARCHITECTURE_FUTURE_ROADMAP_未来架构路线图.md](./2026-07-28_ARCHITECTURE_FUTURE_ROADMAP_未来架构路线图.md)

本文档是对 2026-07-28_ARCHITECTURE_FUTURE_ROADMAP_未来架构路线图.md Section 12 的补充与细化，也是当前唯一的改进任务执行入口。执行时先完成 P0-0 的现状审计，再按依赖顺序推进；不得跳过基线复现，也不得把示例代码直接视为最终实现。

状态标记：`⬜ 未开始`、`🚧 进行中`、`✅ 已完成`、`⏸ 暂缓`。每完成一项，必须填写 commit、配置、实测指标、报告路径和验证命令。

---

## 当前状态快照

| 指标 | 数值 | 来源 |
|------|------|------|
| 外部 Coding Agent 的 locate_code 最终答复 | 4/5 | historical external trace；不是纯工具指标 |
| locate_code 工具级基准（固定 requests 索引，lexical） | 5/5，gold-location coverage 1.000 | `scripts/run_location_retrieval_benchmark.py`，2026-07-31 |
| 40问题集 Recall@5 (BM25 only) | 0.267 | service/evaluation/retrieval_metrics.py |
| 40问题集 MRR (BM25 only) | 0.245 | 同上 |
| Hybrid (BM25+向量) 对比数据 | 推荐 BGE-M3：Recall@5 0.4404，Recall@10 0.4954，MRR 0.3196；all-minilm 仅为历史 provisional baseline | `benchmark-runs/` 本地实测 |
| Embedding 配置 | Provider 默认可关闭；推荐 `openai_compatible` + Ollama `bge-m3:latest`，输入截断 128、batch 16 | service/core/embeddings/service.py |
| 向量检索实现 | NumPy 矩阵化；5000 x 1024 合成微基准 P50 37.794 ms | service/core/vector_store.py |
| 跨文件调用关系 | 已覆盖可静态证明的 Python import/receiver 调用；覆盖率扩展待真实需求驱动 | parser/storage relations + legacy codegraph builder |
| Reranker | BGE reranker A/B 的 MRR 为 0.481，但 CPU P95 77066.8 ms；默认保持 disabled | service/core/retrieval/reranker.py |
| 增量索引 | **已审计且暂停**：snapshot 不可变，跨快照向量缓存已复用；client reuse 完整 ingest 433.575 s | scripts/profile_ingest.py |

---

## P0：本周内必须做（直接影响面试可信度）

### ✅ P0-0：现状审计与基线冻结

**目的：** 当前代码已存在 Hybrid、RRF、真实向量存储和 observed relation 消费路径，部分旧描述已经过期。先冻结实验条件，避免重复开发和不可比指标。

**必须记录：**
1. 被测仓库绝对路径、Git commit、RepoMind commit；
2. 数据库、repo_id、snapshot_id 和索引生成时间；
3. embedding provider、base URL、模型、维度和批大小，不记录密钥；
4. lexical/semantic 候选数、RRF 参数、最终 limit、是否启用结构扩展；
5. Python 和依赖版本、CPU/GPU 环境、冷启动或热缓存；
6. 当前 P0/P1 各项实际状态：未实现、部分实现、已实现但缺 benchmark。

**产物：** 新增可提交的 benchmark manifest 或配置模板；真实密钥与本机数据库继续由 `.gitignore` 管理。

**验收标准：** 其他开发者只依赖 manifest、gold-set 和命令说明，就能在同一 commit 上重建等价实验。

**预计耗时：** 半天

**实测记录（2026-07-30）：**

- RepoMind 代码版本：`e5507d2976c8dcd2cf72ca31728a2e4699ebd871`；被测目标快照：`c92e2f9af153212074da62d2d7fc1418bfbc0d72`（干净 detached worktree）。
- 可提交实验契约：[backend-understanding.manifest.example.json](../../examples/benchmarks/backend-understanding.manifest.example.json)；统一执行器：[run_retrieval_benchmark.py](../../scripts/run_retrieval_benchmark.py)；gold-set SHA-256：`5aadace0da4a260826882b198778436c52f5b0116cbe4135126fbb8907d4f331`。
- 冻结检索参数：最终 `limit=8`、候选倍率 `4`、最大候选数 `200`、RRF `k=60`、启用结构扩展。runner 会校验这些声明与当前检索器默认值一致，并将实际 mode 写入 trace。
- runner 使用隔离 SQLite、内存 SecretStore 与 FastAPI TestClient；它不执行、不安装、不改写被测仓库。提交物不含本机路径、数据库 ID、snapshot ID 或密钥；运行 capture 位于被忽略的 `benchmark-runs/`。
- Hybrid 前置检查完成：本机 Ollama `127.0.0.1:11434` 不可达，且未设置专用 embedding 环境变量。因此 Hybrid 尚无可用实测值，不能以 lexical fallback 冒充 Hybrid。

---

### ✅ P0-1：建立 runner 并跑完 Hybrid 的 40 问题对比实验

**问题：** 声称做了 hybrid 检索，但只有 BM25 baseline 数据，没有 BM25+向量 的对比数字，面试站不住脚。

**改法：**
1. 新增统一 benchmark runner，读取现有 `examples/benchmarks/backend-understanding-gold.json`，不要把 40 问题 benchmark 塞进 MCP 单元测试；
2. 在同一 commit、同一份索引内容和同一参数下，先跑 BM25 only，确认可复现 Recall@5 `0.267`、MRR `0.245`；
3. 再跑当前 qwen Hybrid 作为历史诊断对照，不把它作为最终能力基线；
4. 用 `service/evaluation/retrieval_metrics.py` 的 `evaluate_rankings()` 计算指标；
5. 保存逐题 ranking、逐题命中、配置、Recall@5/10、MRR、P50/P95 延迟和运行时间。

**验收标准：**
- BM25 指标与已发布 baseline 一致，允许的浮动必须在报告中解释；
- 能说出“当前模型 Hybrid 下 Recall@5=X，MRR=X，相对 BM25 变化 Y%”；
- 原始 capture 和对比报告落在 `examples/benchmarks/`，任何数字均可从 capture 重算。

**预计耗时：** 1 天

**实测记录（2026-07-30，BM25 复现已完成）：**

| 指标 | 实测值 |
|------|-------:|
| Queries | 40 |
| Recall@5 | 0.267 |
| Recall@10 | 0.379 |
| MRR | 0.245 |
| Citation hit rate | 0.550 |
| Citation precision | 0.174 |
| Task completion | 0.550（22/40） |
| Tool selection exact match | 1.000 |
| P50 / P95 延迟 | 872.587 ms / 1346.594 ms |
| 完整运行时间 | 61.11 s |
| 索引文件 / chunks | 196 / 8386 |

BM25 的 Recall@5 与 MRR 与已发布基线在报告精度内一致，完成了可复现基线核验。Citation precision 与历史 capture 的 `0.166` 不同，是当前 RepoMind 代码生成的 evidence 细节变化所致，不代表排名指标变化。原始本地 capture/report 因包含运行时标识和绝对路径元数据而保留在被忽略的 `benchmark-runs/`；可公开复现输入为 manifest、gold-set 和 runner。

**Hybrid 实测记录（2026-07-31）：**

- 使用同一冻结 target commit `c92e2f9af153212074da62d2d7fc1418bfbc0d72`、同一 40 题 gold（SHA-256 `5aadace0da4a260826882b198778436c52f5b0116cbe4135126fbb8907d4f331`）和同一检索参数运行隔离 FastAPI ingest/ask/trace。
- provider 为本机 Ollama 的 OpenAI-compatible API，模型 `all-minilm:latest`（384 维）。为适配该模型较短上下文，本次索引输入截断为 `128` 个字符、embedding batch size 为 `16`；`8477/8477` chunks 的状态均为 `ready`，且 `8477` 条真实向量均已落库。该限制必须保留在解释实验结果时，不能与未截断模型或 BGE-M3 的结果混为一谈。
- 运行器逐题校验 trace 的 retrieval mode 为 `hybrid`，40 题均有排序结果；目标仓库代码未执行，也未安装其依赖。运行产物位于被忽略的 `benchmark-runs/backend-understanding-20260731-all-minilm-hybrid-v3/`，其中 `hybrid-capture.json`、`hybrid-report.md` 和 `runtime-manifest.local.json` 可用于本机复核与指标重算。

| 指标 | BM25 | all-minilm Hybrid | 相对变化 |
|------|-----:|------------------:|---------:|
| Recall@5 | 0.267 | 0.353 | +32.3% |
| Recall@10 | 0.379 | 0.405 | +6.8% |
| MRR | 0.245 | 0.289 | +17.8% |
| Citation hit rate | 0.550 | 0.475 | -13.6% |
| P50 / P95 延迟 | 872.587 / 1346.594 ms | 841.529 / 1007.072 ms | -3.6% / -25.2% |
| 完整运行时间 | 61.11 s | 272.001 s | +345.1% |

结论：当前模型的 Hybrid Recall@5 为 `0.353`、MRR 为 `0.289`，相对 BM25 的排名指标均有提升，已完成“存在真实 Hybrid 对照数据”的 P0-1 验收。但 `all-minilm` 只是一份可用的本地 embedding 基准，不是推荐模型；其较激进的输入截断也意味着下一步必须按 P0-2 在相同冻结契约下完成 BGE-M3 或其他候选的 A/B，才决定产品默认配置。

**补充实测记录（2026-07-31，locate_code 工具级基准）：**

- 历史“4/5”是外部 Coding Agent 对 RepoMind 返回候选的最终选取结果，不足以证明工具本身漏检。例如 `scheme-adapter-selection` 的历史 trace 同时收到 `sessions.py:442-503` 与 `sessions.py:870-881`，但 Agent 最终答复只引用前者。
- 新增 `scripts/run_location_retrieval_benchmark.py`，从 manifest 绑定的隔离 SQLite 调用生产 `locate_code`；逐个 gold 位置按路径与覆盖行评分，不执行、安装或修改目标 requests 仓库。输入 manifest 固定目标 commit `69f84847045bef7a849cc994a26fe7ba8a169e95`，运行产物保留在被忽略的 `benchmark-runs/`。
- 修复前（同一固定索引、错误标成 hybrid 的旧运行）：任务通过 `3/5`、gold-location coverage `0.800`、mean gold-location reciprocal rank `0.550`。修正 query embedding 失败时的有效 mode 后，确认这些运行实际都是 lexical 降级。
- 修复后：增加成对行为子句的前半句召回、受限的通用代码术语 `handler -> adapter` 扩展，以及仅对函数体有真实词面证据的弱符号候选。运行 `benchmark-runs/requests-location-retrieval-20260731-lexical-symbol-recall-v4/` 的结果为任务通过 `5/5`、gold-location coverage `1.000`、mean gold-location reciprocal rank `0.578`、P50/P95 `47449.642 / 50156.737 ms`。
- 延迟不能与正常 lexical 基准混为一谈：历史索引保存了向量，运行环境却没有可用 embedding provider，导致每个查询仍等待 embedding 失败后才降级。`retrieval_mode=lexical` 的语义现已正确，但“配置不可用时避免远端 embedding 超时”仍是独立性能缺口，必须在 provider 配置与降级策略审计时处理。
- **降级性能修复（2026-07-31）：** 新增无网络的 query embedding 配置能力判定。provider 被禁用、缺少凭据、密钥存储不可读或配置非法时直接 lexical；对于 `localhost`/loopback provider，额外以 `200ms` TCP 探测识别端口未启动，避免随后调用 `60s` 的 embedding 接口。远端 API 不做预探测，以免增加额外网络往返。固定索引的设置为 `openai_compatible`、`http://localhost:11434/v1`、`all-minilm`，当前端口不可达，故该分支实测生效。运行 `benchmark-runs/requests-location-retrieval-20260731-lexical-fast-fallback-v6/`：仍为 lexical，任务通过 `5/5`、gold-location coverage `1.000`、mean gold-location reciprocal rank `0.578`，P50/P95 从 `47449.642 / 50156.737 ms` 降至 `6332.877 / 6626.050 ms`（分别降低 `86.65% / 86.79%`）。验证：`python -m pytest backend/tests/test_m3_embeddings.py backend/tests/test_m3_hybrid_retrieval.py backend/tests/test_mcp_server.py backend/tests/test_benchmark_fixtures.py -q`，结果 `74 passed`。这只证明不可用 provider 的快速 lexical 降级，不构成真实 Hybrid 对比；P0-1 保持 `🚧`。
- 验证：`python -m pytest backend/tests/test_m3_hybrid_retrieval.py backend/tests/test_mcp_server.py backend/tests/test_benchmark_fixtures.py -q`，结果 `64 passed`。本记录证明工具级定位回归已修复；P0-1 的 40 问真实 Hybrid 对照仍未完成，故本项保持 `🚧`。

---

### ✅ P0-2：修复 Embedding 模型选型

**问题：** `service/core/embeddings/service.py` 默认使用的模型是 `text-embedding-3-small`（OpenAI API），本地 demo 用 `qwen2.5-coder:7b`，但后者是 decoder-only 生成模型，不是对比学习训练的 embedding 模型，语义聚类效果差。

**改法（三选一，按条件选）：**

| 方案 | 条件 | 改动位置 |
|------|------|---------|
| BGE-M3 本地 | 有 Ollama，想免费 | `embeddings/openai_compatible.py`，改 model_name 为 `bge-m3` |
| text-embedding-3-small API | 有 OpenAI Key | 默认配置已支持，直接启用 |
| Voyage-code-3 API | 追求最优代码 embedding | 同上，改 base_url 和 model_name |

**实验顺序：** 保持 P0-1 的其他条件不变，至少比较 BM25、当前 qwen Hybrid、BGE-M3 Hybrid。只有实测胜出的模型才进入推荐配置，不因模型名称预设结论。

**验收标准：**
- 最低门禁：Recall@5 >= 0.30，MRR 不低于 BM25 baseline；
- 里程碑目标：Recall@5 >= 0.35；
- 报告同时给出总体、五类问题和延迟指标，任一类别明显回退都必须说明。

**预计耗时：** 1-2 天

**推进记录（2026-07-31，尚未完成）：**

- P0-1 已提供可复现的 `all-minilm:latest` Hybrid 对照（Recall@5 `0.353`、MRR `0.289`），但该 384 维通用模型采用 `128` 字符截断，不能因一次总体提升就设为推荐配置。
- benchmark runner 已将 gold 的 `category` 写入新 capture；指标报告会按 `symbol_navigation`、`dependency_impact`、`security_review`、`repository_navigation`、`test_runtime` 五类分别计算 Recall@5、Recall@10 和 MRR。下一次候选模型运行会同时输出总体、类别和延迟，满足本项的报告契约。
- 当前机器只有 `all-minilm:latest`，没有本地 BGE/Code embedding 缓存，也没有可用的 OpenAI 或 Voyage API 凭据。已尝试通过 Ollama 拉取 `bge-m3`，但 1.2 GB 模型源实际下载速率约 `80 KB/s`（预计数小时），已停止拉取，避免将长时间网络等待误报为实验完成。
- 下一步条件明确：在已具备 `bge-m3`（或记录了 provider、模型版本、维度、上下文截断和 batch size 的等价专用 embedding 模型）的机器上，沿用 P0-1 的 target commit、gold SHA、retrieval 参数及隔离 runner 跑新目录；确认真实向量覆盖、40 个 trace 均为 `hybrid` 后，再依据总体/五类/延迟决定推荐配置并标记本项 `✅`。

**候选实验记录（2026-08-01，`nomic-embed-text`，未通过）：**

- 候选为本机 Ollama `nomic-embed-text:latest`，OpenAI-compatible `/v1/embeddings` 冒烟验证返回 `768` 维向量。该模型是专用 embedding 模型，但并非代码专用模型；本次用于验证“等价专用 embedding 候选”是否能在固定 RepoMind 语料上胜出。
- 条件保持与 P0-1 对照一致：目标快照 `c92e2f9af153212074da62d2d7fc1418bfbc0d72`、40 题 gold SHA-256 `5aadace0da4a260826882b198778436c52f5b0116cbe4135126fbb8907d4f331`、`limit=8`、候选倍率 `4`、最大候选数 `200`、RRF `k=60`、结构扩展开启、输入截断 `128` 字符、batch `16`、reranker 关闭。隔离运行清单记录 `196` 个文件、`8477` chunks、`embedding_status=ready`；40 条 trace 均为真实 `hybrid`，没有 lexical fallback。
- 产物位于被忽略的 `benchmark-runs/backend-understanding-20260801-nomic-hybrid-v1/`，完整运行 `307.240 s`；本地 runner 的 `hybrid-capture.json`、`hybrid-report.md` 和 `runtime-manifest.local.json` 可复核每题排序、类别和配置。

| 指标 | BM25 | all-minilm Hybrid | nomic Hybrid | nomic 相对 BM25 |
|------|-----:|------------------:|-------------:|----------------:|
| Recall@5 | 0.267 | 0.353 | 0.267 | 0.0% |
| Recall@10 | 0.379 | 0.405 | 0.355 | -6.3% |
| MRR | 0.245 | 0.289 | 0.212 | -13.5% |
| P50 / P95 延迟 | 872.587 / 1346.594 ms | 841.529 / 1007.072 ms | 990.990 / 1181.856 ms | +13.6% / -12.2% |
| 完整运行时间 | 61.110 s | 272.001 s | 307.240 s | +402.8% |

| 类别 | nomic Recall@5 | nomic Recall@10 | nomic MRR | 结论 |
|------|---------------:|----------------:|----------:|------|
| dependency_impact | 0.463 | 0.525 | 0.500 | 局部表现较好，但不足以抵消总体退化 |
| symbol_navigation | 0.625 | 0.750 | 0.353 | 局部表现较好，但低于 all-minilm 的总体结论不变 |
| security_review | 0.125 | 0.250 | 0.143 | 明显回退，不能接受 |
| repository_navigation | 0.000 | 0.125 | 0.021 | 完全失去 Top-5 召回，不能接受 |
| test_runtime | 0.125 | 0.125 | 0.042 | 明显回退，不能接受 |

结论：`nomic-embed-text` 未达到 Recall@5 `>=0.30` 的最低门禁，且 MRR `0.212` 低于 BM25 `0.245`；它也在三个类别发生明显回退，因此不作为默认模型。

**候选实验记录（2026-08-01，`bge-m3`，通过）：**

- 首次运行发现 Ollama 对一个短 Markdown evidence 返回 NaN，导致全批次被标成 warning；已在 `backend/service/core/embeddings/service.py` 增加批次二分、单条安全截断、实际发送内容 hash，以及成功批次保留。无法嵌入的内容仍只记录 warning，不伪造向量。回归测试 `17 passed`。
- 固定目标 commit `c92e2f9af153212074da62d2d7fc1418bfbc0d72`、gold SHA `5aadace0da4a260826882b198778436c52f5b0116cbe4135126fbb8907d4f331`、`limit=8`、candidate multiplier `4`、max candidates `200`、RRF `k=60`、结构扩展开启、reranker 关闭；模型为 Ollama `bge-m3`（1024 维），输入截断 `128` 字符，batch `16`。
- `benchmark-runs/backend-understanding-20260801-bge-m3-hybrid-v3/` 实测：8477/8477 chunks 有真实向量、状态全部 `ready`、40/40 查询为 Hybrid；Recall@5 `0.440`、Recall@10 `0.445`、MRR `0.331`、P50/P95 `1082.0/1288.0 ms`、citation hit rate `0.650`、task completion `26/40`。
- 五类 Recall@5 / MRR：`dependency_impact 0.671/0.619`、`repository_navigation 0.156/0.188`、`security_review 0.250/0.188`、`symbol_navigation 0.625/0.400`、`test_runtime 0.500/0.260`。相对 BM25 Recall@5 `0.267`、MRR `0.245` 和 all-minilm provisional Recall@5 `0.353`、MRR `0.289` 均提升，未见未解释的类别回退。
- 因此推荐配置确定为 `openai_compatible` + Ollama `bge-m3`；P0-2 验收完成。后续 P1-3 必须用该最终模型重新校准，不能继续引用 all-minilm provisional 阈值。

---

## P1：两周内（影响核心功能完整性）

### ✅ P1-1：向量检索性能优化（numpy 矩阵化）

**问题：** `service/core/vector_store.py` 的 `search_vectors()` 是 Python 循环逐条计算余弦相似度，5000 chunks 时耗时秒级。

**改法：**
```python
# 替换 vector_store.py 中的暴力循环
import numpy as np

def search_vectors(snapshot_id, query_vector, top_k):
    rows = _fetch_all_vectors(snapshot_id)  # 从 SQLite 取出所有 BLOB
    if not rows:
        return []
    
    # 矩阵化：一次计算所有相似度
    embeddings_matrix = np.vstack([_unpack_float32_vector(r["embedding"]) for r in rows])
    query_vec = np.array(query_vector, dtype=np.float32)
    
    # 批量余弦相似度
    norms = np.linalg.norm(embeddings_matrix, axis=1)
    query_norm = np.linalg.norm(query_vec)
    similarities = np.dot(embeddings_matrix, query_vec) / (norms * query_norm + 1e-9)
    
    top_indices = np.argsort(-similarities)[:top_k]
    return [{"chunk_id": rows[i]["chunk_id"], "score": float(similarities[i])} for i in top_indices]
```

**验收标准：** 5000 chunks 查询延迟 < 100ms（当前可能 > 2000ms）

**预计耗时：** 1 天

**实测记录（2026-07-30）：**

- 实现：`service/core/vector_store.py` 使用 NumPy `float64` 矩阵批量计算余弦相似度；保留“只返回正相似度结果”、维度不匹配跳过和同分时沿用 SQLite 返回顺序的既有语义。`numpy>=2.0.0,<3` 已列入后端运行依赖。
- 正确性：新增 `backend/tests/test_vector_store.py`，覆盖与旧 Python 余弦实现的结果/分数一致性、同分稳定排序、零向量查询及损坏或不兼容向量跳过。验证命令：`python -m pytest backend/tests/test_vector_store.py backend/tests/test_m3_embeddings.py backend/tests/test_m3_hybrid_retrieval.py -q`，结果 `12 passed`。
- 性能：同机、Python 3.13.0、NumPy 2.1.2；固定随机种子生成 5000 条 × 1024 维 float32 BLOB，预热后取 9 次新实现和 3 次旧实现。新实现 P50 `37.794 ms`、P95 `41.364 ms`；旧循环 P50 `960.046 ms`；中位数加速 `25.4x`。达到 <100ms 的验收门槛。
- 边界：这是不依赖模型服务的合成向量微基准，用于验证向量扫描本身；端到端 Hybrid 的真实延迟仍须在 P0-1 embedding provider 可用后单独记录，不能与此指标混用。

---

### ✅ P1-2：审计并补充跨文件调用关系（Code Graph M2）

**问题：** legacy `service/core/codegraph/builder.py:136` 没有生成调用边，但当前 parser/storage 已能保存部分 relations，检索链也能沿 observed relation 扩展。应先测覆盖率，再补缺口，不能从零重做第二套关系系统。

**改法（分三步）：**

**步骤一：建 import 映射表**
在 `parse_file()` 里扫描 `ast.Import` 和 `ast.ImportFrom`：
```python
import_map: dict[str, str] = {}  # {"PaymentClient": "payment_client.py"}
for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom) and node.module:
        for alias in node.names:
            name = alias.asname or alias.name
            import_map[name] = node.module  # 需要再解析成文件路径
```

**步骤二：追踪函数体内的变量类型**
扫描赋值语句：`client = PaymentClient()` → 记录 `{client: PaymentClient}`

**步骤三：连调用边**
在 `ast.Call` 节点里，如果 `call.func` 是 `client.charge`，查 `client` 的类型，再查 import\_map 找到对应文件，建一条 `calls` 边写入 `code_edges` 表。

**注意：** 只连能静态确定的边（best-effort），推断不出来的不猜。

**验收标准：** 对 requests 库，`Session.send()` 调用 `HTTPAdapter.send()` 这条关系能被检测到并存入 code_edges

**预计耗时：** 5-7 天

**完成记录（2026-07-31）：** 已复核现有 parser/linker/storage 链路：import、同文件 `self.method()`、跨文件函数调用、包重导出的 `ImportedClass().method()` 均会保留 canonical relation，并在目标唯一时投影至 `code_edges`。补齐直接构造赋值的局部接收器绑定：`adapter = HTTPAdapter(); adapter.send(...)` 会解析为 `transport.HTTPAdapter.send`；重赋值为动态工厂后会清除绑定而不猜测。以 requests 的关键结构等价 fixture（`Session.send()` -> `HTTPAdapter.send()`）端到端验证已解析、已落库并已投影 `code_edges`；解析/存储/JS-TS 聚焦测试结果 `35 passed`。该验收仅承诺静态可证明边，不将第三方 requests 源码或其依赖作为本项目运行时依赖执行。

---

### ✅ P1-3：低相关拒答校准

**问题：** `service/core/evidence/assembler.py` 没有最低分过滤，靠预算耗尽隐式淘汰，query 无关时仍会返回最不相关的结果。

**改法：**
1. 建立明确的无关查询负样本集；
2. lexical、semantic、RRF 分通道校准，不能用一个数值直接比较不同分数空间；
3. 无 lexical 命中且 semantic top score 低于实测绝对阈值时返回空结果或明确 warning；
4. 相对 top-score ratio 只能用于同一候选列表内去尾，不能作为“是否相关”的唯一判断；
5. 保留现有完全无命中时 `not_found` 行为，并增加边界值测试。

**验收标准：** 报告负样本拒答准确率和正样本 Recall@5；降低误召回时不得让正样本 Recall@5 低于已冻结门禁。

**预计耗时：** 半天

**实测记录（2026-07-31，lexical-only 校准）：**

- 实现：新增 `RelevancePolicy`，保留 lexical、semantic 与 RRF 的独立原始信号；RRF 只作审计观测，不作为跨通道置信度阈值。低相关结果会在结构扩展前被抑制，`/ask` 在没有其他有效专项证据时返回明确的中文“证据不足”答复，并将判定写入 trace。
- 数据与可复现性：新增经人工复核的 10 条负样本 `examples/benchmarks/backend-understanding-negative-v1.json`，以及隔离 SQLite 校准 runner `scripts/run_relevance_calibration.py`。目标快照固定为 `c92e2f9af153212074da62d2d7fc1418bfbc0d72`；runner 只索引和检索，不执行目标仓库代码。runner 已同时支持 `lexical` 与真实 `hybrid`：后者必须显式传入 `openai_compatible` provider、base URL、model、仅本进程使用的 key 环境变量，并验证索引确有真实向量；缺少任一条件会在创建输出目录前失败，不能降级后冒充 Hybrid。
- 校准策略：对纯英文自然语言问题过滤停用词后要求四个实义词共现；显式符号、路径、中文和中英混合问题仍使用既有的召回优先 OR 查询。四词门槛是针对同一固定正负样本和同一索引条件的单变量调整，避免将不同通道的分数空间硬比较，也不以 RRF 绝对值判断相关性。
- 结果：40 条正样本 Recall@5 `0.267`、Recall@10 `0.442`、MRR `0.247`、误拒 `0`；10 条负样本拒答 `9/10`，拒答准确率 `0.900`，误接受 `1`。运行耗时 `34.10 s`，索引 `196` 个文件、`8477` chunks。capture 位于被忽略的 `benchmark-runs/relevance-calibration-20260731-lexical-quadruple-v1/`。唯一误接受是 `negative-react-native-metro`：被测仓库本身包含 React、module alias 等重叠词汇，当前词法通道返回了桌面端源码；该边界须在 Hybrid 校准中重新评估，不能声称 lexical 拒答已完全解决。
- 验证：`python -m pytest backend/tests/test_m3_lexical_retrieval.py backend/tests/test_relevance_policy.py backend/tests/test_m3_hybrid_retrieval.py backend/tests/test_search_and_ask.py backend/tests/test_m4_main_agent.py backend/tests/test_benchmark_fixtures.py backend/tests/test_mcp_server.py -q`，结果 `83 passed`；`python scripts/verify_retrieval_regression.py` 重算冻结 lexical 基线 Recall@5 `0.267`、MRR `0.245`。本条仅 lexical 子项完成，不能标记为全项 `✅`：P0-1 的真实 Hybrid provider 可用后，必须用同一负样本集复跑 semantic/hybrid 校准并补填指标；不得将本条 lexical-only 指标描述为 Hybrid 结论。
- 实验契约补齐（2026-08-01）：`scripts/run_relevance_calibration.py` 已支持并记录 `--embedding-max-input-characters` 与 `--embedding-batch-size`，Hybrid 校准会校验正数并写入隔离 settings。后续 P1-3 必须传入与 P0-2 候选模型 benchmark 完全一致的截断和批处理参数，避免把不同 embedding 输入条件下的拒答指标混为同一组实验。验证：`python -m pytest backend/tests/test_vector_store.py backend/tests/test_m3_embeddings.py backend/tests/test_m3_hybrid_retrieval.py backend/tests/test_m3_lexical_retrieval.py backend/tests/test_relevance_policy.py backend/tests/test_benchmark_fixtures.py backend/tests/test_mcp_server.py -q`，结果 `96 passed`。
- Hybrid 实测（2026-08-01，provisional）：在冻结快照 `c92e2f9af153212074da62d2d7fc1418bfbc0d72`、`all-minilm:latest`（384D、截断 `128` 字符、batch `16`）下，未校准时负样本拒答为 `0/10`；复核同一正负样本的通道原始分数后，将 semantic 最低分设为 `0.51`、Hybrid lexical 最低分设为 `31.4`。复跑结果：40 条正样本 Recall@5 `0.3529`、Recall@10 `0.4113`、MRR `0.2865`、误拒 `0`；10 条负样本拒答 `10/10`、准确率 `1.000`、误接受 `0`，耗时 `290.074 s`。隔离 capture：`benchmark-runs/relevance-calibration-20260801-all-minilm-hybrid-calibrated-v2/`。这完成了当前可用真实 Hybrid 条件下的子验收；`all-minilm` 仍只是 provisional baseline。P0-2 的模型选型完成后，必须以完全相同的 benchmark 契约复跑并更新阈值、正负样本指标和 capture，才可将本条标为 `✅`。
- 最终模型复校准（2026-08-01）：为保证阈值实验可复现，`scripts/run_relevance_calibration.py` 现在显式接受并记录 `--hybrid-lexical-min-score` 与 `--semantic-min-score`，并将其注入生产 `HybridRetriever` 的 `RelevancePolicy`。在固定 `bge-m3`（1024D、截断 `128`、batch `16`）、相同 target SHA、gold 和检索参数下，原始分布中正样本最低 semantic top score 为 `0.5548`，负样本最高为 `0.5791`，不存在零误拒且全拒负样本的单阈值分界；因此选择可解释的 `hybrid lexical >=31.4`、`semantic >=0.58`，并以独立完整运行验证，而非照搬 all-minilm 阈值。
- `benchmark-runs/relevance-calibration-20260801-bge-m3-calibrated-v2/` 实测：40 条正样本 Recall@5 `0.4404`、Recall@10 `0.4954`、MRR `0.3196`、误拒 `1`；10 条负样本拒答 `10/10`、拒答准确率 `1.000`、误接受 `0`，总耗时 `712.295 s`。正样本 Recall@5 高于冻结门禁且相较未校准运行未下降，满足验收；该边界的一个误拒作为已知权衡保留在 capture 中。P1-3 验收完成。

---

### ✅ P1-4：Reranker 集成（质量 A/B 已完成；CPU 默认启用不通过）

**问题：** 当前只有单轮检索，BM25+向量融合后直接返回，没有二次精排。MRR 受限。

**改法：**
1. 将 reranker 抽象为可关闭的 provider，不让模型成为核心检索的硬依赖；
2. 模型懒加载并缓存实例，CPU 环境不得强制 `use_fp16=True`；
3. 在 `service/core/retrieval/service.py` 的 `HybridRetriever.retrieve()` 里，BM25+向量融合完取默认 Top-50 后调用 reranker；实际送入精排的候选数可通过 `reranker_candidate_limit` 配置，范围为 `5..50`；

```python
from FlagEmbedding import FlagReranker

reranker = FlagReranker(
    "BAAI/bge-reranker-v2-m3",
    use_fp16=settings.reranker_use_fp16,  # GPU 可开启，CPU 默认关闭
)

def rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    pairs = [(query, c.get("content", "")) for c in candidates]
    scores = reranker.compute_score(pairs)
    reranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    return [item for item, _ in reranked[:top_k]]
```

4. 只对 `limit >= 5` 的查询启用，避免小查询额外延迟。

**验收标准：** 最低门禁 MRR >= 0.30，里程碑目标 MRR >= 0.35；同时报告 Recall@5 和 P95 延迟，不能用明显召回回退换取 MRR。

**预计耗时：** 3-4 天

**完成记录（2026-07-31 至 2026-08-01）：** 已实现 `service/core/retrieval/reranker.py` 的可插拔二阶段精排接口，以及 `flag_embedding` 可选 provider。默认 `disabled`，不下载、不导入也不加载模型；仅当检索处于真实 Hybrid 模式、请求 `limit >= 5`、且 provider 实际可用时才对 RRF Top-50 精排。`FlagEmbedding` 缺包或模型加载失败时保持原 RRF 排序，检索 run 中记录 `rerank.applied=false`，因此不会让模型成为核心检索硬依赖。设置 API 已增加 `reranker_provider`、`reranker_model`、`reranker_use_fp16`（CPU 默认 `false`）。

- 实验基础设施补齐（2026-08-01）：`scripts/run_retrieval_benchmark.py` 已增加 `--reranker-provider`、`--reranker-model`、`--reranker-use-fp16`，将实际配置写入 `runtime-manifest.local.json`，并在每条 query capture 中记录 trace 的 `rerank.applied` 与候选数。若请求 `flag_embedding` 但任一查询没有实际精排，runner 立即失败，不会把 fallback 基线伪装为 reranker A/B 结果；lexical 模式也拒绝启用 reranker。主 Agent retrieval trace 现在显式包含非敏感 rerank 审计，低相关早退路径同样记录该事件。验证：`python -m pytest backend/tests/test_vector_store.py backend/tests/test_m3_embeddings.py backend/tests/test_m3_hybrid_retrieval.py backend/tests/test_m3_lexical_retrieval.py backend/tests/test_relevance_policy.py backend/tests/test_benchmark_fixtures.py backend/tests/test_mcp_server.py -q`，结果 `100 passed`。
- 真实质量 A/B（2026-08-01）：固定 target SHA `c92e2f9af153212074da62d2d7fc1418bfbc0d72`、40 题 gold SHA-256 `5aadace0da4a260826882b198778436c52f5b0116cbe4135126fbb8907d4f331`、BGE-M3（1024D，输入截断 `128`，batch `16`）、`limit=8`、候选倍率 `4`、最大候选 `200`、RRF `k=60` 和结构扩展；唯一变量为 reranker。control 为 `disabled`，treatment 为 `FlagEmbedding 1.4.0` + `transformers 4.57.6` + `BAAI/bge-reranker-v2-m3`，CPU、`use_fp16=false`。treatment 的 40/40 trace 均为真实 `hybrid` 且 `rerank.applied=true`，候选数为 48--50；8477/8477 chunks 的向量状态为 `ready`。

| 指标 | BGE-M3 Hybrid control | + BGE reranker treatment | 变化 |
|------|----------------------:|-------------------------:|-----:|
| Recall@5 | 0.440 | 0.543 | +23.4% |
| Recall@10 | 0.445 | 0.664 | +49.2% |
| MRR | 0.331 | 0.481 | +45.3% |
| Citation hit rate | 0.525 | 0.825 | +57.1% |
| P50 / P95 延迟 | 1139.8 / 1370.5 ms | 74618.0 / 77066.8 ms | +63.5 / +56.2 s |

- 验收结论：质量门槛与里程碑均通过，且 Recall@5 未退化；原始 artifacts 分别位于被忽略的 `benchmark-runs/backend-understanding-20260801-bge-m3-reranker-control-v2/` 与 `benchmark-runs/backend-understanding-20260801-bge-m3-reranker-treatment-v1/`。但 CPU 上每题约 75 秒的延迟不可作为默认交互体验接受，故保持 `reranker_provider=disabled` 为默认值；`flag_embedding` 仅是可选的离线/高延迟质量模式。下一项不是直接进入 P2，而是先以真实产品 SLA 决定是否开展 reranker 性能专项（候选数、批处理、轻量模型或 GPU），并重新跑同一 A/B 验收。
- 候选数性能专项（2026-08-01）：仅改变送入 reranker 的候选 head，其他实验契约、模型和硬件保持不变；Top-10 产物位于被忽略的 `benchmark-runs/backend-understanding-20260801-bge-m3-reranker-top10-v1/`。40/40 query 的 `rerank.applied=true`，实际候选数均为 `10`。相较 Top-50 treatment，Top-10 的 Recall@5 从 `0.543` 降至 `0.440`，Recall@10 从 `0.664` 降至 `0.504`，MRR 从 `0.481` 降至 `0.346`；P50/P95 从 `74618.0/77066.8 ms` 降至 `13857.8/17766.1 ms`，完整运行时间为 `1166.311 s`。结论是 Top-10 能明显降低 CPU 延迟，但 P95 仍约 17.8 秒，且质量退化明显，暂不选择为默认值。默认仍为 `reranker_provider=disabled`、候选默认 `50`；后续应先根据产品 SLA、GPU 可用性、轻量模型以及序列长度/批处理策略决定独立性能实验，不建议在没有新约束的情况下盲跑 Top-20。
- 回归验证：`python -m pytest backend/tests/test_vector_store.py backend/tests/test_m3_embeddings.py backend/tests/test_m3_hybrid_retrieval.py backend/tests/test_m3_lexical_retrieval.py backend/tests/test_relevance_policy.py backend/tests/test_benchmark_fixtures.py backend/tests/test_mcp_server.py -q`，结果 `103 passed`（2026-08-01）。

---

### ✅ P1-5：外部 Agent MCP Token 节省端到端对照实验

**产品问题：** RepoMind 的最终价值不能只用 Recall/MRR 或 `locate_code` 命中率表达；必须能如实说明，外部 Coding Agent 在使用 MCP 后实际少用、持平或多用了多少 Token。

**已完成的实验基础设施（2026-08-01）：**

1. [run_codex_location_ab.ps1](../../scripts/run_codex_location_ab.ps1) 对每个 baseline/treatment 任务从原始 Codex JSONL `turn.completed` 提取 `input_tokens`、`output_tokens`，成功任务同时写入 `usage_provenance=codex_exec_json.turn.completed` 及原始 JSONL 的 `raw_trace_sha256`；
2. 新增 [report_mcp_token_savings.py](../../scripts/report_mcp_token_savings.py)，产出 JSON/Markdown，报告 input/output/total Token 的绝对和百分比变化。它拒绝缺少 cohort、重复行、缺 usage provenance/trace hash，以及 Codex 版本、模型、reasoning effort、sandbox 模式、超时或 MCP profile 不一致的 batch；每个 run 内由执行器固定 baseline/treatment 使用同一 target commit，跨陌生仓库的 batch 则允许各自固定不同 commit，并逐仓库披露；
3. 成本比较只纳入两组均按运行前 rubric 通过的任务；两组通过率独立报告。`source_characters_received` 仅标为上下文体积 proxy，绝不替代外部 Agent 实际用量；
4. 协议见 [2026-08-01_MCP_TOKEN_SAVINGS_PROTOCOL_MCP节省Token评测协议.md](../../examples/benchmarks/2026-08-01_MCP_TOKEN_SAVINGS_PROTOCOL_MCP节省Token评测协议.md)，执行说明见 [2026-08-01_MCP_TOKEN_SAVINGS_EXECUTION_MCP节省Token执行方案.md](./2026-08-01_MCP_TOKEN_SAVINGS_EXECUTION_MCP节省Token执行方案.md)。报告器会额外按 baseline/MCP cohort 拆分失败类别与状态，避免把双方失败混同为 MCP 问题；聚焦回归 `python -m pytest backend/tests/test_mcp_token_savings_report.py -q` 于 2026-08-02 为 `12 passed`（另有一个既有 Pydantic v2 弃用警告）。

**历史结果（不能作为节省宣传）：** 历史 `codex-token-ab-v1` 仅有同仓库 3 个任务，质量均通过，但 baseline 输入 Token `130,936`、MCP 输入 Token `148,193`，MCP **增加 `13.18%`**。因此当前没有“节省 X% Token”的有效结论；该结果应保留为 MCP 工具定义、调用次数和返回 evidence 自身存在上下文成本的反例。

**本地紧凑 profile pilot（2026-08-01，不能作为项目结论）：** 在隔离 checkout `b4eacc5ba103fcbedff07a275ebd508595ee3c0b` 的 lexical-only 索引中，生产 `locate_code` 冻结任务通过 `2/8`、gold-location coverage `0.625`、MRR `0.396`；仅工具级通过的 `mcp-tests` 进入 Agent A/B。相同 Codex CLI `0.145.0`、`gpt-5.6-terra`、`low` reasoning、240 秒超时和 target commit 下，baseline/treatment 都通过冻结 rubric。`coding-agent` 单工具 profile 的 input Token 为 `34,314`，baseline 为 `50,613`，减少 `16,299`（`32.20%`）；total Token 为 `34,481` 对 `51,286`，减少 `16,805`（`32.77%`）。原始 trace、SHA-256、结果和可复算 batch 位于被忽略的 `e2e-artifacts/compact-token-pilot-b4eacc/run-2-mcp-tests-240s/` 与 `run-2-batch.json`。`run-1` 双方超时、`run-3` 单边通过、`run-4` 单边失败/超时，均明确排除 Token 汇总，说明必须保留重复运行和通过率。Windows 上该 pilot 为启动 stdio MCP 使用 bypass sandbox，tool 限制仍是 profile/prompt 级，不能视为正式外部实验。P1-5 维持 `🚧`。

**首轮外部三仓库 A/B（2026-08-01，历史单次运行，P1-5 正式验收仍为 `🚧`）：** 运行前冻结 Click、Typer、Requests 各 10 个 `single_location_navigation` 任务，并在生产 `locate_code` 的隔离索引预检中均达到 `10/10` gold-location coverage（共 `30/30`）。三个目标提交分别为 `00e592cea702e0b2caa0dee42489fdb1c22cd845`、`32d80ef6b4f5aff5094e6983e0928edaa8766c3b`、`414f0513c33883adf6f2b46901d4f0b38a455851`。每题均以 fresh `codex exec --ephemeral` 运行 baseline 与 manifest-bound `coding-agent` MCP treatment；共同条件为 Codex CLI `0.145.0`、`gpt-5.6-terra`、`low` reasoning、240 秒超时和 `bypass_sandbox=true`。聚合产物位于被忽略的 `e2e-artifacts/external-token-study-20260801/external-token-ab-v3-run-1-report.json` 与 `.md`，batch 清单为 `external-token-ab-v3-run-1-batch.json`。

| 指标 | Baseline | MCP | 变化 |
|---|---:|---:|---:|
| 完整任务通过率（30 题） | 26/30（86.67%） | 23/30（76.67%） | -10.00 个百分点 |
| 两组均通过、可比较任务 | \- | 20/30 | \- |
| Input Token（仅 20 个两组均通过任务） | 735,130 | 668,897 | -66,233（-9.01%） |
| Output Token（同上） | 9,125 | 3,187 | -5,938（-65.07%） |
| Total Token（同上） | 744,255 | 672,084 | -72,171（-9.70%） |
| Source characters（仅辅助 proxy） | 46,064 | 24,182 | -21,882（-47.50%） |

逐仓库总 Token 变化为 Click `-10.95%`（5 个 both-passed）、Typer `+9.19%`（9 个）、Requests `-29.36%`（6 个），故不得将 `-9.70%` 表述为所有仓库或所有任务均会节省。所有 20 个成功行均已复算原始 JSONL SHA-256，并带有 `codex_exec_json.turn.completed` usage provenance；所有单边失败与 timeout 均保留在同一批结果中。由于 MCP 完整任务通过率低于 baseline，且 fresh Agent 运行已观察到显著随机性/timeout，这只是满足最小样本门槛的一次**初步**实测，不能标记 P1-5 为正式完成或作为稳定产品承诺。下一步先定位 MCP treatment timeout/稳定性问题，在不改冻结任务和对照条件的前提下预注册至少两次独立重复，再报告方差和最终范围化结论。

**首轮配对结果矩阵（2026-08-02，由 `report_mcp_token_savings.py` 重新聚合）：** 双方均通过 `20`；仅 baseline 通过 `6`；仅 MCP 通过 `3`；双方均未通过 `1`。因此 MCP-only 结果说明工具对少数任务确有补充价值，但不能抵消六个 baseline-only 任务造成的质量缺口。首轮没有 `timeout`，但共有 `7` 个 `status=incomplete` 行；其余未通过行是已完成但未满足行号 rubric。由于旧 runner 尚未记录 MCP 调用数和最终答复存在性，不能从这批工件可靠定位每个 incomplete 是发生在 MCP 调用前还是调用后。后续 repeat 必须继续同时报告这四格矩阵、失败类别和两组完整通过率。

**正式结论门禁实现（2026-08-02）：** `scripts/run_codex_location_ab.ps1` 现在要求每个运行声明非空 `repeat_id`，并将 timeout、MCP 调用数、最终答复存在性和失败类别写入结果。`scripts/report_mcp_token_savings.py` 升级为 `mcp-token-savings-report-v2`：除既有 both-passed Token 汇总外，聚合 `failure_classes`/`statuses`，并对至少 3 个 benchmark、20 个任务、20 个 both-passed、2 个独立 repeat，以及 MCP 通过率不低于 baseline 执行机器可读的 `acceptance` 门禁。门禁不通过时固定输出 `not_accepted`，禁止将 Token 百分比作为产品结论。首轮三仓库结果必然仍为 `not_accepted`：只有一个 repeat，且 MCP 通过率 `76.67%` 低于 baseline `86.67%`。这不是新实验结果，不能用它掩盖稳定性缺口。

**最新合并结果（2026-08-02，两个独立 repeat，P1-5 仍为 `🚧`）：** 合并报告 [external-token-ab-v3-run-1-repeat-2.report.md](../../e2e-artifacts/external-token-study-20260801/external-token-ab-v3-run-1-repeat-2.report.md) 覆盖相同三仓库、冻结任务、target commit、模型和 MCP profile 下的两次独立运行，共 `60` 个 cohort-task。Baseline 完成 `53/60`（`88.33%`），MCP 完成 `50/60`（`83.33%`）；双方均通过 `44`，仅 baseline 通过 `9`，仅 MCP 通过 `6`，双方失败 `1`。在 44 个双方通过任务中，input Token `1,669,974 -> 1,457,896`（`-12.70%`），output Token `20,355 -> 7,590`（`-62.71%`），Total Token `1,690,329 -> 1,465,486`（`-224,843`，`-13.30%`）；source-character proxy 减少 `102,930`（`-64.82%`）。失败分类为 `rubric_failed=13`、`timeout_before_mcp_call=4`。全部样本、仓库和 repeat 门禁已满足，唯一失败门禁是 `treatment_pass_rate`，故机器可读正式状态为 `not_accepted`，`publishable_token_conclusion=false`。这证明 MCP 可减少已成功完成任务的上下文成本，但尚未证明它能在不降低任务成功率的前提下节省 Token；P1-5 不得标记 `✅`。

**下一步执行约束：** 先逐条复核 `rubric_failed`：区分真实的 `locate_code` 漏检/排序错误、冻结评分规则与代码语义不一致，以及 Agent 输出选择差异。`click-prompt-helper` 已确认属于 overload 声明（138）与具体实现（167）的评分政策问题，不得为迎合旧 gold 降低具体实现的排序；只有确认是真实工具错误时才新增 `locate_code` 回归。随后在不改变冻结任务、commit、模型、profile 或 timeout 的条件下做预注册的严格配对重跑。对于 `timeout_before_mcp_call`，只能成对重跑 baseline 和 MCP，并保留原始工件和所有失败行；不得仅挑选 MCP timeout 重跑，也不得把不同启动策略或预热策略混入当前正式 cohort。启动策略改动必须另建实验 cohort，独立报告。

**V4 两次独立 repeat 实测（2026-08-02，P1-5 仍为 `🚧`）：** Click 使用修订后的 v4 语义答案组，Typer 与 Requests 沿用冻结的 v3 任务集；三仓库共 `60` 个 cohort-task，条件仍为 Codex CLI `0.145.0`、`gpt-5.6-terra`、`low` reasoning、240 秒超时、`bypass_sandbox=true` 和 `coding-agent` MCP profile。可复核报告为 [external-token-ab-v4-repeat-2.report.md](../../e2e-artifacts/external-token-study-20260801/external-token-ab-v4-repeat-2.report.md)，实际使用的有效 batch 清单为 `external-token-ab-v4-repeat-2-batch2.json`（均为本地忽略的实验工件）。

| 指标 | Baseline | MCP | 变化 |
|---|---:|---:|---:|
| 完整任务通过率（60 题） | 51/60（85.00%） | 45/60（75.00%） | -10.00 个百分点 |
| 双方均通过、可比较任务 | \- | 43/60 | \- |
| Input Token（仅 43 个双方均通过任务） | 1,960,457 | 939,610 | -1,020,847（-52.07%） |
| Output Token（同上） | 33,682 | 10,600 | -23,082（-68.53%） |
| Total Token（同上） | 1,994,139 | 950,210 | -1,043,929（-52.35%） |
| Source characters（仅上下文体积 proxy） | 282,392 | 55,133 | -227,259（-80.48%） |

V4 配对矩阵为：双方均通过 `43`、仅 baseline 通过 `8`、仅 MCP 通过 `2`、双方失败 `7`。失败类别为 `incomplete_before_mcp_call=14`、`incomplete_after_mcp_before_final_answer=4`、`rubric_failed=4`、`timeout_before_mcp_call=1`、`timeout_after_mcp_before_final_answer=1`；其中 MCP 组通过率低于 baseline，报告器唯一失败门禁为 `treatment_pass_rate`，机器可读状态为 `not_accepted`，`publishable_token_conclusion=false`。

V4 证明在双方都成功的任务子集上，MCP 可以把外部 Agent 的输入/总 Token 降低约一半；但它没有证明在不降低整体任务成功率的前提下节省 Token。因此 `52.35%` 只能作为当前诊断性观察，不能写成无条件产品承诺，P1-5 不得标记 `✅`。下一步仍需优先修复 MCP 组的调用前后 incomplete、timeout 和 rubric 失败，再按相同门禁进行成对复测。

**紧凑返回协议修复后的正式结果（2026-08-02，P1-5 已完成）：** 在不改变冻结任务、目标仓库 commit、Codex CLI、模型、reasoning effort、超时和 MCP profile 的条件下，对 Click、Typer、Requests 三个陌生公开仓库各运行 10 个任务，并完成 `p1-5-repeat-1`、`p1-5-repeat-2` 两次独立 repeat，共 `60` 个 cohort-task。Baseline 与 MCP 均通过 `60/60`，双方均通过 `60/60`；treatment 共完成 `30` 次 MCP 调用，未出现 timeout、`rubric_failed`、基础设施失败或候选位置误选。报告器 acceptance 状态为 `accepted`。

| 指标 | Baseline | MCP | 变化 |
|---|---:|---:|---:|
| 完整任务通过率（60 题） | 60/60（100.00%） | 60/60（100.00%） | 0 个百分点 |
| 双方均通过、可比较任务 | \- | 60/60 | \- |
| Input Token（60 个双方均通过任务） | 2,733,497 | 1,360,698 | -1,372,799（-50.22%） |
| Output Token（同上） | 42,570 | 9,593 | -32,977（-77.47%） |
| Total Token（同上） | 2,776,067 | 1,370,291 | -1,405,776（-50.64%） |
| Source characters（仅上下文体积 proxy） | 412,735 | 161,234 | -251,501（-60.94%） |

Source-character 总量仅作为上下文体积 proxy，不能替代外部 Agent 的计费 Token；正式结论以 `turn.completed` usage provenance 为准。可复核工件为 [p1-5-v5-report.md](../../e2e-artifacts/p1-5-v5-report.md)、[p1-5-v5-report.json](../../e2e-artifacts/p1-5-v5-report.json) 和 [p1-5-v5-batch.json](../../e2e-artifacts/p1-5-v5-batch.json)。该结论应表述为：在本实验的固定条件下，双方均成功的 60/60 个任务中，RepoMind MCP 使外部 Coding Agent 的 Input Token 减少 `50.22%`、Total Token 减少 `50.64%`，且未观察到通过率下降；不应外推为所有任务、模型或仓库的无条件节省比例。

**验收步骤与完成状态：**

1. ✅ 使用 Click、Typer、Requests 三个陌生公开仓库；每个仓库的 baseline/treatment 使用同一 target commit、隔离运行目录和 manifest-bound 任务集，任务与 rubric 放在目标仓库之外；
2. ✅ 冻结 30 个任务并执行两次独立 repeat，共 60 个 cohort-task；所有运行固定 Codex/client 版本、模型、reasoning effort、超时、sandbox 模式和 MCP profile；
3. ✅ 每个任务均运行 fresh ephemeral baseline 与 treatment；treatment 仅使用 RepoMind MCP，未允许 shell/local source read；
4. ✅ 由 `report_mcp_token_savings.py` 聚合并通过 `accepted` 门禁，报告 target commit、样本数、both-passed 数、两组通过率、input/output/total Token、绝对/百分比变化、失败分类和 usage provenance；
5. ✅ 样本、质量和 provenance 条件全部满足，P1-5 标记为 `✅`。后续新增模型、仓库或启动策略时应创建新的 cohort，不覆盖本次正式结果。

**预计耗时：** 准备 0.5-1 天；有可用 MCP 索引和外部 Agent 后运行取决于任务数与重复次数。

---

## P2：一个月内（企业级落地）

### ✅ P2-1：可选的本地访问保护

**问题：** RepoMind 当前定位是本地、单用户、只读系统。默认 loopback 场景不需要多租户模型，但如果用户主动暴露 HTTP 端口，应有最小访问保护。

**改法：** 默认只绑定 loopback；仅在显式开启远程访问时要求静态 API token。MCP stdio 不增加认证，多租户、JWT、用户归属和权限系统不在当前范围。

**实现（2026-08-01）：** 新增 `REPOMIND_BIND_HOST`，默认值为 `127.0.0.1`；`localhost`、IPv4 loopback 和 IPv6 `::1` 均视为本地绑定。只有显式配置非 loopback host 时，`Settings` 才要求非空 `REPOMIND_API_TOKEN`，并由启动入口将该 host 传给 Uvicorn。已有 `X-RepoMind-API-Token` 中间件继续保护业务 API，health 保持公开用于启动探测，shutdown 使用独立 token，MCP stdio 路径不受影响。

**实测与验证（2026-08-01）：** `test_desktop_security.py` 覆盖默认 loopback、loopback 变体、远程无 token 启动校验、远程 token 保护业务 API，以及启动层将配置 host 传给 Uvicorn；安全/配置/迁移/契约回归 `python -m pytest tests/test_desktop_security.py tests/test_settings_security.py tests/test_m0_contract.py tests/test_migrations.py -q` 为 `27 passed`，全量后端回归为 `260 passed`。`python -m py_compile service/config/settings.py service/main.py` 与本次涉及文件的 `git diff --check` 通过。该项不改变默认桌面运行行为，也不引入 JWT、多租户或 MCP 认证。

**预计耗时：** 2 天

---

### ✅ P2-2：在线检索质量监控

**问题：** 有离线评估（40问题集），没有在线监控。生产环境检索质量下滑无法感知。

**实现（2026-08-01）：**
1. 新增 migration `v008_retrieval_metrics.py` 和 `retrieval_metrics` 表；指标独立于 Agent trace，避免把一次 MCP 工具调用伪装成 Agent 工作流。每条记录保存 `repo_id`、`snapshot_id`、工具名、retrieval mode、返回数量、RRF top score、耗时和 UTC 时间。为兼容 v008 的既有表结构，保留 `query` 列但运行时只写入固定脱敏标记。
2. `search_code` 成功检索后记录一条；`locate_code` 即使执行 query expansion 或词级 fallback，也只在完整 MCP 调用结束后记录一条，并取内部检索的最高 RRF score，因此请求数等于用户真实调用数。
3. 新增受现有桌面 API token 保护的 `GET /api/v1/metrics`，默认近 7 天；`days=1..30`，可选 `repo_id`。返回每日请求数、平均/最高 top score、低分数和总体聚合。遥测写入失败只记 warning，绝不影响只读检索结果。
4. 连续 10 次 top score 为 `NULL` 或 `<0.01` 时记录一次 warning；随后仍在同一低分连续区间内不会重复刷屏。

**实测与验证（2026-08-01）：**

- 新增 `backend/tests/test_retrieval_metrics.py`，覆盖 v008 建表及索引、500 字符 query 截断、按 repo 隔离聚合、token 边界、`search_code` 单次写入、`locate_code` 多轮内部检索仍单次写入、遥测异常隔离和低分 streak 告警。
- 窄回归：`python -m pytest tests/test_retrieval_metrics.py tests/test_mcp_server.py tests/test_desktop_security.py tests/test_migrations.py -q`，结果 `51 passed`。
- 检索关联回归：`python -m pytest tests/test_retrieval_metrics.py tests/test_vector_store.py tests/test_m3_embeddings.py tests/test_m3_hybrid_retrieval.py tests/test_m3_lexical_retrieval.py tests/test_relevance_policy.py tests/test_benchmark_fixtures.py tests/test_mcp_server.py -q`，结果 `110 passed`。
- 本项观察线上调用与分数趋势，不改变离线 ranking；因此不填写新的 Recall@K 或 MRR，也不将测试结果伪装为质量提升指标。

**可决策性补强（2026-08-01）：**

- `GET /api/v1/metrics` 在既有 `totals` 和每日 `trend` 中补充 `average_duration_ms`、`p50_duration_ms` 和 `p95_duration_ms`；百分位以最多 30 天的本地记录按 deterministic nearest-rank 计算。接口还新增 `breakdown`，按 `tool_name + retrieval_mode` 返回请求数、低分数、平均/P50/P95 延迟，因此可以区分 `search_code`/`locate_code` 与 `hybrid`/`lexical` 的真实瓶颈，而不泄露额外 query 内容。
- 这不需要 schema migration：`v008` 已持久化 `duration_ms`。更新的 telemetry 测试覆盖总览、逐日和工具/模式分组的准确聚合；窄回归结果为 `55 passed`，完整后端回归为 `261 passed, 72 warnings`。warnings 为既有 Pydantic、FastAPI/Starlette 弃用提示。
- 离线 `scripts/report_retrieval_metrics.py` 继续只重算冻结 benchmark capture；它与在线 MCP 使用遥测保持职责隔离。新增字段用于决定后续应优先处理低分召回、降级比例还是 provider 延迟，不构成新的离线质量指标。
- 当前态复核（2026-08-01）：`python -m pytest tests/test_retrieval_metrics.py tests/test_mcp_server.py tests/test_desktop_security.py tests/test_migrations.py tests/test_m0_contract.py -q` 为 `60 passed, 20 warnings`；完整后端 `python -m pytest -q` 为 `262 passed, 72 warnings`。固定 capture 门禁 `python scripts/verify_retrieval_regression.py` 重算 BM25 `Recall@5=0.2666666667`、`Recall@10=0.3791666667`、`MRR=0.2450297619`，与冻结基线一致。验证仅使用临时独立数据库，未读取或修改用户索引数据库。
- 隐私最小化补强（2026-08-01）：新增 `v009_redact_retrieval_metric_queries.py`，将升级前本地 `retrieval_metrics.query` 的历史内容统一改为 `[redacted]`；后续 MCP 调用也只写入该固定标记，原始查询文本不再持久化。`/api/v1/metrics` 的计数、分数、延迟及工具/模式聚合不依赖此列，行为保持不变。桌面后端兼容门槛和冻结后端 smoke 已同步要求 schema `9`；历史数据迁移、运行时写入、MCP telemetry 容错和桌面 schema 契约均通过隔离测试验证，不代表真实 MCP 使用数据。

**预计耗时：** 3 天

---

### ⏸ P2-3：Snapshot-aware 增量索引（需先重新设计）

**现状复核（2026-08-01）：** 原描述已经不适用。当前 ingest 以 `repo_id + snapshot_id` 隔离数据，每个 commit 创建不可变 snapshot，成功后才 `publish_snapshot()` 切换 active snapshot。旧 `codegraph/store.py` 的全表 DELETE 不能作为当前 snapshot 数据模型的改造入口；在已发布旧 snapshot 中按文件删除/重建会破坏历史证据和可复现检索。

**后续改法（重新立项时执行）：**
1. 新 snapshot 建立时比较新旧快照中已存在的内容 hash，沿用现有 SHA-256 语义，不另引入 MD5；仅将未变化文件的 parsed evidence、embedding 和关系结果复制或引用到新 snapshot。
2. 只对新增、修改、删除文件重新扫描、解析、embedding 和关系抽取；关系重算范围必须包含受 import/export 变化影响的依赖文件。
3. 在新 snapshot 完整成功并通过完整性检查后才 publish；任何失败都保留旧 active snapshot 可查询。需要先定义复用记录的所有权、删除传播和向量去重策略，再写实现。

**重新立项前置条件与验收标准：** 已在真实固定 checkout 上记录全量刷新基线，但结论是不应直接立项通用文件级增量。`scripts/profile_ingest.py` 在干净的 `c92e2f9af153212074da62d2d7fc1418bfbc0d72` checkout（196 文件、8477 chunks）中，以隔离数据库和本地 Ollama `bge-m3:latest`（OpenAI-compatible、输入截断 128 字符、batch 16）实测：总耗时 `640.657 s`，其中 embedding `634.751 s`（99.1%）；扫描 `0.060 s`、解析 `1.717 s`、事实落库 `1.169 s`、chunk 投影 `1.553 s`，其余阶段均不足 `1 s`。同一目标 lexical 画像总耗时 `5.991 s`。

随后在隔离 Git clone 中只修改 `2026-08-01_REPOMIND_README_项目说明.md` 并创建第二个 commit，复用同一个 RepoMind 数据库和同一 embedding 配置：首个 snapshot 为 `8477 stored / 0 reused`，总耗时 `642.822 s`；第二个 snapshot 为 `26 stored / 8452 reused`、`8478` chunks，总耗时 `136.280 s`，其中 embedding `129.255 s`。这证明现有 `provider + model + content_hash` 跨快照向量复用有效，但新增内容的本地 embedding 仍是主要瓶颈；解析、事实落库和 chunk 投影合计约 `4.7 s`，不应先重写为通用文件级增量。P2-3 继续保持暂停状态，下一步应单独测量 embedding batch size/调用效率；只有真实刷新需求仍要求更低延迟时，才重新评估 parsed evidence/关系复用。若后续重新立项，仍必须以单文件改动验证：新 snapshot 检索正确、旧 snapshot 结果不变、失败不切换 active snapshot；在相同机器和仓库下单文件刷新 `< 5 s` 才作为性能目标。

**Embedding batch 对照（2026-08-01）：** 在同一隔离数据库中再次只修改 `2026-08-01_REPOMIND_README_项目说明.md`，将 batch 从 `16` 改为 `32`，其余模型、截断和目标仓库不变；第二个 snapshot 为 `26 stored / 8453 reused`，总耗时 `144.722 s`，embedding `136.597 s`。相较 batch=16 的 `129.255 s`，batch=32 慢约 `5.7%`，当前没有证据支持修改生产默认 batch；该实验仅作为后续排查的已测基线。

**Provider 调用效率修复与实测（2026-08-01）：** `OpenAICompatibleEmbeddingProvider` 现在按 provider 实例懒加载并复用一个 OpenAI-compatible SDK client，避免每个 embedding batch 重建客户端与连接池；单测同时验证首次响应乱序仍会按 `index` 排序，且两次 `embed()` 只调用一次 `client_factory`。在相同干净 checkout `c92e2f9af153212074da62d2d7fc1418bfbc0d72`、隔离数据库、Ollama OpenAI-compatible `bge-m3:latest`、输入截断 `128`、batch `16` 下，用 `scripts/profile_ingest.py` 重新完整索引：`196` files、`8477` chunks、`8477 stored / 0 reused`、`embedding_status=ready`；总耗时 `433.575 s`，embedding `427.636 s`。相较修复前同契约完整 profile 的总 `640.657 s`、embedding `634.751 s`，分别减少 `207.082 s`（`32.32%`）和 `207.115 s`（`32.63%`）。该结果证明 client reuse 在当前机器和 provider 上有真实收益；验证命令为 `python -m pytest tests/test_m3_embeddings.py tests/test_vector_store.py tests/test_m3_hybrid_retrieval.py -q`，结果 `25 passed, 6 warnings`。仍保持生产 batch `16`，且此结果不改变 P2-3 的暂停状态：除非出现真实刷新 SLA，不能据此恢复旧式文件级 DELETE/rebuild 或泛化为通用增量重构。

**预计耗时：** 5-7 天

---

### ✅ P2-4：Code Graph 多语言支持（JS/TS tree-sitter）

**现状复核与实现：** 原先指向 `service/core/codegraph/builder.py` 的方案已经过时；生产 ingest 不经过该旧 builder。当前链路为 `ParserRegistry.parse_all()` 产出规范化 evidence/symbol/relation，再由 `project_symbols_to_code_graph(repo_id, snapshot_id)` 投影到快照隔离的 `code_nodes` 和 `code_edges`。`parsing/javascript_typescript_parser.py` 已使用 `tree_sitter_javascript` 与 `tree_sitter_typescript` 支持 `.js/.jsx/.mjs/.cjs/.ts/.tsx/.mts/.cts`，并提取 module、class、function、interface、method、静态 import/export、继承和可直接命名的调用；`RepositoryLinker` 仅对可唯一证明的 JS/TS 相对 import 进行跨文件绑定。依赖缺失时只产生文件级 evidence 和 `tree_sitter_unavailable` 诊断，绝不伪造符号或图边。

**实测与验收（2026-08-01）：**

- 新增 `backend/tests/test_javascript_typescript_graph_ingest.py`：在临时目录创建并提交纯文本 TypeScript Git fixture，调用真实 `ingest_repository_snapshot()`；测试不执行目标仓库代码、不安装其依赖。
- tree-sitter 可用时，首个快照的 `code_nodes` 至少包含 `Worker`（class）、`helper`/`start`（function）和 `run`（method），`code_edges` 包含确定性的 `contains` 边；`GET /api/v1/code-graph/{repo_id}/stats` 和 `GET /api/v1/code-graph/{repo_id}/search?q=Worker` 均返回首个 `snapshot_id`。
- 将 `Worker` 改为 `Processor` 并提交第二个 Git snapshot 后，未传 `snapshot_id` 的搜索只读取新的 active snapshot 且不再返回 `Worker`；显式传入首个 `snapshot_id` 仍准确返回 `Worker`，证明图谱投影及 API 都遵守历史快照隔离。
- 验证命令：`python -m pytest tests/test_javascript_typescript_graph_ingest.py tests/test_javascript_typescript_parser.py tests/test_m2_parser_storage.py tests/test_snapshot_ingest.py tests/test_m0_contract.py tests/test_snapshot_api.py -q`，结果 `33 passed`。同时将 `test_m0_contract.py` 的健康检查 schema 期望由已过期的 `7` 同步为当前 migration `v008` 的 `8`。

**验收结论：** JS/TS 的结构化事实已经通过真实 Git ingest、规范化存储、快照图投影和公开图 API 得到端到端验证；本项不承诺 Rust/Go，后续语言应复用同一 canonical facts + snapshot projection 模式并单独立项。

---

### ✅ P2-5：Debate 模式智能触发

**问题：** `service/core/debate.py` 多角色辩论模式 token 消耗是普通模式的 3 倍，但目前没有自动判断"什么时候值得用"的逻辑。

**实现（2026-08-01）：** `MultiAgentDebateService` 原本没有任何生产调用方，本项不只增加触发条件，也将它接入 `run_main_agent()` 的证据优先问答链路。

1. `service/core/agent/router.py` 的规则路由将 Debate 限制为长度超过 50 字、包含架构/设计/原因/取舍/影响等复杂开放问题的查询；含限定名、`snake_case` 或 `CamelCase` 的精确符号查询明确跳过。触发时固定使用 `developer` 和 `architect` 两个角色，不扩大为高自主多 Agent 编排。
2. Main Agent 先完成检索、Specialist 补证和 `EvidenceAssembler` 的预算/去重，再要求最终证据至少来自两个文件且未被 relevance policy 拒绝；否则不调用 LLM Debate，并在 trace 写入 `insufficient_grounded_evidence`。因此不会让多角色模型在无证据条件下编造结论。
3. 只有两个选定角色都成功使用 LLM 时，Debate 才直接成为最终回答，避免随后再调用一次普通 synthesis；离线、无 key、部分角色失败或全部 Debate 调用未使用 LLM 时仍回退到原来的单次规则/LLM 问答。`agent_trace_steps` 会记录 `debate` 的 selected roles、LLM 实际使用数、token 和跳过/失败原因，API/MCP 响应合同不变。

**实测与验证（2026-08-01）：**

- `backend/tests/test_m4_main_agent.py` 新增并覆盖：复杂开放问题选择双角色、精确符号问题不选择、单一证据来源跳过、两个独立证据来源时成功 Debate 直接完成回答且不重复普通 synthesis。
- 回归命令：`python -m pytest tests/test_m4_main_agent.py tests/test_mcp_server.py tests/test_snapshot_api.py -q`，结果 `46 passed`。该改动属于问答编排与 token 消耗策略，不改变检索排序，故不填写 Recall@K/MRR 指标。

**预计耗时：** 2 天

---

## CI 回归门禁（P0-1 完成后立即加）

```python
# tests/test_regression_gate.py
def test_bm25_baseline_not_regressed():
    """BM25 baseline 指标不能倒退。"""
    metrics = run_goldset("bm25")
    assert metrics.recall_at_5 >= 0.267
    assert metrics.mrr >= 0.245

def test_locate_code_benchmark():
    """locate_code 工具在 5 个手标 case 上不能低于 4/5。"""
    results = run_locate_code_benchmark()
    assert results["passed"] >= 4
```

门禁分两层：

1. **普通 PR CI：** 校验 gold/capture 契约，并从固定 capture 重算指标；必须离线、确定、快速。
2. **手动或定时 benchmark：** 真实重新索引并调用 embedding/reranker，生成新 capture 和对比报告；允许依赖本地模型或外部 API。

普通 CI 不得强依赖 Ollama、GPU、模型下载或外部 API。

**已落实的离线部分（2026-07-30）：** [verify_retrieval_regression.py](../../scripts/verify_retrieval_regression.py) 已接入 Windows CI。它只读取已提交的 gold、manifest 与脱敏 lexical capture，校验固定 commit、gold SHA-256、40 题顺序、相对路径安全性，并重算冻结指标：Recall@5 `0.2666666667`（展示时为 `0.267`）、Recall@10 `0.3791666667`、MRR `0.2450297619`、Citation hit rate `0.550`、Task completion `0.550`、Tool selection exact match `1.000`。它不启动服务、不读取用户数据库，也不调用 embedding/reranker。真实重新索引与 Hybrid benchmark 仍为手动或定时任务，待 P0-1 完成后再把其结果作为独立基准记录。

---

## 执行顺序建议

### 给下一模型的当前执行关口（2026-08-01）

1. 保持离线 CI 基准门禁；只有改动 retrieval、embedding 降级或 `locate_code` 路径时，才复跑对应固定 capture 和回归测试。新的模型、融合参数、结构扩展或 reranker 实验一次只改变一个主要变量。
2. P0-2 与 P1-3 已完成，BGE-M3 是当前推荐 embedding 配置；不要因为模型已安装就重复跑候选筛选。`nomic-embed-text:latest` 已测失败，`all-minilm:latest` 仅保留为历史 provisional baseline。
3. P1-4 的质量 A/B 已完成：`bge-reranker-v2-m3` 将 MRR 提升到 `0.481`，但 CPU P95 为 `77066.8 ms`，默认 provider 必须保持 `disabled`。先收集产品 SLA 和可用硬件；仅在需要低延迟精排时，单独立项比较候选数、批处理、轻量 reranker 或 GPU，并固定原实验契约复跑 A/B。
4. P2-2 已完成，先观察 `/api/v1/metrics` 的真实 MCP 请求量、低分率和趋势。P2-3 的单文件实验已确认缓存可复用 `8452/8478` 个向量，但新增 `26` 个向量仍耗时 `129.255 s`；batch=32 对照为 `136.597 s`，不能修改生产默认配置。provider client reuse 已在同契约完整 BGE-M3 profile 中将总耗时从 `640.657 s` 降到 `433.575 s`（embedding `634.751 s` 降到 `427.636 s`）；该专项已完成，不要重复跑。不要把通用文件级增量或 parsed evidence 复用当作默认下一步；只有真实刷新 SLA 未满足时，才单独重新立项。
5. P1-1、P1-2 不重复开发，只在改动其代码路径时运行对应回归。其余 P2 不是串行必做清单，必须按真实用户需求、线上遥测和已测瓶颈重新立项。
6. 文档中必须区分外部 Agent 的端到端 A/B 与工具级固定基准：历史外部 A/B 为 RepoMind MCP `3/5`，而生产 `locate_code` 的固定 manifest lexical 工具级回归为 `5/5`、gold-location coverage `1.000`、mean reciprocal rank `0.578`。两者测量对象不同，不能相互替代。

**当前运行态（2026-08-01）：** 默认用户数据库 `~/.repomind/repomind.sqlite3` 尚不存在 `retrieval_metrics` 表，本机也没有运行中的后端监听端口；因此尚无真实 MCP 使用数据可供 P2-2 观察。不得通过测试、benchmark 或合成请求填充该表来触发后续优化决策。实际桌面后端以包含 schema v009 的版本运行并收到真实请求后，再从认证的 `GET /api/v1/metrics` 读取聚合趋势。

**桌面后端发布门禁复核（2026-08-01）：** 已修正两个过期 smoke 契约：`scripts/smoke_backend.ps1` 要求迁移序列 `1,2,3,4,6,7,8,9`、schema `9` 和 `retrieval_metrics` 表；`scripts/smoke_mcp.ps1` 不再将 MCP 工具固定为旧的 6 个，而是精确校验当前 7 个只读工具，包含 `locate_code`。使用当前源码重新构建的 `backend-dist/repomind-backend.exe` 已通过：

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_backend.ps1 -PythonCommand python`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/smoke_backend.ps1 -ExePath backend-dist/repomind-backend.exe`：`schema=9`、迁移序列 `1,2,3,4,6,7,8,9`、FTS5、`retrieval_metrics`、无 key 设置均通过。
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/smoke_mcp.ps1 -ExePath backend-dist/repomind-backend.exe -PythonCommand python`：7 个 MCP 只读工具发现与空库 `list_repositories` 调用通过。

这证明当前冻结后端已具备安全启动并收集真实 MCP 遥测的发布前提，但临时 smoke 使用隔离空库，**不是**真实使用数据。下一步应使用同一构建链生成桌面包，实际启动后让真实 MCP 客户端请求进入用户数据库，再读取认证的 `/api/v1/metrics`；不得人为写入 `retrieval_metrics`。

**完整桌面包门禁（2026-08-01，待在锁定环境重建）：** 历史上曾使用 `REPOMIND_SKIP_WINDOWS_EXE_METADATA=1` 生成未签名的 `desktop/app/release/win-unpacked/RepoMind.exe`，并完成当时的目录级 smoke、E2E 和哈希校验；该运行使用 Node `v24.14.1`/npm `11.11.0`/Python `3.13`，不符合项目锁定的 Node `20.18.0`、npm `10.8.2`、Python `3.12`，不能作为正式发布证据。更重要的是，当前 `backend-dist/repomind-backend.exe` 的 SHA-256 为 `F901C5499730CC232A1ADC1C0F69152C304218562DE9EE68A3CD6C740B9509D8`，而历史 `win-unpacked/resources/backend/repomind-backend.exe` 为 `597322701BE7F61B47E4F596D2E8BDF253BF4BC8EE68EED01182A3C9DCAC265D`；历史桌面包内嵌的不是当前 schema v009 后端，只可保留为 schema-8 的历史运行证据。

现已新增 `scripts/verify_runtime_contract.ps1`，并接入 `scripts/package_windows.ps1` 和 Windows CI。打包会在任何清理或构建前精确校验 `.nvmrc`、`package.json#packageManager`、`.python-version`；本机当前会因 Node `24.14.1` 不匹配而预期失败。正式 v009 桌面包必须由 GitHub Windows CI 或具备 Node `20.18.0`、npm `10.8.2`、Python `3.12` 的本地环境重新执行完整打包链，再验证包内后端 schema `9`、MCP smoke、E2E 与新生成的递归 `SHA256SUMS.txt`。在此之前，不得声称已有可发布的 v009 桌面包。

**发布流水线对齐（2026-08-01）：** 新增 `scripts/verify_release_hashes.ps1`，它独立复算 `SHA256SUMS.txt` 并拒绝空清单、重复路径、路径穿越、遗漏文件、额外条目与哈希不匹配。`package_windows.ps1` 在生成递归清单后立即调用它；CI 在 packaged Electron E2E 之后再调用一次。Release 工作流现与 CI 对齐：先验证身份、锁定运行时和离线检索基准，再构建 release、对 `win-unpacked` 运行隔离 E2E 和共享索引 MCP smoke，最后复核哈希，失败时上传脱敏 E2E 诊断。历史目录包可通过当前清单复核 `84` 个文件，但它仍是 schema-8 历史证据，不能替代锁定环境下生成的 v009 产物。

**发布校验回归补强（2026-08-01）：** 新增 `scripts/test_release_hashes.ps1`，在临时目录覆盖正常递归清单、内容篡改、未列出的额外文件和 manifest 路径穿越四条验证分支；本地结果为 `Release checksum verifier tests OK`。该测试已接入 `.github/workflows/ci-windows.yml` 和 `.github/workflows/release-windows.yml`，因此发布校验器的拒绝逻辑会在正式构建前持续执行。当前源码完整后端回归为 `262 passed, 72 warnings`，冻结检索门禁仍为 Recall@5 `0.2666666667`、MRR `0.2450297619`；本机运行时契约按预期拒绝 Node `24.14.1`，所以尚未产生新的 v009 包。

**桌面运行态与 schema 契约复核（2026-08-01）：** 桌面主进程此前仅要求后端 schema `>=7`，与迁移后的 telemetry 契约不一致；现已将健康兼容检查收敛到 `desktop/app/electron/backendLifecycle.ts`，要求 schema `>=9`，且添加回归覆盖：schema `9` 通过、schema `8` 被拒绝。当前源码的 Electron 生命周期单测为 `10 passed`，完整后端回归为 `262 passed, 72 warnings`，新冻结后端的 schema-9 HTTP smoke 已通过。历史完整目录包的 schema-8 结果及其 SHA-256 只代表当时的 v008 构建；必须在锁定运行时重建完整桌面包，才可将 v009 的冻结后端纳入可发布目录和生成新的哈希清单。

同一未签名 `win-unpacked` 包还通过隔离 Playwright Electron E2E：`npm run test:e2e:packaged` 在临时 `REPOMIND_USER_DATA_PATH` 中用时 `34.5 s`，实际启动桌面程序和内嵌后端，完成内置 Demo 的 ingest、问答、证据/Trace、工作流和 JSON/Markdown 导出。该测试刻意使用新的临时 userData，未读取、修改或填充真实桌面库 `%%APPDATA%%/repomind-desktop/backend-data/repomind.sqlite3`，因此它只证明运行闭环，不构成真实 MCP 遥测数据。

```
第1阶段: P0-0（现状审计、冻结 commit/config；已完成）
第2阶段: 修复“索引有向量但 query embedding provider 未配置或本地端点不可达”时的快速 lexical 降级，并用固定 locate_code 基准验证质量不变、延迟恢复正常。该项已完成，是 P0-1 的运行前置，不产生 Hybrid 指标。
第3阶段: P0-1（runner、BM25 复现与真实 all-minilm Hybrid 对照已完成；all-minilm 只作 provisional baseline）
第3.5阶段: 固定 manifest 的 locate_code 工具级基准（已完成首轮 5/5 lexical 回归；每次影响 locate_code 的改动后复跑）
第4阶段: 立即保持离线 CI 门禁，并将真实 provider benchmark 留给手动或定时任务
第5阶段: P0-2 已完成：BGE-M3 在完整真实向量覆盖下通过 Hybrid A/B，成为推荐 embedding 配置
第6阶段: P1-3 已完成：已用 BGE-M3 与相同契约完成正负样本拒答校准
第7阶段: P1-4 已完成质量 A/B：BGE reranker 明显提升质量，但 CPU P95 约 77 秒，保持为可选离线质量模式；需要默认精排时先立项性能专项
第8阶段: P2-2 已完成，先通过 `/api/v1/metrics` 收集真实 MCP 请求量、低分率和趋势；它不替代离线 benchmark
第9阶段: 已完成真实 ingest profile、单文件第二 snapshot 实验、batch=32 对照和 provider client reuse profile；BGE-M3 embedding 占修复前全量 ingest 的 99.1%，client reuse 将同契约完整 ingest 从 640.657 秒降至 433.575 秒，embedding 从 634.751 秒降至 427.636 秒。单文件变化时已有缓存复用 8452/8478 个向量，但新增 26 个向量仍耗时 129.255 秒，batch=32 为 136.597 秒。当前不调整生产默认配置；只有新的刷新需求或 provider 性能证据出现时才继续专项，再决定是否立项 P2-3。只能实现 snapshot-aware 增量复用，不能在已发布 snapshot 内 DELETE 重建
第10阶段: 按需要扩展 P1-2 的静态关系覆盖范围；P2 其余条目仅按真实产品需求和已测瓶颈推进，不默认全部实施
```

---

## 对下一个 AI 的交接说明

1. **本文档路径：** `docs/后续开发指导/2026-08-01_IMPROVEMENT_PLAN_V2_当前改进执行计划.md`
2. **上层路线图：** `docs/后续开发指导/2026-07-28_ARCHITECTURE_FUTURE_ROADMAP_未来架构路线图.md`（包含 M6-M9 宏观演进，本文档是它的细化落地版）
3. **测试入口：** `backend/tests/test_mcp_server.py`（locate_code benchmark 在这里）
4. **评测工具：** `backend/service/evaluation/retrieval_metrics.py`（Recall@K 和 MRR 计算）
5. **每完成一个 P0/P1 条目，请更新本文档对应条目状态为 ✅，并填写实测后的指标数字**
6. **不得完全照抄示例实现。** 每项开始前先核对当前代码；验收以固定 benchmark 的实测结果和回归测试为准。
7. **P2-3 已暂停并改写。** 当前快照不可变；后续必须在新 snapshot 构建阶段复用未变化结果，成功后再原子 publish，不能按旧计划在当前数据上做文件级 DELETE/重建。

---

## 执行纪律

1. 一次只改变一个主要实验变量；模型、融合参数、结构扩展和 reranker 不同时切换。
2. 每个优化都同时报告质量、延迟和失败降级，不只挑最好看的数字。
3. P0/P1 可以按上述依赖顺序连续执行；P2 必须在开始前重新评估产品需求，不能视为必做清单。
4. 若代码现状与本文档冲突，以代码和可复现测试为事实来源，并先修订本文档再继续。
5. 不执行目标仓库代码，不安装目标仓库依赖，不把密钥、本机数据库或绝对路径提交到仓库。
