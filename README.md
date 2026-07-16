<div align="center">

# RepoMind

### 面向 Windows 的本地 Git 仓库知识助手

将指定 Git commit 构建为不可变知识快照，通过结构化解析、混合检索和有边界的 Agent 调度，帮助开发者快速理解陌生仓库，并生成可回溯到 **commit、文件路径、源码行号和执行轨迹** 的回答。

[![Windows CI](https://github.com/sail0kevin/Repository-Mind/actions/workflows/ci-windows.yml/badge.svg)](https://github.com/sail0kevin/Repository-Mind/actions/workflows/ci-windows.yml)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4)
![Python](https://img.shields.io/badge/Python-3.12-3776AB)
![Node.js](https://img.shields.io/badge/Node.js-20.18.0-339933)

[核心能力](#核心能力) · [系统架构](#系统架构) · [快速开始](#快速开始) · [面试讲解要点](#面试讲解要点) · [开发报告](docs/后续开发指导/DEVELOPMENT_REPORT.md)

</div>

> [!IMPORTANT]
> RepoMind 默认只读分析目标仓库：**不执行被分析代码、不安装其依赖、不修改目标仓库，也不自动提交代码或创建 PR。**

## 这个项目解决什么问题

面对一个陌生代码仓库，开发者通常需要反复确认：

- 项目入口在哪里，应该从哪些目录和文件开始阅读？
- 某个函数、配置或接口发生修改后，可能影响哪些模块？
- 项目如何启动、如何测试，相关配置在哪里？
- AI 给出的结论引用的是哪个版本、哪个文件、哪些代码行？
- 仓库更新后，历史回答引用的源码是否仍然可信？

RepoMind 将这些步骤组织为一条绑定 Git commit 的本地知识链路。它不会直接把整个仓库塞给大模型，而是先构建可复用、可检索、可追溯的知识快照，再由 Main Agent 基于证据生成回答。

典型问题包括：

```text
“这个仓库应该从哪里开始读？”
“修改这个函数可能影响哪些模块和测试？”
“认证、密钥和权限相关代码有哪些风险线索？”
“项目的启动入口和测试命令在哪里？”
```

## 当前验证状态

以下结果来自 **2026-07-16 的本地 Windows 验证**：

| 验证项 | 结果 | 说明 |
| --- | ---: | --- |
| 后端自动化测试 | **87 passed** | 覆盖迁移、Snapshot、解析、检索、Agent、设置安全等 |
| 桌面端自动化测试 | **22 passed** | 覆盖 API Client 与仓库注册状态逻辑 |
| Renderer production build | 通过 | Vite production build |
| Electron TypeScript build | 通过 | Electron 主进程与 preload 编译 |
| 数据库 Schema | **Version 7** | 实际数据库迁移结果 |
| SQLite FTS5 | 通过 | 冻结后端执行真实 MATCH 查询 |
| PyInstaller 冻结后端 Smoke | 通过 | 启动、迁移、FTS5、无 Key、隔离数据库、进程清理 |
| NSIS Setup / Portable | 本地生成成功 | 发布二进制不提交到 Git 仓库 |
| GitHub Actions | 工作流已配置 | 远端状态以 Actions 页面实际运行结果为准 |

> 自动化测试和小型回归 fixture 不等同于大型真实仓库的检索质量评测。当前尚未完成大规模仓库的 Recall@K、P50/P95 延迟和磁盘占用基准。

## 核心能力

### 1. Commit 级不可变知识快照

- 以 `repo_id + commit SHA` 唯一标识 Repository Snapshot；
- 文件、Evidence、Catalog、检索结果、回答引用和 Agent Trace 均绑定具体 Snapshot；
- 同一 commit 重复 ingest 保持幂等；
- 只有完整构建成功的 Snapshot 才能切换为 active；
- 新 Snapshot 构建失败时，继续保留上一份成功版本；
- 索引期间如果 HEAD、分支或文件内容发生漂移，本次 Snapshot 不会发布。

为保证每条回答都能回溯到确定 commit，RepoMind 要求被索引仓库具有有效 HEAD，并保持干净工作树。

### 2. 多语言结构解析与可追溯 Evidence

统一 `ParserAdapter` 支持：

- Python AST；
- JavaScript / TypeScript tree-sitter；
- Markdown 标题结构；
- JSON / YAML / TOML 配置结构；
- 通用文本 fallback。

解析结果统一保存为 Evidence Units、Symbols、Relations 和 Parser Diagnostics。每条 Evidence 均可定位到 Snapshot、文件路径、起止行号和内容哈希；无法可靠解析的文件会明确标记为 fallback。

### 3. FTS5/BM25 与可选混合检索

RepoMind 默认使用 SQLite FTS5/BM25 进行本地词法检索，并支持：

- 标识符、路径和配置键查询；
- snake_case、camelCase 等查询归一化；
- 可选 OpenAI-compatible Embedding；
- RRF 多路融合；
- Evidence ID 去重；
- 基于已观察静态关系的一跳结构扩展。

Embedding 使用独立配置和独立 API Key，默认关闭。未配置或调用失败时，系统会明确降级为 `lexical-only`，不会阻断仓库索引和搜索。

### 4. Token 预算 Evidence Bundle

检索结果不会无限加入模型上下文。Evidence Assembler 会在预算内选择、去重和裁剪：

| 预算项 | 默认值 |
| --- | ---: |
| Bundle 总预算 | 2,400 估算 token |
| 单条 Evidence 上限 | 600 估算 token |
| 最大 Evidence 数量 | 12 |
| 单文件最大占比 | 50% |
| 优先覆盖来源文件 | 至少 2 个 |

这里的 token 是用于本地上下文裁剪的启发式估算，不是供应商的精确计费 token。

### 5. 有边界的 Main Agent 与 Specialist Tools

Main Agent 使用**确定性意图路由**选择只读 Specialist Tool，同时执行混合检索和 Evidence Bundle 裁剪，最后统一生成回答并保存 Trace。

当前提供：Repository Navigator、Dependency Impact、Test / Runtime、Security Review 和 Language Structure 五类工具。

普通问题通常不调用工具；依赖影响、测试、安全或语言结构问题才进入对应工具。执行层设置单次最多两个工具的硬上限，当前互斥路由规则通常选择零个或一个工具，不存在无限自主循环。

### 6. 无 Key 降级与密钥隔离

- Chat 与 Embedding 配置完全分离；
- Windows 桌面版使用当前用户的 DPAPI 加密保存密钥；
- 设置接口不会返回完整 API Key；
- Embedding 不可用时降级为 `lexical-only`；
- Chat Key 未配置或模型调用失败时，返回基于证据的规则型回答；
- Specialist Tool 失败时保留可用结果，并附加 limitation；
- 新 Snapshot 失败时继续使用上一成功 Snapshot。

### 7. 源码引用与 Agent Trace

每次问答可以保存并展示：

- 问题绑定的 Snapshot 和 commit；
- 实际检索模式；
- Evidence 预算、入选和裁剪信息；
- 路由决策与工具选择原因；
- 工具状态、耗时和限制；
- 最终引用的 Evidence IDs；
- 回答生成模式。

桌面端读取回答所属 Snapshot 中已经持久化的 Evidence，不会使用后来变化的工作区文件冒充历史证据。

## 系统架构

```text
┌─────────────────────────────────────────────────────────────┐
│                 Electron + React Desktop                    │
│  仓库注册 · Snapshot · Catalog · 搜索 · 问答 · Evidence    │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTP / API v1
┌────────────────────────────▼────────────────────────────────┐
│                       FastAPI Backend                       │
│                                                             │
│  Local Git Repository / Public GitHub URL                   │
│                  │                                          │
│                  ▼                                          │
│        Commit-level Immutable Snapshot                      │
│                  │                                          │
│                  ▼                                          │
│             ParserAdapter                                   │
│       ┌──────────┼──────────┐                               │
│       ▼          ▼          ▼                               │
│   Evidence    Symbols    Relations / Diagnostics            │
│       │                       │                              │
│       ├────────────┬──────────┘                              │
│       ▼            ▼                                        │
│ SQLite FTS5/BM25  Optional Embedding                        │
│       └──────┬─────┘                                        │
│              ▼                                              │
│    RRF + Structural Expansion                               │
│              │                                              │
│              ▼                                              │
│     Token-budget Evidence Bundle                            │
│              │                                              │
│              ▼                                              │
│          Main Agent                                         │
│       ┌──────┴─────────┐                                    │
│       ▼                ▼                                    │
│ Direct Answer    Read-only Specialist Tool                  │
│       └──────┬─────────┘                                    │
│              ▼                                              │
│ Answer + commit/path/line Citations + Agent Trace           │
└────────────────────────────┬────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │ SQLite + DPAPI  │
                    │ Snapshot / FTS  │
                    │ Evidence / Trace│
                    └─────────────────┘
```

## 端到端工作流程

1. 验证有效 Git HEAD 和干净工作树；
2. 将当前 commit 捕获为不可变 Snapshot；
3. 解析 Evidence、Symbol、Relation 和诊断信息；
4. 写入 FTS5/BM25、可选 Embedding 和分层 Catalog；
5. 通过词法/语义召回、RRF 和结构扩展生成候选证据；
6. 在 Token、条目数和单文件占比预算内组装 Evidence Bundle；
7. Main Agent 直接回答或按问题类型调用只读专业工具；
8. 保存引用、路由、检索、工具调用和 limitation。

## 桌面端工作区

Electron 桌面端提供：

- 本地仓库与公开 GitHub 仓库注册；
- 最近仓库切换；
- Snapshot 列表、切换与刷新；
- Repository Catalog 和目录树；
- 文件内容与源码行号浏览；
- Snapshot-aware 搜索与问答；
- Evidence 卡片和历史源码查看；
- Main Agent Trace；
- Chat 与 Embedding 独立设置；
- 高级 / Legacy 多角色协作入口。

> 当前仓库还没有加入公开产品截图。推送后会优先补充主工作区、Evidence 行号导航和 Agent Trace 的真实运行截图，不使用设计稿冒充产品界面。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| Backend | Python 3.12、FastAPI、Pydantic、SQLite |
| Parsing | Python AST、tree-sitter、Markdown / Config Adapters |
| Retrieval | SQLite FTS5/BM25、可选 Embedding、RRF、静态关系扩展 |
| Agent | Deterministic Router、Read-only Specialist Tools、Persistent Trace |
| Desktop | Electron、React、TypeScript、Vite |
| Testing | pytest、Vitest、React Testing Library |
| Packaging | PyInstaller、electron-builder、NSIS |
| CI / Release | GitHub Actions Windows Runner |

## 快速开始

### 环境要求

- Windows 10/11 x64；
- Python 3.12；
- Node.js 20.18.0；
- npm 10.x；
- Git；
- Windows PowerShell 5.1 或 PowerShell 7。

### 1. 克隆项目

```powershell
git clone https://github.com/sail0kevin/Repository-Mind.git
cd Repository-Mind
```

### 2. 安装并启动后端

```powershell
python -m pip install -r backend/requirements-dev.txt
cd backend
python -m service.main
```

默认 API 地址：`http://127.0.0.1:8000/api/v1`

### 3. 启动桌面端

另开一个 PowerShell：

```powershell
cd desktop/app
npm ci
npm run dev
```

> Embedding 默认关闭。没有 Chat API Key 时，Snapshot、FTS5/BM25 检索和规则型回答仍然可用。

### 构建 Windows 应用

```powershell
python -m pip install -r backend/requirements-build.txt

powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/package_windows.ps1 `
  -PythonCommand python `
  -Release
```

主要产物：

```text
backend-dist/repomind-backend.exe
desktop/app/release/RepoMind-<version>-x64-setup.exe
desktop/app/release/RepoMind-<version>-x64-portable.exe
desktop/app/release/SHA256SUMS.txt
```

当前 Setup 和 Portable 已完成本地构建验证，但公开 GitHub Release 尚未发布。

## 项目结构

```text
Repository-Mind/
├── backend/                   Snapshot、解析、检索、Evidence 与 Main Agent
├── desktop/app/               Electron + React + TypeScript 桌面应用
├── scripts/                   Windows 构建、Smoke 与身份契约检查
├── docs/后续开发指导/          当前架构、开发报告和上传说明
├── .github/workflows/         Windows CI 与 Release workflow
├── .env.example
├── .nvmrc
├── .python-version
└── README.md
```

## 面试讲解要点

### 为什么不是普通的“代码聊天”？

RepoMind 先将 Git commit 固化为 Snapshot，再构建 Evidence、符号关系、Catalog 和检索索引。因此回答可以绑定确定版本、文件和行号，而不是引用当前工作区中的不确定内容。

### 为什么采用 RAG + Agent，而不是二选一？

- RAG 负责低成本、可复用、可追溯的仓库知识底座；
- Agent 负责问题分类、受约束的工具调用和结果综合；
- 普通问题不启动固定多角色链，避免重复检索和额外 Token 消耗。

### 最关键的数据一致性设计是什么？

Snapshot 只有完整构建成功后才会成为 active。如果索引期间 HEAD 或文件内容发生漂移，本次构建会被拒绝，上一份可用知识库不会被半成品覆盖。

### 如何控制 Agent 不受约束地探索？

Router 当前采用确定性规则，工具全部只读，执行层限制单次最多两个工具，现有规则通常只选择零个或一个工具。工具失败时返回 limitation，而不是无限重试或中断整个请求。

### 如何处理模型不可用？

Chat 与 Embedding 完全解耦。Embedding 失败时退化到 `lexical-only`；Chat 无 Key 或调用失败时返回规则型回答，而不是让检索和桌面应用整体失效。

### 如何保证答案可解释？

系统保存检索模式、Evidence 选择、预算、路由原因、工具状态、耗时、引用和回答模式，桌面端可以通过 Trace 回看回答链路。

> **一句话面试口径：** RepoMind 的核心不是简单调用大模型，而是用不可变 Git Snapshot 保证知识版本一致性，用结构化 RAG 提供可定位证据，再用有预算、有上限、可审计的轻量 Agent 调度处理复杂仓库问题。

## 当前限制

| 限制 | 当前状态 |
| --- | --- |
| 平台 | 仅正式支持和验证 Windows 10/11 x64 |
| 远程仓库 | 仅支持无需认证的公开 GitHub 仓库 |
| Embedding | 默认关闭，未配置时使用 `lexical-only` |
| 代码关系 | 来自静态分析，不等同于运行时调用图 |
| 动态调用 | 反射、运行时注入和跨语言调用可能缺失 |
| 结构扩展 | 当前检索只沿已观察静态关系扩展一跳 |
| Security Tool | 只提供规则型静态线索，不构成完整安全审计 |
| Agent 自主性 | 确定性、有硬上限的调度，不是自治多 Agent 群 |
| 检索评测 | 尚无大型真实仓库 Recall@K、MRR 和引用准确率基准 |
| 性能评测 | 尚无大型仓库 ingest、P50/P95 延迟和磁盘占用基准 |
| CI | 工作流已配置，远端运行状态尚未确认 |
| 发布可信度 | 尚无正式应用图标和 Windows 代码签名证书 |
| 完整 E2E | 冻结应用的 register → ingest → search → ask → trace 尚未自动化验证 |

## 深入文档

- [开发与验证报告](docs/后续开发指导/DEVELOPMENT_REPORT.md)：M0–M5 状态、本地测试、Windows 构建、Smoke 和验收矩阵；
- [RAG 与 Agentic AI 设计](docs/后续开发指导/RAG_VS_AGENTIC.md)：为什么采用检索底座与条件式 Agent 调度；
- [架构与后续路线图](docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md)：当前架构边界和后续演进方向；
- [GitHub 上传说明](docs/后续开发指导/GITHUB_UPLOAD_GUIDE.md)：源码、文档、本地产物和敏感信息的上传边界。

## 说明

- 项目当前没有正式 LICENSE 文件，因此暂不声明开源许可证；
- 本地构建可能使用 Electron 默认图标，并显示 Windows 未知发布者提示；
- GitHub Actions 的真实结果以远端 Actions 页面为准；
- Release 二进制通过 GitHub Release 发布，不进入源码 Git 历史。
