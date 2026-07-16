# RepoMind

RepoMind 是一个面向 Windows 的本地 Git 仓库知识助手：把 commit 变成不可变 Snapshot，用结构化 Evidence/Catalog 和混合检索回答“这个仓库是什么、从哪里开始读、改动会影响什么”。每个回答都可以回到 commit、文件路径、源码行和 Main Agent Trace。

它不是自动编程工具：不会执行目标仓库代码，不修改文件，不自动提交或创建 PR，也不是让多个 Agent 自由聊天。Legacy 多角色页面仅保留作兼容展示；主流程是一个有边界的 Main Agent，按规则选择零个或一个只读 Specialist Tool。

## 为什么值得看

这个项目解决的是“读懂陌生仓库”而不是“替你写代码”：

- Snapshot 层把一次 commit 的文件、符号和解析结果固定下来，避免回答混用工作区与历史版本。
- Evidence/Catalog 层把 Markdown、Python、配置等内容统一成可定位证据，支持 FTS5/BM25、可选 Embedding 和 RRF 融合。
- Main Agent 层先做确定性路由：局部解释走 0 工具，安全问题只走 `security_review`，影响问题只走 `dependency_impact`；每次执行都留下 Trace。

### 为什么需要协作层

仓库概览、局部解释、安全线索和影响分析需要不同的证据范围与输出约束。让一个模型自由发挥会难以复现、审计和定位引用；RepoMind 因此让 Main Agent 统一管理 Snapshot、Evidence 预算和最终回答，再按意图委派一个窄边界 Specialist Tool。这里的“多智能体”是可观测的受约束协作，不是多个 Agent 互相编故事的聊天室；代码中的两个核心层分别是 Evidence/RAG 层与 Main Agent/工具层。

```mermaid
flowchart LR
  A[Git commit] --> B[Immutable Snapshot]
  B --> C[Parser]
  C --> D[Evidence + Catalog]
  D --> E[FTS5/BM25 + optional Embedding/RRF]
  E --> F[Bounded Main Agent]
  F -->|local explanation| G[Direct answer · 0 tools]
  F -->|security| H[Security Review]
  F -->|impact| I[Dependency Impact]
  G --> J[Answer + file/path/line refs]
  H --> J
  I --> J
  J --> K[Agent Trace · Markdown/JSON export]
```

## 真实 Demo

内置 Demo 固定在 commit `e718d4a31f9df9d74b8b74fe5f5e49b92625862b`。在无网络、无 Chat Key、无 Embedding Key 的临时环境中，结果为：`main`、10 个文件、150 个知识片段、Snapshot succeeded、Catalog 可读。

![一键 Demo 入口](docs/assets/screenshots/01-demo-entry.png)

![Snapshot 与 Catalog](docs/assets/screenshots/02-snapshot-catalog.png)

![局部解释问答](docs/assets/screenshots/03-local-answer.png)

![Evidence 与源码行](docs/assets/screenshots/04-evidence-drawer.png)

![安全问题与 Main Agent Trace](docs/assets/screenshots/05-security-trace.png)

![Workflow 分析与 Markdown 导出](docs/assets/screenshots/06-workflow-export.png)

真实运行状态序列（约 45 秒）：

![RepoMind showcase](docs/assets/repomind-showcase.gif)

公开示例产物：[`examples/outputs/repomind-demo-report.md`](examples/outputs/repomind-demo-report.md) · [`examples/outputs/repomind-demo-trace.json`](examples/outputs/repomind-demo-trace.json)

## 三个最能说明边界的问题

| 问题 | 期望路由 | 展示什么 |
| --- | --- | --- |
| `GreetingService.build_message 方法是做什么的？` | 0 tools | 直接从 Evidence 回答，并打开文件与行号 |
| `这个仓库有哪些安全风险线索？` | `security_review` | 只调用安全工具，Trace 显示 route → retrieval → tool → synthesis |
| `修改 GreetingService.build_message 可能影响哪些调用方和测试？` | `dependency_impact` | 只调用影响分析，展示一跳关系与相关测试 |

## 快速运行

开发环境需要 Windows、Python 3.11+、Node.js 20+。

```powershell
cd repo-knowledge-assistant
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt

cd desktop/app
npm ci
npm run dev
```

打开桌面端后点击“打开内置 Demo”。不配置 Chat/Embedding Key 也能完成 Snapshot、Catalog、lexical 检索、规则回答、Evidence 和 Trace；真实模型调用需要在本地设置页显式配置。

## 当前验证结果

- Backend：`pytest -q backend/tests` → **92 passed**。
- Desktop：`npm test -- --run` → **24 passed**。
- Desktop build：`npm run build`（Vite renderer + Electron TypeScript）通过。
- 冻结后端 smoke：schema、FTS5、无 Key 降级、进程退出和文件锁检查通过。
- Demo 验收：局部问题 0 工具；安全问题仅 `security_review`；影响问题仅 `dependency_impact`；不存在的 Trace 返回 404；重复打开 Demo 幂等。

这些数字是本地真实运行结果，不代表远端 CI、签名安装包或正式 Release 已完成。

## 安全与数据边界

RepoMind 默认只读目标仓库，不执行其中的代码。开发/截图/测试应使用临时 `REPOMIND_USER_DATA_PATH` 和临时数据库；不要提交数据库、日志、密钥或构建产物。安全报告与披露方式见 [`SECURITY.md`](SECURITY.md)。

## 文档入口

- [`README.en.md`](README.en.md)：English overview。
- [`docs/后续开发指导/DEVELOPMENT_REPORT.md`](docs/后续开发指导/DEVELOPMENT_REPORT.md)：当前实现与验证记录。
- [`docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md`](docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md)：架构与后续路线图。
- [`docs/后续开发指导/RAG_VS_AGENTIC.md`](docs/后续开发指导/RAG_VS_AGENTIC.md)：RAG 与受约束 Agent 的分工。
- [`docs/多模态AI交接/RepoMind_多模态AI展示与发布任务书.md`](docs/多模态AI交接/RepoMind_多模态AI展示与发布任务书.md)：展示与发布验收边界。

## 贡献与路线图

欢迎通过 Issue/PR 讨论解析器、检索质量、Evidence 可解释性和 Windows 体验。请先阅读 [`SECURITY.md`](SECURITY.md) 与任务书的公开边界；不要上传真实私有仓库、凭据或未经脱敏的运行数据。

下一步按优先级推进：Markdown/Trace 导出体验 → 双语文档与公开示例 → Windows Electron E2E 与远端 CI → NSIS/Portable/SHA-256 与 v0.1.0 Release。不会为了展示而增加无边界的新 Agent 或模型 Provider。
