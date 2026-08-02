# MCP Token 节省执行说明

最后需要回答的产品问题是：在可复现且质量不退化的真实外部 Coding
Agent 工作流中，RepoMind MCP 实际改变了多少模型 Token 消耗。

这不是 Retrieval Recall/MRR 问题，也不能从 MCP 返回字符数、工具调用数或
价格表反推。唯一可作为主结论的数字，是外部 Agent 在完成一轮任务后报告的
`turn.completed.usage` Token 字段。

## 当前状态

- 历史内部小样本 `codex-token-ab-v1` 的 3 个任务均完成，但 MCP 输入 Token
  为 `148,193`，Baseline 为 `130,936`，即 **增加 `13.18%`**。这不是节省，
  也不能因其中一个诊断任务为负变化就挑选性宣传。
- `scripts/run_codex_location_ab.ps1` 现会从原始 Codex JSONL 的
  `turn.completed` 提取 `input_tokens`/`output_tokens`，并在成功任务结果中写入
  `usage_provenance=codex_exec_json.turn.completed` 与 `raw_trace_sha256`。
- `scripts/report_mcp_token_savings.py` 已实现输入、输出和总 Token 的成对汇总；
  它只统计两组均按 rubric 通过的任务，单独报告两组通过率，并拒绝缺用量来源、
  trace 哈希或条件不一致的结果。

因此，报告能力已经可用；下方先记录最新的 V4 实测，再保留 V3 合并运行和首轮真实外部运行作为历史批次。两者都不能替代成功率达到或超过 baseline 后的正式结论。

## V4 最新外部三仓库 A/B（2026-08-02）

报告为 `e2e-artifacts/external-token-study-20260801/external-token-ab-v4-repeat-2.report.md`，实际聚合使用的有效 batch 清单为 `external-token-ab-v4-repeat-2-batch2.json`。在 Click、Typer、Requests 三个固定公开仓库、相同 target commit、Codex CLI `0.145.0`、`gpt-5.6-terra`、`low` reasoning、240 秒 timeout、`bypass_sandbox=true` 与 `coding-agent` MCP profile 下，完成了两个独立 repeat，共 60 个 cohort-task。Click 使用 v4 语义答案组，Typer 与 Requests 保持原冻结任务集。

| 指标 | Baseline | MCP | 变化 |
| --- | ---: | ---: | ---: |
| 完整任务通过率（60 个 cohort-task） | 51/60（85.00%） | 45/60（75.00%） | -10.00 个百分点 |
| 可比较的 both-passed 任务 | \- | 43/60 | \- |
| Input Token（仅 both-passed） | 1,960,457 | 939,610 | -1,020,847（-52.07%） |
| Output Token（仅 both-passed） | 33,682 | 10,600 | -23,082（-68.53%） |
| Total Token（仅 both-passed） | 1,994,139 | 950,210 | -1,043,929（-52.35%） |
| Source characters（仅上下文体积 proxy） | 282,392 | 55,133 | -227,259（-80.48%） |

配对结果为双方均通过 `43`、仅 baseline 通过 `8`、仅 MCP 通过 `2`、双方失败 `7`。失败类别为 `incomplete_before_mcp_call=14`、`incomplete_after_mcp_before_final_answer=4`、`rubric_failed=4`、`timeout_before_mcp_call=1`、`timeout_after_mcp_before_final_answer=1`。报告器的正式状态为 `not_accepted`，唯一失败门禁为 `treatment_pass_rate`（MCP `75.00%` < baseline `85.00%`）。因此 `-52.35%` 只表示双方均成功任务中的诊断性 Token 观察，不能作为产品或销售结论，P1-5 保持 `🚧`。

V4 的主要价值是把“上下文体积明显减少”与“整体任务质量仍未达标”同时测出来：在双方成功子集上总 Token 降低约一半，但 MCP 组仍有调用前后 incomplete、timeout 和 rubric 失败。下一步应先处理这些失败类别，再以相同样本、模型、profile 和通过率门禁复测。

## V3 合并外部三仓库 A/B（2026-08-02）

合并报告为 `e2e-artifacts/external-token-study-20260801/external-token-ab-v3-run-1-repeat-2.report.md`。在相同的 Click、Typer、Requests 冻结任务、target commit、Codex CLI `0.145.0`、`gpt-5.6-terra`、`low` reasoning、240 秒 timeout、`bypass_sandbox=true` 与 `coding-agent` MCP profile 下，完成了两个独立 repeat，共 60 个 cohort-task。

| 指标 | Baseline | MCP | 变化 |
| --- | ---: | ---: | ---: |
| 完整任务通过率（60 个 cohort-task） | 53/60（88.33%） | 50/60（83.33%） | -5.00 个百分点 |
| 可比较的 both-passed 任务 | \- | 44/60 | \- |
| Input Token（仅 both-passed） | 1,669,974 | 1,457,896 | -212,078（-12.70%） |
| Output Token（仅 both-passed） | 20,355 | 7,590 | -12,765（-62.71%） |
| Total Token（仅 both-passed） | 1,690,329 | 1,465,486 | -224,843（-13.30%） |
| Source characters（仅上下文体积 proxy） | \- | \- | -102,930（-64.82%） |

配对结果为双方均通过 `44`、仅 baseline 通过 `9`、仅 MCP 通过 `6`、双方失败 `1`。失败分类合计为 `rubric_failed=13`、`timeout_before_mcp_call=4`；按 cohort 拆分后，baseline 为 `rubric_failed=5`、`timeout_before_mcp_call=2`，MCP 为 `rubric_failed=8`、`timeout_before_mcp_call=2`。因此 timeout 并非 MCP 独有，且其发生在首次 MCP 调用之前，不能直接归因于工具检索。报告器的验收状态为 `not_accepted`，因为 MCP 通过率低于 baseline；因此 `-13.30%` 只表示双方均成功任务中的诊断性 Token 观察，**不能**作为产品或销售结论，P1-5 保持 `🚧`。

后续复现必须严格配对：任何 startup timeout 都同时重跑该任务的 baseline 与 MCP，保留旧 trace、结果和失败行，预先登记重跑原因与 repeat ID。禁止只重跑 treatment timeout，也禁止把新的预热、启动方式或 timeout 策略混入上述正式 cohort；这类改动必须作为新的实验 cohort 单独报告。

**评分规则复核（2026-08-02）：** `click-prompt-helper` 的 gold 是 `src/click/termui.py:138`，即 `@overload` 的第一个类型签名；同一冻结源码中可执行的 `def prompt` 从第 `167` 行开始。repeat-2 的 MCP 一次 `locate_code` 调用同时返回了 `167-285`、`138-149` 和 `153-164`，Agent 最终报告 `167-285`，所以冻结 rubric 判失败；baseline 报告覆盖 `138` 的范围而通过。这说明该条任务的“必须返回声明”与“开发者应先读实现”的语义尚未明确，不能据此降低实现位置排序或宣称检索缺陷。下一次正式实验前，必须版本化并冻结评分政策：明确只接受首个 overload，或同时接受对应的具体实现定义；若改变政策，必须创建新的任务集版本，保留现有工件不改写。

## 历史首轮外部三仓库 A/B（2026-08-01）

在运行前冻结了 Click、Typer、Requests 的 30 个单入口代码定位任务，每仓库 10 题；生产
`locate_code` 在三个独立索引上的预检均为 `10/10` gold-location coverage。三个目标提交分别为
`00e592cea702e0b2caa0dee42489fdb1c22cd845`、`32d80ef6b4f5aff5094e6983e0928edaa8766c3b` 和
`414f0513c33883adf6f2b46901d4f0b38a455851`。每题运行 fresh `codex exec --ephemeral` 的 baseline
与 manifest-bound `coding-agent` MCP treatment；共同条件为 Codex CLI `0.145.0`、`gpt-5.6-terra`、
`low` reasoning、240 秒 timeout 和 `bypass_sandbox=true`。

可复算 batch 清单为被忽略 artifact 目录中的
`e2e-artifacts/external-token-study-20260801/external-token-ab-v3-run-1-batch.json`；原始 JSONL、
`results.json`、metadata、JSON 报告和 Markdown 报告均保留在同目录。所有纳入汇总的成功行都具有
`codex_exec_json.turn.completed` usage provenance 和已复核的原始 trace SHA-256。

| 指标 | Baseline | MCP | 变化 |
| --- | ---: | ---: | ---: |
| 完整任务通过率（30 题） | 26/30（86.67%） | 23/30（76.67%） | -10.00 个百分点 |
| 可比较的 both-passed 任务 | \- | 20/30 | \- |
| Input Token（仅 both-passed） | 735,130 | 668,897 | -66,233（-9.01%） |
| Output Token（仅 both-passed） | 9,125 | 3,187 | -5,938（-65.07%） |
| Total Token（仅 both-passed） | 744,255 | 672,084 | -72,171（-9.70%） |
| Source characters（仅上下文体积 proxy） | 46,064 | 24,182 | -21,882（-47.50%） |

仓库级总 Token 结果存在明显差异：Click `-10.95%`（5 个 both-passed）、Typer `+9.19%`（9 个）、
Requests `-29.36%`（6 个）。因此正确表述是：**在这一次、三个固定提交的单入口定位对照中，20 个两组均通过
任务的总 Token 降低 9.70%，同时 MCP 完整任务通过率比 baseline 低 10 个百分点。** 它不证明所有代码任务、
所有仓库或所有 MCP 会话都会节省 Token。

本轮也观察到单边 timeout 和失败；Click、Typer、Requests 的 both-passed 样本数分别仅为 5、9、6，说明外部 Agent
运行及 MCP treatment 仍有可用性/随机性风险。Windows 为启动本地 stdio MCP 子进程使用 bypass sandbox，工具限制
来自 prompt/profile 而非 OS 强制。完成至少两次使用相同冻结任务和条件的独立重复，并先处理 timeout 原因前，
不将此结果升级为产品级承诺或标记 P1-5 完成。

## 本地紧凑 profile pilot（2026-08-01）

为验证节省机制是否至少能在真实外部 Agent trace 中出现，使用隔离 checkout
`b4eacc5ba103fcbedff07a275ebd508595ee3c0b` 和独立 lexical-only 索引进行了本地
pilot。该索引包含 220 个文件、12,691 个 chunks；工具级冻结任务集为 8 题，其中生产
`locate_code` 通过 2/8，gold-location coverage 为 `0.625`，mean reciprocal rank 为
`0.396`。因此只有工具级通过的 `mcp-tests` 被纳入本次 Agent 对照。

`run-2-mcp-tests-240s` 使用 Codex CLI `0.145.0`、`gpt-5.6-terra`、`low` reasoning、
240 秒超时和相同 target commit；treatment 使用单工具、manifest-bound 的
`coding-agent` profile。两组均按冻结 rubric 通过，原始 JSONL 的 SHA-256 和
`turn.completed.usage` 已保存。由
`e2e-artifacts/compact-token-pilot-b4eacc/run-2-batch.json` 驱动的报告结果为：

| 指标 | Baseline | coding-agent MCP | 变化 |
| --- | ---: | ---: | ---: |
| Input Token | 50,613 | 34,314 | -16,299（-32.20%） |
| Output Token | 673 | 167 | -506（-75.19%） |
| Total Token | 51,286 | 34,481 | -16,805（-32.77%） |
| Source characters（仅上下文体积 proxy） | 9,999 | 1,790 | -8,209（-82.10%） |

这只是一个**本地、单任务、单次**的机制验证，不能替代外部仓库结论，也不能与历史
3 题的 `+13.18%` 输入 Token 结果抵消或合并。`run-1` 两组均超时，`run-3` 仅 treatment
通过，`run-4` 出现单边失败/超时；它们全部从 Token 汇总中排除，但必须作为 Agent
随机性和可用性风险保留。Windows 上为启动本地 stdio MCP 子进程使用了 bypass sandbox，
本次 tool 限制由 prompt/profile 约束而非 OS 强制；该限制同样不应从最终报告中省略。

聚合器现还会把 `timeout_seconds` 作为强制可比条件，拒绝混合不同超时预算的运行。
它还会要求每个运行写入 `repeat_id`，并输出失败类别与正式验收门禁。正式结论仍要求
3 个陌生公开仓库、至少 20 个任务、至少 20 个 both-passed 任务、至少 2 个独立重复批次，且 MCP
通过率不得低于 baseline；否则报告状态为 `not_accepted`，Token 变化只能作为诊断结果。

## 当前待测优化：紧凑定位路径

`locate_code(..., compact=true)` 已为 Coding Agent 提供最小定位返回：成功时只传仓库快照证明和
`path/start_line/end_line`，不重复传入问题、evidence ID、原因、空 evidence 容器或常规限制说明。
默认详细格式保持不变，供人工审计和需要进一步解释的调用使用；`degraded` 与 `not_found` 的紧凑结果仍保留
检索模式和限制，不能因压缩而掩盖可信度边界。

下一次外部实验先在同一冻结任务上比较 baseline、详细 MCP 和紧凑 MCP 三组。只有紧凑 MCP 的 rubric
通过率不低于详细 MCP，才将它作为正式 MCP treatment；正式运行提示词要求普通定位问题只调用一次
`locate_code(compact=true)`，只有确实需要源码语义时再读取窄范围证据。

为同时减少工具 schema 和每次调用参数，正式紧凑组使用
`python -m service.mcp_server --profile coding-agent`。它只公开一个绑定 manifest 的
`locate_code(question, limit?)` 工具；`repo_id` 与 `snapshot_id` 仅由临时服务端环境变量提供。运行器会把
`mcp_profile` 写入 metadata，聚合脚本拒绝把 `full` 和 `coding-agent` profile 混入同一可比 batch。

## 严格执行顺序

1. 准备至少 3 个陌生的公开仓库，固定每个目标仓库的 40 位 Git commit；每个
   仓库使用隔离的 RepoMind database、data directory、repo_id 与 snapshot_id。
2. 为每个仓库人工编写 5-10 个可评分任务，覆盖符号定位、跨文件影响、执行流和
   配置/边界问题。任务、gold 路径及行号在运行前冻结，且存放在目标仓库之外。
3. 对每项任务，以同一 Codex 版本、模型、reasoning effort、进程/sandbox 模式、
   超时、答案长度和目标 commit 运行 fresh ephemeral baseline 与 MCP treatment。
   Baseline 只允许正常搜索/读取；treatment 只允许临时、manifest 绑定的 MCP。
4. 每个条件独立重复运行。最小发布样本为 20 个任务、3 个仓库；若外部 Agent
   具有明显随机性，至少每个 cohort/task 重复 3 次，并将每次保留为独立 batch run。
5. 以 `scripts/report_mcp_token_savings.py` 聚合 raw JSONL 旁生成的
   `results.json` 与 `run-metadata.json`。报告仅对 both-passed 任务计算
   input/output/total Token saving，不能用失败或超时任务降低 treatment 成本。
6. 发布时同时给出：目标仓库和 commit、任务数、both-passed 数、两组通过率、
   外部 Agent/client 版本、模型、reasoning effort、总 input/output/total Token、
   绝对与百分比变化、运行次数及局限性。source characters 仅作上下文体积辅助项。

## 验收与表述

验收不预设必须为正数。真实报告可能显示节省、持平或增加 Token；任何一种结果
都应如实保留。只有通过上述门槛并保存可复核的 usage provenance/trace 哈希后，
项目才能说“在该范围内通过 MCP 实际节省了 X% Token”。推荐表述必须包含样本和
质量条件，例如：

> 在 3 个固定 commit 的公开仓库、24 个任务、同模型与同 reasoning effort 的
> 对照中，RepoMind MCP 在 22 个两组均通过的任务上使外部 Agent 总 Token 变化
> X%；Baseline/MCP 通过率分别为 B%/M%。

相关协议见 [2026-08-01_MCP_TOKEN_SAVINGS_PROTOCOL_MCP节省Token评测协议.md](../../examples/benchmarks/2026-08-01_MCP_TOKEN_SAVINGS_PROTOCOL_MCP节省Token评测协议.md)。

---

## CI 回归门禁（P0-1 完成后立即加）
