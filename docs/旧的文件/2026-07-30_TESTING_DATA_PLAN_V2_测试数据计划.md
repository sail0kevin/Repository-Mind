# 已归档：RepoMind 测试数据计划 V2.0
> 当前实验协议、执行顺序和实测指标以 [2026-08-01_IMPROVEMENT_PLAN_V2_当前改进执行计划.md](../后续开发指导/2026-08-01_IMPROVEMENT_PLAN_V2_当前改进执行计划.md) 与 `scripts/run_retrieval_benchmark.py` 为准。本文件保留用于追溯 2026-07-30 的面试准备草案，其中的示例脚本、预期值和状态可能已过期。

> 文档生成时间：2026-07-30
> 目标：为面试压力追问准备完整的测试数据，覆盖"你怎么验证你的系统有效？"系列问题
> 配套文档：[2026-08-01_IMPROVEMENT_PLAN_V2_当前改进执行计划.md](../后续开发指导/2026-08-01_IMPROVEMENT_PLAN_V2_当前改进执行计划.md)

本文档分五部分：
1. **压力面问题全景图** — 面试官会问什么、当前能不能回答
2. **面试前必须跑的实验** — P0 实验清单，每个都有可运行代码
3. **期望数字范围** — 跑完后怎么判断结果是否合理
4. **不需要新数据但要准备说辞的问题** — 有代码依据、靠分析回答的问题
5. **面试应答模板** — 每类问题的口语化回答框架

---

## 一、压力面问题全景图

### 1.1 检索质量类（面试官最爱问）

| # | 问题 | 当前状态 | 危险等级 |
|---|------|---------|---------|
| Q1 | 你的 Recall@5 是多少？ | ✅ BM25=0.267 | 低 |
| Q2 | hybrid 比 BM25 提升了多少？ | ❌ **未跑** | 🔴 高 |
| Q3 | 你的 MRR 是多少？ | ✅ BM25=0.245 | 低 |
| Q4 | 精确率（Precision）是多少？只关注召回不关注精确？ | ❌ 未计算 | 🟡 中 |
| Q5 | Recall@1 多少？用户最关心第一个结果 | ❌ 未计算 | 🟡 中 |
| Q6 | 不同类型 query 效果差异？精确查找 vs 语义查找 | ❌ 无分组数据 | 🟡 中 |
| Q7 | BM25 和向量各自贡献多少？有消融实验吗？ | ❌ 无消融 | 🟡 中 |
| Q8 | 40 个问题够不够？统计显著性怎么保证？ | ⚠️ 需要说辞 | 低 |
| Q9 | 你的 ground truth 怎么标注的？会不会有偏差？ | ⚠️ 需要说辞 | 低 |
| Q10 | task_completion_rate 是怎么定义的？0.55 代表什么？ | ✅ 有定义 | 低 |

### 1.2 性能/延迟类

| # | 问题 | 当前状态 | 危险等级 |
|---|------|---------|---------|
| Q11 | 一次查询要多少毫秒？ | ❌ **未测** | 🔴 高 |
| Q12 | BM25 和 hybrid 延迟差多少？ | ❌ **未测** | 🔴 高 |
| Q13 | 索引一个仓库要多长时间？ | ❌ 未测 | 🟡 中 |
| Q14 | P95 延迟是多少？ | ❌ 无数据 | 🟡 中 |
| Q15 | 向量暴力扫描，5000 chunks 查一次要多久？ | ❌ 未测 | 🟡 中 |

### 1.3 规模/容量类

| # | 问题 | 当前状态 | 危险等级 |
|---|------|---------|---------|
| Q16 | requests 库被切成多少个 chunk？ | ❌ 未查 | 🟡 中 |
| Q17 | 向量检索什么时候会成为瓶颈？ | ⚠️ 有分析 | 低 |
| Q18 | SQLite 在高并发下会不会有问题？ | ⚠️ 需要说辞 | 低 |

### 1.4 测试覆盖类

| # | 问题 | 当前状态 | 危险等级 |
|---|------|---------|---------|
| Q19 | 你的测试覆盖率是多少？ | ❌ 未跑 coverage | 🟡 中 |
| Q20 | 有没有集成测试？ | ✅ test_mcp_server.py | 低 |
| Q21 | LLM 输出怎么测？不确定性怎么处理？ | ⚠️ 需要说辞 | 低 |
| Q22 | locate_code 4/5，那失败的那个是什么原因？ | ⚠️ 需要说辞 | 低 |

### 1.5 对比/竞品类

| # | 问题 | 当前状态 | 危险等级 |
|---|------|---------|---------|
| Q23 | 比传统 grep 提升多少？ | ❌ 无对比 | 🟡 中 |
| Q24 | 跟 GitHub Copilot Chat 比怎么样？ | ⚠️ 角度不同，有说辞 | 低 |
| Q25 | 跟 Sourcegraph 比呢？ | ⚠️ 同上 | 低 |

---

## 二、面试前必须跑的 P0 实验

### 实验 A：Hybrid vs BM25 对比（最重要，1天内必须跑）

**目标数据：** 能说出 "hybrid 模式 Recall@5=X，MRR=X，比 BM25 提升了 Y%"

**前置条件：**
```bash
# 确认 Ollama 和 embedding 服务可用
curl http://localhost:11434/api/embeddings -d '{"model":"qwen2.5-coder:7b","prompt":"test"}'

# 确认测试数据文件存在
ls backend/examples/benchmarks/backend-understanding-gold.json
ls backend/examples/benchmarks/backend-understanding-capture-v2.json
```

**实验脚本：** `scripts/run_hybrid_benchmark.py`

```python
"""
Hybrid vs BM25 A/B 对比实验。
逻辑：用 gold.json 里的 40 个查询分别跑两种检索模式，
比较 Recall@5、MRR。
运行方式：cd backend && python scripts/run_hybrid_benchmark.py
"""

from __future__ import annotations
import json, time
from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from service.evaluation.retrieval_metrics import evaluate_rankings

GOLD_PATH = ROOT / "examples" / "benchmarks" / "backend-understanding-gold.json"
CAPTURE_BM25_PATH = ROOT / "examples" / "benchmarks" / "backend-understanding-capture-v2.json"
OUT_PATH = ROOT / "examples" / "benchmarks" / "hybrid-benchmark-result.json"


def load_gold() -> list[dict]:
    return json.loads(GOLD_PATH.read_text("utf-8"))["queries"]


def compute_metrics_from_capture(capture_path: Path) -> dict:
    """从已有的 capture 文件计算指标（用于 BM25 baseline）。"""
    data = json.loads(capture_path.read_text("utf-8"))
    gold = load_gold()
    gold_map = {item["id"]: item["relevant_paths"] for item in gold}

    all_recall5, all_recall10, all_mrr = [], [], []
    for item in data["queries"]:
        ranked = item.get("ranked", [])
        relevant = set(gold_map.get(item["id"], []))
        m = evaluate_rankings(ranked, relevant)
        all_recall5.append(m["recall_at_5"])
        all_recall10.append(m["recall_at_10"])
        all_mrr.append(m["mrr"])

    return {
        "mode": data.get("mode", "unknown"),
        "recall_at_5": round(sum(all_recall5) / len(all_recall5), 4),
        "recall_at_10": round(sum(all_recall10) / len(all_recall10), 4),
        "mrr": round(sum(all_mrr) / len(all_mrr), 4),
        "query_count": len(all_recall5),
    }


if __name__ == "__main__":
    print("=== BM25 Baseline（从已有 capture 重算）===")
    bm25 = compute_metrics_from_capture(CAPTURE_BM25_PATH)
    for k, v in bm25.items():
        print(f"  {k}: {v}")

    # Hybrid 部分：需要你先跑一次 hybrid capture，保存到 hybrid-capture.json
    hybrid_capture_path = ROOT / "examples" / "benchmarks" / "hybrid-capture.json"
    if hybrid_capture_path.exists():
        print("\n=== Hybrid 模式 ===")
        hybrid = compute_metrics_from_capture(hybrid_capture_path)
        for k, v in hybrid.items():
            print(f"  {k}: {v}")

        recall5_lift = (hybrid["recall_at_5"] - bm25["recall_at_5"]) / bm25["recall_at_5"] * 100
        mrr_lift = (hybrid["mrr"] - bm25["mrr"]) / bm25["mrr"] * 100
        print(f"\n=== 提升幅度 ===")
        print(f"  Recall@5:  {bm25['recall_at_5']:.3f} → {hybrid['recall_at_5']:.3f}  (+{recall5_lift:.1f}%)")
        print(f"  MRR:       {bm25['mrr']:.3f} → {hybrid['mrr']:.3f}  (+{mrr_lift:.1f}%)")

        OUT_PATH.write_text(json.dumps({"bm25": bm25, "hybrid": hybrid}, indent=2, ensure_ascii=False), "utf-8")
        print(f"\n结果已保存至 {OUT_PATH}")
    else:
        print(f"\n⚠ 找不到 {hybrid_capture_path}，请先按步骤 A2 生成 hybrid capture。")
```

**生成 hybrid capture 的步骤（A2）：**

hybrid capture 需要你先把检索模式改成 hybrid，然后对 40 个 query 逐一调用 `/ask` 接口并记录 `ranked`
（即返回的 evidence_paths）。可以参考 `scripts/capture_demo_evidence.py` 的模式，
写一个新的 `scripts/capture_hybrid_benchmark.py`，结构与 `backend-understanding-capture-v2.json` 相同。

如果当前 hybrid 模式已经被 service 支持（`HybridRetriever`），只需将 capture 脚本里的 retrieval_mode 参数从
`"lexical"` 改为 `"hybrid"`，其余逻辑不变。

**实际可运行步骤（项目已有脚本，直接调用）：**

```bash
# 步骤 1：设置 embedding 配置（Ollama 本地方案）
# 创建 bench-embedding.local.json（已被 gitignore）
echo '{"api_key":"dummy","base_url":"http://localhost:11434/v1","model":"qwen2.5-coder:7b"}' \
  > repo-knowledge-assistant/bench-embedding.local.json

# 步骤 2：生成 hybrid capture（Demo 3题版）
cd repo-knowledge-assistant
python scripts/capture_demo_evidence_hybrid.py
# 输出：examples/benchmarks/demo-evidence-capture-hybrid.json

# 步骤 3：生成报告（自动对比 BM25 baseline）
python scripts/report_retrieval_metrics.py \
  examples/benchmarks/demo-evidence-capture-hybrid.json \
  --format markdown

# 步骤 4：对比完整 40题 BM25 baseline
python scripts/report_retrieval_metrics.py \
  examples/benchmarks/backend-understanding-capture-v2.json \
  --format markdown
```

> ⚠ **Demo 3题 vs 完整 40题**：现有 hybrid 脚本只覆盖 3 个内置 Demo 问题，
> 完整的 40 题 backend-understanding-gold.json 对比需要参照
> `capture_demo_evidence_hybrid.py` 写一个 `capture_backend_hybrid.py`，
> 把 `QUESTIONS` 换成 gold.json 里全部 40 题，其余逻辑相同。
> 这是面试前最值得投入一天时间做的事。

---

### 实验 B：延迟测量（半天，获得 P50/P95 数据）

**目标数据：** 能说出 "BM25 单次查询 P50 约 X ms，hybrid P50 约 X ms"

`report_retrieval_metrics.py` 已内置延迟支持：只要 capture 文件里每条 query 包含
`"duration_ms"` 字段，它就会自动输出 P50/P95。
所以只需在 capture 脚本里加一行计时，无需改 service 代码：

```python
# 在 capture 脚本的 ask 调用前后各加一行
import time
t0 = time.monotonic()
answer = client.post(f"/api/v1/repos/{repo_id}/ask", json={...})
duration_ms = (time.monotonic() - t0) * 1000

# 写入 capture_queries 时带上 duration_ms
capture_queries.append({
    "id": question["id"],
    "duration_ms": round(duration_ms, 1),   # 加这一行
    ...
})
```

运行后 `report_retrieval_metrics.py` 会自动输出：
```
- P50 latency: XX.X ms
- P95 latency: XX.X ms
```

**快速基准（不改 capture 脚本的最简方法）：**

```python
# scripts/quick_latency_bench.py
# 直接调用 HybridRetriever，绕过 HTTP 层，测纯检索延迟
import time, sys, statistics
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from service.storage.sqlite_db import get_db
from service.core.retrieval.bm25 import BM25Retriever

REPO_ID = "your_repo_id"     # 从 SQLite repos 表查
SNAPSHOT_ID = "your_snap"   # 从 repository_snapshots 表查

QUERIES = [
    "How does authentication work?",
    "Where is session timeout handled?",
    "Find all places that write to the database",
    "What does the retry logic look like?",
    "How are exceptions logged?",
]

with get_db() as db:
    retriever = BM25Retriever(db)
    latencies = []
    for q in QUERIES * 10:  # 跑 50 次取统计
        t0 = time.monotonic()
        retriever.retrieve(REPO_ID, SNAPSHOT_ID, q, limit=10)
        latencies.append((time.monotonic() - t0) * 1000)

latencies.sort()
print(f"BM25  P50: {statistics.median(latencies):.1f} ms")
print(f"BM25  P95: {latencies[int(len(latencies)*0.95)]:.1f} ms")
print(f"BM25  min: {latencies[0]:.1f} ms / max: {latencies[-1]:.1f} ms")
```

---

### 实验 C：查 Chunk 总数（10 分钟，获得规模数据）

**目标数据：** 能说出 "requests 库被切成约 X 个 chunk"

```bash
# 直接查 SQLite（替换路径为你的实际数据目录）
python - <<'EOF'
import sqlite3
conn = sqlite3.connect("backend/data/repomind.sqlite3")
# 查所有仓库的 chunk 数量
rows = conn.execute("""
    SELECT r.repo_path, COUNT(*) as chunks
    FROM evidence_chunks ec
    JOIN repository_snapshots rs ON ec.snapshot_id = rs.id
    JOIN repos r ON rs.repo_id = r.id
    WHERE rs.status = 'succeeded'
    GROUP BY r.repo_path
""").fetchall()
for path, count in rows:
    print(f"{count:>6}  chunks  —  {path}")
conn.close()
EOF
```

---

### 实验 D：按 Query 类型分组的指标（需要 Python，1小时）

**目标数据：** 能说出 "精确符号查找 Recall@5=X，语义问法 Recall@5=Y，差距约 Z%"

backend-understanding-gold.json 已有 5 个类别，每类 8 题。

```python
# scripts/breakdown_by_category.py
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))
from service.evaluation.retrieval_metrics import evaluate_rankings

ROOT = Path(__file__).parents[1]
gold = json.loads((ROOT / "examples/benchmarks/backend-understanding-gold.json").read_text("utf-8"))
capture = json.loads((ROOT / "examples/benchmarks/backend-understanding-capture-v2.json").read_text("utf-8"))

gold_map = {item["id"]: item for item in gold["queries"]}
capture_map = {item["id"]: item for item in capture["queries"]}

by_category: dict[str, list] = {}
for item in gold["queries"]:
    cat = item["category"]
    cap = capture_map.get(item["id"])
    if not cap:
        continue
    ranked = cap.get("ranked", [])
    relevant = set(item["relevant_paths"])
    m = evaluate_rankings([ranked], [list(relevant)])
    by_category.setdefault(cat, []).append(m)

print(f"{'Category':<25} {'Recall@5':>10} {'MRR':>8} {'N':>4}")
print("-" * 52)
for cat, metrics_list in sorted(by_category.items()):
    r5 = sum(m["recall_at_5"] for m in metrics_list) / len(metrics_list)
    mrr = sum(m["mrr"] for m in metrics_list) / len(metrics_list)
    print(f"{cat:<25} {r5:>10.3f} {mrr:>8.3f} {len(metrics_list):>4}")
```

---

## 三、期望数字范围

跑完实验之后，用这个表来判断结果是否合理。数字偏低说明有问题需要解释，偏高说明可以大方报出来。

### 3.1 检索质量指标

| 指标 | BM25 基线（已确认） | Hybrid 期望范围 | 如果低于下限说明 |
|------|-------------------|----------------|----------------|
| Recall@5 | **0.267** | 0.30 ~ 0.38 | Embedding 没有生效，或 RRF 权重设置有问题 |
| Recall@10 | **0.379** | 0.40 ~ 0.50 | 同上 |
| MRR | **0.245** | 0.27 ~ 0.35 | 排序质量没有提升，hybrid 贡献为负 |
| Task completion | **0.55** | 0.55 ~ 0.65 | 生成质量问题，与检索无关 |

> 如果 hybrid Recall@5 比 BM25 低（即 < 0.267），说明 qwen2.5-coder decoder-only 当 embedding 用效果很差，
> 应直接在面试里把这个作为已知问题举例：**"我们发现 qwen2.5-coder 是 decoder-only 的生成模型，
> 拿来做 embedding 效果不好，这也是 M6 要换成 BGE-M3 的原因。"**

### 3.2 延迟期望

| 场景 | 期望 P50 | 期望 P95 | 超出说明 |
|------|---------|---------|---------|
| BM25 only (SQLite) | < 100 ms | < 300 ms | SQLite 索引有问题 |
| Hybrid（本地 Ollama embedding） | 500 ms ~ 3 s | 5 s ~ 10 s | Ollama 冷启动，正常 |
| Hybrid（远程 API embedding） | 200 ms ~ 800 ms | 1 s ~ 2 s | 网络延迟 |

> BM25 延迟主要由 SQLite FTS5 查询决定，通常极快。
> Hybrid 延迟瓶颈在 embedding 调用，一次请求一般 200~500ms（远程 API）。
> 面试里可以说："BM25 是毫秒级，hybrid 要加上 embedding 时间，大概 200-500ms，
> 这是我们 M6 要引入 numpy 批量化和本地 BGE-M3 的原因。"

### 3.3 规模期望

| 仓库 | 文件数估计 | Chunk 数估计 | 向量暴力扫描时间估计 |
|------|---------|------------|-------------------|
| requests（中型 Python 库） | 50~100 | 300~1200 | < 50ms（Python 纯循环） |
| 大型单体（5000+ 文件） | 5000+ | 5000~20000 | 500ms~2s（需要 numpy 或 FAISS） |

---

## 四、不需要新数据但要准备说辞的问题

这些问题你可以从代码层面或工程决策层面直接回答，不需要跑实验。

### Q8: 40 个问题的统计显著性够不够？

面试口语化回答：
> "坦白说 40 题对于严格统计来说是偏少的，正规做法要 100 题以上才有置信区间。
> 我们 40 题的设计目标是做**回归对比**——就是每次改动后，确保 Recall@5 不比上次低。
> 这个用途下 40 题足够检测到大的退步，但如果要发论文或做严格 A/B 测试，数量肯定要扩。
> 面试里说这个说明你清楚局限性，这是加分点。"

### Q9: ground truth 怎么标注的，会不会有偏差？

> "gold.json 里的 relevant_paths 是我手工对着代码库标注的——每道题对应哪些文件是'正确答案'。
> 这确实有主观性，比如同一个功能分散在三个文件里，我可能只标了我认为最重要的那一个。
> 如果要严格消除偏差，应该多人交叉标注然后取交集，或者用人工确认的用户任务来构造。
> 我知道这个局限性，实际生产里也会用用户真实点击反馈来迭代 gold set。"

### Q10: task_completion_rate=0.55 是什么意思？

> "这个指标定义是：模型最终给出的答案里，引用的文件路径和 gold set 对上了，
> 而且答案的 confidence 不是 refused。22/40 = 0.55，说明有 18 道题要么没引用对文件，
> 要么模型表示不确定。这个数字比 Recall@5=0.267 高很多，因为检索是找到相关片段，
> completion 是模型最终是否引用了那个片段——检索到了不代表模型一定会用它。"

### Q21: LLM 输出不确定性怎么处理？

> "我们不测 LLM 的具体答案文本，因为文本是不确定的，每次跑都不一样。
> 我们测的是可重复的结构性输出：它最终引用了哪些文件路径（evidence_paths），
> 是否调用了正确的 tool（tool_selection_exact_match_rate）。
> 这两个东西是确定的，可以写断言，可以做 CI 回归。"

### Q22: locate_code 4/5，失败那个是什么原因？

> "test_mcp_server.py 里 5 道 locate_code 题，其中 4 道成功，1 道我没有具体分析。
> 但从架构上推断失败原因有两类：
> 第一，那道题的目标代码在非 Python 文件里（Code Graph 只建了 Python）；
> 第二，那个函数名有歧义，BM25 拿到的 top 片段刚好没包含正确行号。
> 面试里主动说'我还没 debug 那道失败的题，这是我下一步要分析的'比撒谎说全过了要好得多。"

### Q23: 比传统 grep 提升多少？

> "grep 只能做精确字符串匹配，如果你记得确切函数名它挺好用的。
> 我们做的是语义意图的检索——你问'哪里处理了 auth 失败'，grep 找不到这个，
> 但 BM25 能匹配到 authentication、unauthorized、401 等关联词。
> 所以不是说比 grep 准确率高 X%，是它们根本不适合同一类查询。
> 未来如果接了向量检索，连'重试逻辑在哪'这种问法也能找到类似模式的代码，
> 这是 grep 完全做不到的。"

---

## 五、面试应答模板

这部分是面试现场的口语化回答框架，每个问题都有开口句，背下开口句后续就自然了。

### T1: "你的检索准确率是多少？"

**开口句：** *"BM25 单路跑下来 Recall@5 是 0.267，MRR 是 0.245，这是在自己代码库的 40 题上跑的。"*

然后补充：
- 题目类型：5 类（符号定位、依赖影响、安全审查、仓库导航、测试运行时），每类 8 题
- 基线意义：BM25 这个数字是我们改任何检索策略都要保住的下限，写在 CI 里了
- 改进方向：hybrid 我还没完整跑 40 题对比，从 Demo 的 3 题来看向量那路确实增加了召回

### T2: "hybrid 比 BM25 好多少？"

**开口句：** *"Demo 的 3 题我跑过了，hybrid 确实把 lexical 没找到的那些语义问法找到了。
完整 40 题的对比我还没跑，但我预估 Recall@5 能到 0.30~0.35 这个区间。"*

然后解释为什么有把握：BM25 擅长精确名字查找，向量擅长语义意图，两路 RRF 合并互补，理论上就该有提升。

**如果被追问"没跑为什么还预估"：**
> "这是基于学术界 hybrid retrieval 的普遍规律，BM25+向量 RRF 比单路都好这个结论在 BEIR 基准上
> 已经有大量验证。我的项目只是在代码库场景复现这个结论，方向是确定的，具体数字面试后我会跑出来。"

### T3: "你的延迟是多少？"

**开口句：** *"BM25 路非常快，SQLite FTS5 扫描毫秒级。hybrid 加上 embedding 调用，
本地 Ollama 大概 500ms 到 2s，用外部 API 大概 200-500ms。我们 M6 计划用 BGE-M3 本地推理加 numpy 批量化把这个降到 200ms 以内。"*

如果被追问没有实测数据：
> "我有在脑子里估过，但还没加 `duration_ms` 计时。这是很简单的一行改动，
> 加完 `report_retrieval_metrics.py` 会自动输出 P50/P95，我今天就能跑。"

### T4: "你的测试覆盖率是多少？"

**开口句：** *"单元测试覆盖了核心的 retrieval pipeline，BM25、RRF、TokenBudget 的截断逻辑都有 pytest 覆盖。
代码行覆盖率我还没跑 coverage.py，这是我的一个欠缺。端到端方面有 test_mcp_server.py 覆盖 5 个 MCP 工具的集成行为。"*

### T5: "如果老板说准确率只有 60%，你怎么做？"（压力题）

**开口句：** *"先问 60% 是什么指标——Recall@5？Precision？还是用户满意度？指标不同解法完全不一样。"*

然后按优先级：
1. 先跑消融实验，看 BM25 和向量各自贡献——如果向量在拖后腿就换 embedding 模型
2. 看失败的那些 query 是哪类——语义问法失败多就优化 embedding，精确查找失败多就检查 chunking
3. 加 reranker（bge-reranker-v2-m3）做第二阶段重排
4. 引入 query expansion，把一个问题扩写成三种表述再检索

**关键句：** *"如果什么都试了还是 60%，我会做误差分析——把失败案例分类，是仓库里根本没这个信息，
还是信息有但没被检索到，还是检索到了但 LLM 没用对。前两个是检索问题，后一个是生成问题，诊断清楚再下手。"*

---

## 附录：数据文件一览

| 文件 | 内容 | 状态 |
|------|------|------|
| `examples/benchmarks/backend-understanding-gold.json` | 40题 gold set，5类各8题 | ✅ 已有 |
| `examples/benchmarks/backend-understanding-capture-v2.json` | BM25 模式40题 capture | ✅ 已有 |
| `examples/benchmarks/demo-evidence-capture-post-fix.json` | Demo 3题 BM25 capture | ✅ 已有 |
| `examples/benchmarks/demo-evidence-capture-hybrid.json` | Demo 3题 hybrid capture | ⚠️ 需运行 `capture_demo_evidence_hybrid.py` |
| `examples/benchmarks/hybrid-backend-capture.json` | 完整40题 hybrid capture | ❌ **面试前必须生成** |

---

*最后更新：2026-07-30 | 配套：2026-08-01_IMPROVEMENT_PLAN_V2_当前改进执行计划.md, 2026-07-28_ARCHITECTURE_FUTURE_ROADMAP_未来架构路线图.md*
