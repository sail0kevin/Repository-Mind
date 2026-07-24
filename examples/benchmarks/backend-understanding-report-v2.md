# Retrieval benchmark: repomind-backend-understanding-v1

- Snapshot: `c92e2f9af153212074da62d2d7fc1418bfbc0d72`
- Mode: `lexical`
- Queries: **40**
- Recall@5: **0.267**
- Recall@10: **0.379**
- MRR: **0.245**
- Citation hit rate: **0.550**
- Citation precision: **0.166**
- Task completion rate: **0.550** (22/40)
  - Citation path missing: 0
  - Relevant evidence missing: 18
  - Refused: 0
- Tool selection exact-match rate: **1.000**
  - Missing expected tool: 0.000
  - Unexpected extra tool: 0.000
  - Scope: expected tools are labeled from the same deterministic Router rules; this is a regression check, not an unseen-query generalization score.

## Per-query actual cited files

### `sn-route-question`

- Question: `route_question 这个函数的作用是什么？`
- Route tools: `[]`
- Actual cited files: `backend/service/core/agent/router.py`, `backend/tests/test_m4_main_agent.py`, `examples/benchmarks/demo-evidence-report-post-fix.md`, `desktop/app/renderer/src/main.tsx`, `examples/outputs/repomind-demo-trace.json`, `demo/repomind-demo/README.md`
- Relevant cited files: `backend/service/core/agent/router.py`
- Result: **passed**

### `sn-rrf-fuse`

- Question: `ReciprocalRankFusion.fuse 是如何给多路候选打分的？`
- Route tools: `[]`
- Actual cited files: `backend/service/core/retrieval/fusion.py`, `backend/tests/test_m3_hybrid_retrieval.py`, `backend/service/core/retrieval/service.py`
- Relevant cited files: `backend/service/core/retrieval/fusion.py`
- Result: **passed**

### `sn-hybrid-retrieve`

- Question: `HybridRetriever.retrieve 的检索流程是怎样的？`
- Route tools: `[]`
- Actual cited files: `backend/service/core/retrieval/service.py`, `backend/tests/test_m3_hybrid_retrieval.py`, `backend/service/core/retrieval/lexical.py`, `backend/service/core/retrieval/__init__.py`
- Relevant cited files: `backend/service/core/retrieval/service.py`
- Result: **passed**

### `sn-evidence-assemble`

- Question: `EvidenceAssembler.assemble 负责做什么？`
- Route tools: `[]`
- Actual cited files: `backend/service/core/evidence/assembler.py`, `backend/tests/test_evidence_assembler.py`
- Relevant cited files: `backend/service/core/evidence/assembler.py`
- Result: **passed**

### `sn-run-main-agent`

- Question: `run_main_agent 完成一次问答要经过哪几个阶段？`
- Route tools: `[]`
- Actual cited files: `backend/service/core/agent/main_agent.py`, `docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`, `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`, `backend/service/core/agent/models.py`
- Relevant cited files: `backend/service/core/agent/main_agent.py`
- Result: **passed**

### `sn-agentplan-structure`

- Question: `AgentPlan 的类结构和字段有哪些？`
- Route tools: `['language_structure']`
- Actual cited files: `backend/service/core/agent/models.py`, `backend/service/core/agent/router.py`, `backend/service/core/agent/__init__.py`
- Relevant cited files: `backend/service/core/agent/models.py`
- Result: **passed**

### `sn-retrievalplan-fields`

- Question: `列出 RetrievalPlan 的字段和方法列表。`
- Route tools: `['language_structure']`
- Actual cited files: `backend/service/core/retrieval/planner.py`, `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`
- Relevant cited files: `backend/service/core/retrieval/planner.py`
- Result: **passed**

### `sn-evidencebudget-symbol`

- Question: `EvidenceBudget 这个符号定义了哪些预算项？`
- Route tools: `['language_structure']`
- Actual cited files: `backend/service/core/evidence/assembler.py`, `backend/service/core/evidence/budget.py`, `backend/tests/fixtures/parsing/pkg/other.py`
- Relevant cited files: `backend/service/core/evidence/budget.py`
- Result: **passed**

### `di-route-question-callers`

- Question: `修改 route_question 的关键字规则会影响哪些调用方？`
- Route tools: `['dependency_impact']`
- Actual cited files: `backend/service/core/agent/router.py`, `backend/tests/test_m4_main_agent.py`, `examples/benchmarks/code-understanding-gold.json`
- Relevant cited files: `backend/service/core/agent/router.py`
- Result: **passed**

### `di-run-main-agent-deps`

- Question: `run_main_agent 依赖哪些模块和函数来完成一次问答？`
- Route tools: `['dependency_impact']`
- Actual cited files: `backend/service/core/agent/main_agent.py`, `docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`, `backend/service/core/debate.py`
- Relevant cited files: `backend/service/core/agent/main_agent.py`
- Result: **passed**

### `di-evidencebudget-impact`

- Question: `改动 EvidenceBudget 的常量会影响证据组装的哪些逻辑？`
- Route tools: `['dependency_impact']`
- Actual cited files: `backend/service/core/evidence/budget.py`, `backend/tests/test_evidence_assembler.py`, `backend/tests/test_m3_hybrid_retrieval.py`, `examples/benchmarks/code-understanding-gold.json`, `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`, `README.md`, `backend/tests/test_m4_main_agent.py`
- Relevant cited files: `backend/service/core/evidence/budget.py`
- Result: **passed**

### `di-fusion-consumers`

- Question: `ReciprocalRankFusion.fuse 的融合结果被检索流程中的谁依赖？`
- Route tools: `['dependency_impact']`
- Actual cited files: `backend/service/core/retrieval/fusion.py`, `backend/tests/test_m3_hybrid_retrieval.py`, `backend/service/core/retrieval/service.py`
- Relevant cited files: `backend/service/core/retrieval/fusion.py`, `backend/service/core/retrieval/service.py`
- Result: **passed**

### `di-publish-snapshot`

- Question: `谁调用 publish_snapshot，它在索引流程中处于哪个位置？`
- Route tools: `['dependency_impact']`
- Actual cited files: `backend/service/storage/snapshot_store.py`, `backend/tests/test_m3_catalog.py`, `backend/tests/test_m3_lexical_retrieval.py`, `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`, `examples/benchmarks/code-understanding-gold.json`, `demo/repomind-demo/README.md`, `backend/service/core/agent/router.py`
- Relevant cited files: `backend/service/storage/snapshot_store.py`
- Result: **passed**

### `di-embed-snapshot`

- Question: `embed_snapshot_evidence 受哪个索引步骤的调用影响，又会影响后续什么？`
- Route tools: `['dependency_impact']`
- Actual cited files: `backend/service/core/embeddings/service.py`, `backend/tests/test_m3_embeddings.py`, `README.md`, `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`, `examples/benchmarks/code-understanding-gold.json`, `demo/repomind-demo/README.md`
- Relevant cited files: `backend/service/core/embeddings/service.py`
- Result: **passed**

### `di-semantic-available`

- Question: `SemanticRetriever.available 返回 False 会影响检索计划的哪些选择？`
- Route tools: `['dependency_impact']`
- Actual cited files: `backend/service/core/retrieval/semantic.py`, `backend/tests/test_m3_hybrid_retrieval.py`, `backend/service/core/retrieval/service.py`, `backend/service/core/retrieval/planner.py`
- Relevant cited files: `backend/service/core/retrieval/semantic.py`, `backend/service/core/retrieval/service.py`, `backend/service/core/retrieval/planner.py`
- Result: **passed**

### `di-ask-endpoint`

- Question: `ask 接口的改动依赖哪个核心函数来生成回答？`
- Route tools: `['dependency_impact']`
- Actual cited files: `desktop/app/renderer/services/apiClient.ts`, `docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`, `desktop/app/renderer/src/main.tsx`, `examples/benchmarks/code-understanding-gold.json`, `README.md`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `sr-scan-patterns`

- Question: `security_review 工具会扫描哪些安全风险模式？`
- Route tools: `['security_review']`
- Actual cited files: `.github/workflows/ci-windows.yml`, `.gitignore`, `backend/service/core/agent/router.py`, `examples/outputs/repomind-demo-trace.json`, `examples/outputs/repomind-demo-trace.post-fix.json`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `sr-dpapi-secret`

- Question: `WindowsDPAPISecretStore 是如何保护 API 密钥的？`
- Route tools: `['security_review']`
- Actual cited files: `.github/workflows/ci-windows.yml`, `.gitignore`, `backend/service/core/agent/router.py`, `backend/tests/test_m3_embeddings.py`, `backend/service/api/v1/settings.py`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `sr-dynamic-exec`

- Question: `安全审查如何识别 eval、exec 这类动态执行风险？`
- Route tools: `['security_review']`
- Actual cited files: `.github/workflows/ci-windows.yml`, `.gitignore`, `backend/service/core/agent/router.py`, `examples/outputs/repomind-demo-report.md`, `backend/service/core/agent/tools.py`, `demo/repomind-demo/README.md`
- Relevant cited files: `backend/service/core/agent/tools.py`
- Result: **passed**

### `sr-unsafe-deser`

- Question: `安全扫描怎样发现 yaml.load、pickle.loads 这类不安全反序列化？`
- Route tools: `['security_review']`
- Actual cited files: `.github/workflows/ci-windows.yml`, `.gitignore`, `backend/service/core/agent/router.py`, `backend/service/core/agent/tools.py`, `demo/repomind-demo/README.md`, `examples/outputs/repomind-demo-trace.post-fix.json`
- Relevant cited files: `backend/service/core/agent/tools.py`
- Result: **passed**

### `sr-token-auth`

- Question: `桌面端接口的令牌认证是怎么实现的？`
- Route tools: `['security_review']`
- Actual cited files: `.github/workflows/ci-windows.yml`, `.gitignore`, `backend/service/core/agent/router.py`, `demo/repomind-demo/README.md`, `backend/tests/test_desktop_security.py`, `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`, `examples/outputs/repomind-demo-trace.post-fix.json`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `sr-redact-secret`

- Question: `redact_secret 如何防止密钥泄漏到提示文本里？`
- Route tools: `['security_review']`
- Actual cited files: `.github/workflows/ci-windows.yml`, `.gitignore`, `backend/service/core/agent/router.py`, `backend/service/core/redaction.py`, `backend/tests/test_settings_security.py`
- Relevant cited files: `backend/service/core/redaction.py`
- Result: **passed**

### `sr-subprocess-shell`

- Question: `安全扫描如何标记 subprocess shell=True 的命令执行风险？`
- Route tools: `['security_review']`
- Actual cited files: `.github/workflows/ci-windows.yml`, `.gitignore`, `backend/service/core/agent/router.py`, `examples/outputs/repomind-demo-report.md`, `demo/repomind-demo/README.md`, `examples/outputs/repomind-demo-trace.post-fix.json`, `demo/repomind-demo/repomind_demo/security_examples.py`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `sr-embedding-key-isolation`

- Question: `为什么 get_embedding_api_key 不复用 Chat 的密钥？`
- Route tools: `['security_review']`
- Actual cited files: `.github/workflows/ci-windows.yml`, `.gitignore`, `backend/service/core/agent/router.py`, `backend/service/core/embeddings/service.py`, `backend/service/api/v1/settings.py`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `rn-overall-architecture`

- Question: `这个项目的整体架构是怎样设计的？`
- Route tools: `['repository_navigator']`
- Actual cited files: `desktop/app/renderer/src/main.tsx`, `demo/repomind-demo/README.md`, `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`, `examples/outputs/repomind-demo-trace.json`, `examples/outputs/repomind-demo-trace.post-fix.json`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `rn-retrieval-modules`

- Question: `检索子系统由哪些主要模块组成？`
- Route tools: `['repository_navigator']`
- Actual cited files: `docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`, `examples/benchmarks/code-understanding-gold.json`, `docs/后续开发指导/GITHUB_UPLOAD_GUIDE.md`, `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `rn-fastapi-entry`

- Question: `FastAPI 应用的入口在哪里定义？`
- Route tools: `['repository_navigator']`
- Actual cited files: `examples/benchmarks/code-understanding-gold.json`, `backend/service/main.py`, `README.md`, `backend/service/api/v1/jobs.py`
- Relevant cited files: `backend/service/main.py`
- Result: **passed**

### `rn-storage-modules`

- Question: `存储层由哪些主要模块组成？`
- Route tools: `['repository_navigator']`
- Actual cited files: `docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`, `examples/benchmarks/code-understanding-gold.json`, `docs/后续开发指导/GITHUB_UPLOAD_GUIDE.md`, `backend/service/storage/evidence_store.py`
- Relevant cited files: `backend/service/storage/evidence_store.py`
- Result: **passed**

### `rn-agent-core`

- Question: `Agent 核心代码的架构和入口是什么？`
- Route tools: `['repository_navigator']`
- Actual cited files: `desktop/app/renderer/src/main.tsx`, `README.md`, `docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `rn-evaluation-overview`

- Question: `评测子系统的概览是怎样的？`
- Route tools: `['repository_navigator']`
- Actual cited files: `docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`, `demo/repomind-demo/README.md`, `desktop/app/vite.config.ts`, `backend/service/core/embeddings/__init__.py`, `backend/tests/test_m4_main_agent.py`, `desktop/app/e2e/global-teardown.ts`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `rn-embedding-modules`

- Question: `Embedding 相关的主要模块分布在哪里？`
- Route tools: `['repository_navigator']`
- Actual cited files: `docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`, `examples/benchmarks/code-understanding-gold.json`, `desktop/app/renderer/src/main.tsx`, `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `rn-rest-api`

- Question: `REST API 的整体架构和主要入口是什么？`
- Route tools: `['repository_navigator']`
- Actual cited files: `desktop/app/renderer/src/main.tsx`, `demo/repomind-demo/README.md`, `examples/outputs/repomind-demo-report.md`, `docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`, `README.md`, `examples/benchmarks/demo-evidence-capture.json`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `tr-router-tests`

- Question: `哪些测试用例验证了 Router 的路由行为？`
- Route tools: `['test_runtime']`
- Actual cited files: `examples/benchmarks/code-understanding-gold.json`, `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`, `examples/outputs/repomind-demo-trace.post-fix.json`, `README.md`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `tr-assembler-tests`

- Question: `EvidenceAssembler 的单元测试覆盖了什么？`
- Route tools: `['test_runtime']`
- Actual cited files: `examples/outputs/repomind-demo-report.md`, `backend/tests/test_evidence_assembler.py`, `examples/benchmarks/code-understanding-gold.json`, `backend/service/core/evidence/__init__.py`
- Relevant cited files: `backend/tests/test_evidence_assembler.py`
- Result: **passed**

### `tr-snapshot-branches`

- Question: `快照的成功与失败分支分别由哪些测试保证？`
- Route tools: `['test_runtime']`
- Actual cited files: `examples/benchmarks/code-understanding-gold.json`, `docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`, `README.md`, `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`, `desktop/app/e2e/global-teardown.ts`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `tr-metrics-tests`

- Question: `Recall 和 MRR 指标的计算有测试覆盖吗？`
- Route tools: `['test_runtime']`
- Actual cited files: `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`, `backend/service/evaluation/retrieval_metrics.py`, `docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `tr-nokey-fallback`

- Question: `缺少模型凭据时的降级问答由哪个测试验证？`
- Route tools: `['test_runtime']`
- Actual cited files: `docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`, `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`, `README.md`, `examples/benchmarks/code-understanding-gold.json`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `tr-desktop-token`

- Question: `业务接口鉴权、health 接口保持公开的行为由哪个测试用例覆盖？`
- Route tools: `['test_runtime']`
- Actual cited files: `examples/benchmarks/code-understanding-gold.json`, `desktop/app/renderer/test/setup.ts`, `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`, `demo/repomind-demo/repomind_demo/service.py`, `backend/tests/test_desktop_security.py`, `docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`
- Relevant cited files: `backend/tests/test_desktop_security.py`
- Result: **passed**

### `tr-settings-redaction`

- Question: `敏感信息存储与脱敏迁移由哪些测试保证？`
- Route tools: `['test_runtime']`
- Actual cited files: `docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`, `examples/benchmarks/code-understanding-gold.json`, `examples/outputs/repomind-demo-trace.post-fix.json`, `docs/后续开发指导/GITHUB_UPLOAD_GUIDE.md`, `backend/service/api/v1/settings.py`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

### `tr-workflow-snapshot`

- Question: `工作流快照的分页与契约由哪些测试用例覆盖？`
- Route tools: `['test_runtime']`
- Actual cited files: `examples/benchmarks/code-understanding-gold.json`, `backend/service/storage/models.py`, `docs/后续开发指导/RESUME_EVIDENCE_PLAN.md`, `demo/repomind-demo/tests/test_greeting.py`
- Relevant cited files: none
- Result: **failed** — no relevant path was cited.

## Limitations

- This capture evaluates cited evidence paths only; it does not judge answer semantics.
- Tool-routing mismatches against the gold file's expected_tools are logged as warnings, not hard failures.
- Latency is omitted because this script does not establish a controlled timing protocol.
- known_paths is capped at 1000 files by the /files endpoint; larger repositories are only partially covered.
