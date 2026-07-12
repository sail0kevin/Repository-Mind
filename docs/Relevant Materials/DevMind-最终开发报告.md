# DevMind 最终开发报告

## 1. 项目最终定位

一句话版本：

**DevMind 是一个面向公开 Python GitHub 仓库的垂直代码分析 Agent 原型，输入仓库 URL，输出带证据的结构化分析报告。**

一段话版本：

这个项目不是做通用 AI 平台，也不是做一个什么都接的聊天机器人，而是围绕“代码仓库理解”这个单一场景做深。第一阶段只支持公开 Python 仓库，只做 2 个分析 Agent 和 1 个 Summary Agent，重点展示你在代码领域的工具定制能力、RAG 设计能力、多 Agent 协作编排能力，以及对上下文成本和可验证性的控制。最终交付物应当是一个可运行 Demo：用户输入 GitHub 仓库 URL，系统完成仓库拉取、文件过滤、代码切块、检索增强、工具调用和多 Agent 分析，输出一份结构化评审报告。

---

## 2. MVP 功能范围

### 必做范围

1. 输入公开 GitHub Python 仓库 URL。
2. 后端自动 clone 仓库到本地工作目录。
3. 扫描仓库文件，过滤无关目录和非重点文件。
4. 对 Python 代码和 README 做切块。
5. 建立本地向量索引和基础元数据索引。
6. 提供 Architecture Agent 分析能力。
7. 提供 Security Agent 分析能力。
8. 提供 Summary Agent 汇总能力。
9. 输出结构化 Markdown / JSON 报告。
10. 前端提供一个最小可演示页面：输入 URL、查看任务进度、查看报告。

### 可选增强，但不阻塞 MVP

1. 增量重建索引。
2. Human-in-the-loop 追问机制。
3. 仓库分析历史记录。
4. 关键词检索 + 向量检索混合召回。
5. 简单依赖图可视化。

### 第一阶段明确不做

1. 多语言支持。
2. 用户体系、登录、权限。
3. 私有仓库 OAuth 接入。
4. 在线协作平台化能力。
5. 自动修复代码、自动提 PR。
6. 完整企业级安全审计。
7. 泛化聊天式问答产品。

---

## 3. 系统整体流程图（文字版）

```text
用户输入 GitHub URL
  -> Repo Intake 模块校验 URL
  -> Git Clone 工具拉取仓库到本地
  -> File Scanner 扫描目录
  -> File Filter 过滤非目标文件
  -> Parser/Chunker 解析 README、Python 源码并切块
  -> Index Builder 生成:
       - metadata index
       - vector index
       - repo map
  -> Task Orchestrator 发起多 Agent 工作流
       - Architecture Agent
       - Security Agent
  -> Summary Agent 汇总两类发现
  -> Report Builder 生成结构化报告
  -> 前端展示报告、证据、摘要和关键风险
```

如果加入 Human-in-the-loop，则流程扩展为：

```text
Agent 分析时发现意图不明确
  -> 触发 clarification question
  -> 用户补充背景
  -> Agent 继续分析并刷新报告
```

---

## 4. 每个 Agent 的职责边界

### 4.1 Architecture Agent

职责：

1. 识别项目入口文件。
2. 分析目录结构和模块分层。
3. 总结核心组件、模块职责和调用关系。
4. 识别依赖管理方式，如 `requirements.txt`、`pyproject.toml`。
5. 提取运行方式、配置方式、主要技术栈。

不负责：

1. 深入做安全漏洞判断。
2. 输出最终用户报告。
3. 扫描所有细粒度代码问题。

输出：

1. 项目架构摘要。
2. 模块关系说明。
3. 入口与启动路径。
4. 核心文件证据列表。

### 4.2 Security Agent

职责：

1. 检查硬编码密钥、Token、密码。
2. 检查危险调用，如 `eval`、`exec`、`pickle.loads`、`subprocess(shell=True)`。
3. 检查潜在反序列化风险、命令执行风险、路径遍历风险。
4. 检查依赖清单中明显过旧或高风险模式。
5. 输出基于规则和证据的风险发现。

不负责：

1. 理解整个系统架构全貌。
2. 做 SAST 级别全覆盖。
3. 给出修复代码 patch。

输出：

1. 风险项列表。
2. 风险等级。
3. 触发规则。
4. 对应文件和代码证据。

### 4.3 Summary Agent

职责：

1. 汇总 Architecture Agent 和 Security Agent 的结果。
2. 去重、归并、重排发现。
3. 按固定报告模板输出最终结果。
4. 标注高置信和低置信结论。

不负责：

1. 直接扫描原始仓库全量代码。
2. 替代前两个 Agent 做独立深分析。

输出：

1. 最终结构化报告。
2. 项目概览。
3. 架构结论。
4. 安全发现。
5. 后续建议。

---

## 5. 每个 Agent 读什么上下文，不读什么上下文

这是项目成败的关键，不然很容易变成“把全仓库塞给模型”。

### Architecture Agent 读取上下文

应读取：

1. `README.md`
2. 仓库目录树摘要
3. `requirements.txt` / `pyproject.toml` / `setup.py`
4. 被识别为入口的 Python 文件
5. 核心模块的 chunk 摘要
6. AST 提取出的 symbol 信息

不应读取：

1. 全量测试文件内容
2. 全部长代码文件原文
3. 大量无关文档
4. 静态资源、图片、构建产物

### Security Agent 读取上下文

应读取：

1. Python 源码 chunk
2. 规则命中的可疑代码片段
3. 配置文件和环境变量模板文件
4. 依赖声明文件

不应读取：

1. 完整 README 作为主上下文
2. 架构摘要全文
3. 无命中的大段普通业务代码

### Summary Agent 读取上下文

应读取：

1. Architecture Agent 的结构化输出
2. Security Agent 的结构化输出
3. 少量顶层 Repo 概览元数据

不应读取：

1. 原始全量 chunk
2. 全部检索证据原文
3. 全仓库目录树细节

### 上下文控制原则

1. Agent 只读自己需要的上下文。
2. 先读摘要，再按需读证据。
3. Summary Agent 不重新读仓库。
4. 模型上下文预算固定，不做无限扩展。

---

## 6. 工具层应该有哪些最小工具

第一阶段工具不要多，但要“真能支撑工作流”。

### 必要工具 1：GitHub Clone Tool

作用：

1. 校验 GitHub URL。
2. clone 仓库到本地临时目录或缓存目录。
3. 返回本地路径、默认分支、commit hash。

实现建议：

- 直接使用系统 `git clone --depth 1`。

### 必要工具 2：Repo Scan Tool

作用：

1. 扫描文件树。
2. 过滤 `.git`、`venv`、`__pycache__`、`build`、`dist` 等目录。
3. 仅保留 Python、Markdown、配置文件。

### 必要工具 3：Python AST Parse Tool

作用：

1. 解析 `.py` 文件。
2. 提取函数、类、import、docstring。
3. 识别入口模式，如 `if __name__ == "__main__":`。

实现建议：

- 使用 Python 标准库 `ast`，这是这个项目最应该体现的“代码领域定制工具”。

### 必要工具 4：Chunking Tool

作用：

1. 按函数、类、模块、README 标题切块。
2. 给每个 chunk 绑定文件路径、行号、symbol 名称。

### 必要工具 5：Vector Retrieval Tool

作用：

1. 将 chunk 嵌入并写入向量库。
2. 支持基于任务的 Top-K 检索。

### 必要工具 6：Security Rule Tool

作用：

1. 使用规则库扫描 Python 源码。
2. 返回风险类型、命中位置、风险说明。

第一阶段规则即可写死在本地，例如：

1. `eval(`
2. `exec(`
3. `pickle.loads(`
4. `yaml.load(` 未指定安全 loader
5. `subprocess.*shell=True`
6. 疑似密钥正则

### 必要工具 7：Report Builder Tool

作用：

1. 将 Agent 输出组装成固定结构的 JSON。
2. 再渲染为 Markdown 报告。

---

## 7. 数据流设计

建议采用“离线预处理 + 在线分析编排”两段式。

### 7.1 输入阶段

输入：

- `repo_url`

输出：

- `repo_id`
- `local_repo_path`
- `commit_hash`

### 7.2 预处理阶段

1. 扫描文件树。
2. 过滤文件。
3. 解析 Python AST。
4. 生成 chunk。
5. 生成 repo map。
6. 写入 metadata store。
7. 写入 vector store。

产物：

1. `repo_manifest.json`
2. `chunks.jsonl`
3. `symbols.json`
4. `repo_map.json`
5. `vector index`

### 7.3 分析阶段

1. Orchestrator 读取 `repo_map` 和任务配置。
2. 为 Architecture Agent 检索架构相关上下文。
3. 为 Security Agent 检索安全相关上下文。
4. 两个 Agent 输出结构化结果。
5. Summary Agent 汇总结果。

### 7.4 输出阶段

1. 结构化 JSON 报告。
2. 可展示 Markdown 报告。
3. 前端展示摘要卡片、发现列表、证据片段。

### 最小存储设计

建议拆成三层：

1. `workspace/repos/`：克隆的仓库。
2. `workspace/artifacts/`：解析和切块产物。
3. `workspace/reports/`：最终报告。

---

## 8. 报告结构设计

这个报告就是你的演示成果，必须结构稳定、像一个“产品输出”，而不是一段散乱文本。

### 建议 Markdown 报告结构

```text
# DevMind Repository Analysis Report

## 1. Repository Overview
- Repo URL
- Commit
- Primary Language
- Estimated Project Type

## 2. Executive Summary
- 一句话总结
- 架构判断
- 主要风险判断

## 3. Architecture Analysis
- 项目入口
- 目录结构
- 核心模块
- 依赖与配置
- 架构特点

## 4. Security Analysis
- 风险摘要
- 逐项风险
  - title
  - severity
  - file
  - evidence
  - rationale

## 5. Key Evidence
- 关键文件
- 关键代码片段

## 6. Suggested Next Steps
- 优先阅读路径
- 优先修复建议

## 7. Limitations
- 分析边界
- 低置信项说明
```

### 建议 JSON 报告结构

```json
{
  "repo": {
    "url": "...",
    "commit": "...",
    "language": "Python"
  },
  "overview": {
    "summary": "...",
    "project_type": "..."
  },
  "architecture": {
    "entrypoints": [],
    "modules": [],
    "dependencies": [],
    "findings": []
  },
  "security": {
    "risk_count": 0,
    "findings": []
  },
  "evidence": [],
  "next_steps": [],
  "limitations": []
}
```

### 报告设计原则

1. 先结论，后证据。
2. 每个发现都尽量绑定文件路径和行号。
3. 明确写出“不确定项”。
4. 固定模板，方便多仓库横向比较。

---

## 9. 技术栈建议

目标不是“最先进”，而是“4 到 6 周内稳定跑通”。

### 后端

推荐：

1. `Python 3.11`
2. `FastAPI`
3. `Pydantic`
4. `GitPython` 或直接调用 `git`

理由：

- Python 对 AST、RAG、规则扫描、脚本编排最顺手。
- FastAPI 足够轻，适合原型 API 和后续 Demo。

### 检索与索引

推荐：

1. `Chroma` 或 `FAISS` 作为向量库
2. `sentence-transformers` 作为本地 embedding 方案
3. 可选 `rank_bm25` 做简单关键词补充

建议取舍：

- 为了降低复杂度，第一版可以先用 `Chroma + sentence-transformers`。
- 如果本机资源吃紧，可先把向量检索做轻，再加 BM25。

### Agent 编排

推荐：

1. 先自写一个轻量 orchestrator，不要先引入重框架。
2. 用清晰的任务对象串联 Agent 输入输出。

理由：

- 这个项目想展示的是你对 Agent workflow 的掌控，不是“会调某个框架 API”。

### 前端

推荐两种路线，二选一：

1. `Next.js` 或 `Vite + React` 做一个极简 Web Demo。
2. 如果你已有这个项目基础是桌面端，也可以继续保留前端壳，但页面一定要收缩。

第一阶段建议：

- **优先 Web Demo，而不是重桌面应用。**

原因：

1. 开发更快。
2. 演示更方便。
3. 面试官打开链接或本地页面更直接。

### 存储

推荐：

1. `SQLite` 保存任务、仓库记录、报告元数据。
2. 本地文件系统保存 artifacts 和报告。

---

## 10. 推荐的项目目录结构

```text
devmind/
  app/
    api/
      routes/
        analyze.py
        report.py
        health.py
    core/
      config.py
      logging.py
    agents/
      architecture_agent.py
      security_agent.py
      summary_agent.py
      orchestrator.py
    tools/
      git_tool.py
      repo_scan_tool.py
      ast_tool.py
      chunk_tool.py
      retrieval_tool.py
      security_rules_tool.py
      report_tool.py
    indexing/
      file_filter.py
      parser.py
      chunker.py
      embedder.py
      vector_store.py
      repo_map.py
    schemas/
      repo.py
      report.py
      agent.py
    services/
      analysis_service.py
      ingestion_service.py
      report_service.py
    storage/
      sqlite.py
      models.py
  frontend/
    src/
      pages/
      components/
      services/
  workspace/
    repos/
    artifacts/
    reports/
  scripts/
    run_backend.ps1
    run_frontend.ps1
    demo_analyze.ps1
  tests/
    test_ast_tool.py
    test_chunker.py
    test_security_rules.py
    test_orchestrator.py
  README.md
```

这个结构的重点是：

1. `agents/` 只管分析职责。
2. `tools/` 只管能力调用。
3. `indexing/` 只管预处理与检索。
4. `services/` 组织业务闭环。

---

## 11. 核心模块划分与职责

### `ingestion_service`

负责：

1. 仓库克隆。
2. 仓库目录准备。
3. 触发扫描、切块、索引构建。

### `file_filter`

负责：

1. 过滤目录。
2. 只保留 Python、Markdown、配置文件。

### `parser` + `ast_tool`

负责：

1. 解析 Python 结构。
2. 提取函数、类、导入、docstring、入口模式。

### `chunker`

负责：

1. 结构化切块。
2. 附带 symbol、文件路径、行号元信息。

### `vector_store` + `retrieval_tool`

负责：

1. 向量化。
2. Top-K 检索。
3. 后续可扩展混合检索。

### `security_rules_tool`

负责：

1. 本地规则扫描。
2. 风险分类。
3. 输出命中证据。

### `orchestrator`

负责：

1. 按顺序或并行触发 Agent。
2. 管理 Agent 输入输出。
3. 控制成本和上下文预算。

### `report_service`

负责：

1. 汇总 Agent 结果。
2. 生成 JSON 和 Markdown 报告。

---

## 12. 每一步应该先写什么后写什么

顺序必须服务于“最小闭环”，不要一开始写很重的前端和很抽象的 Agent 框架。

### 第一步：仓库拉取和文件扫描

先写：

1. `git_tool.py`
2. `repo_scan_tool.py`
3. `file_filter.py`

原因：

- 没有稳定输入，后面所有 Agent 都是空转。

### 第二步：Python AST 解析和切块

先写：

1. `ast_tool.py`
2. `parser.py`
3. `chunk_tool.py` / `chunker.py`

原因：

- 这是“代码领域定制能力”的核心展示点。

### 第三步：索引构建和检索

先写：

1. `embedder.py`
2. `vector_store.py`
3. `retrieval_tool.py`

原因：

- 没有检索，Agent 只能吃全量上下文，原型很快失控。

### 第四步：规则扫描工具

先写：

1. `security_rules_tool.py`

原因：

- Security Agent 最容易先用规则打底，快速产生可验证输出。

### 第五步：Agent 与编排器

先写：

1. `architecture_agent.py`
2. `security_agent.py`
3. `summary_agent.py`
4. `orchestrator.py`

原因：

- 前面的输入、检索、规则工具稳定之后，Agent 才有可靠燃料。

### 第六步：报告生成

先写：

1. `report_tool.py`
2. `report_service.py`

原因：

- 报告是你 Demo 的最终呈现层，应该建立在已有分析结果之上。

### 第七步：API 和前端

先写：

1. `POST /analyze`
2. `GET /report/{id}`
3. 一个输入 URL 和展示报告的页面

原因：

- 这一步只负责把闭环包装成可演示产品，不要反客为主。

---

## 13. 最小可运行版本需要哪些 API / 脚本 / 页面

### 最小 API

1. `POST /api/analyze`
   - 输入：`repo_url`
   - 输出：`task_id`

2. `GET /api/analyze/{task_id}`
   - 输出：任务状态、阶段进度

3. `GET /api/report/{task_id}`
   - 输出：结构化 JSON 报告

### 最小脚本

1. `scripts/run_backend.ps1`
2. `scripts/run_frontend.ps1`
3. `scripts/demo_analyze.ps1`

### 最小页面

1. 首页
   - 输入 GitHub URL
   - 点击开始分析

2. 结果页
   - 显示项目概览
   - 显示 Architecture Findings
   - 显示 Security Findings
   - 显示最终 Summary

如果你想再克制一点，甚至可以先不分页面，只做一个单页工作台。

---

## 14. 哪些地方可以先 mock，哪些地方必须真实实现

### 可以先 mock 的部分

1. 前端视觉样式。
2. Human-in-the-loop 问答流程。
3. 依赖漏洞数据库联动。
4. 仓库历史记录页。
5. 报告导出 PDF。

### 必须真实实现的部分

1. GitHub 仓库拉取。
2. 文件过滤。
3. Python AST 解析。
4. 代码切块。
5. 向量检索。
6. 至少一个真实工具调用链。
7. 多 Agent 编排。
8. 最终结构化报告输出。

原因很直接：这些就是面试官判断你是不是“真做了 Agent 原型”的硬证据。

---

## 15. 一个从 0 到可演示 Demo 的具体开发顺序

### 阶段 0：压缩边界，冻结 MVP

输出：

1. 只支持 Python。
2. 只支持公开仓库。
3. 只做 2+1 Agent。
4. 报告模板冻结。

原因：

- 没有边界冻结，4 周项目一定会失控。

### 阶段 1：打通仓库输入链路

任务：

1. 实现 URL 校验。
2. clone 仓库。
3. 保存本地路径。

验收：

- 给一个仓库 URL，可以稳定拉到本地。

### 阶段 2：打通代码预处理链路

任务：

1. 扫描 Python/README/配置文件。
2. AST 解析。
3. 切块。
4. 生成 repo map。

验收：

- 能导出 `chunks.jsonl` 和 `repo_map.json`。

### 阶段 3：打通检索链路

任务：

1. embedding。
2. 向量入库。
3. query 检索。

验收：

- 输入“项目入口在哪里”这类问题，能返回相关 chunk。

### 阶段 4：打通 Agent 工作流

任务：

1. Architecture Agent 调用检索工具和 AST 信息。
2. Security Agent 调用规则工具和检索工具。
3. Summary Agent 汇总。

验收：

- 能输出三段独立结果，并合成一份报告。

### 阶段 5：打通前后端演示闭环

任务：

1. 后端提供分析 API。
2. 前端提供输入框、进度、报告展示。

验收：

- 一次完整演示 3 分钟内可跑通。

### 阶段 6：打磨可讲述性

任务：

1. 选 3 个公开 Python 仓库做 Demo 样例。
2. 保留分析产物截图。
3. 写 README、架构图、简历描述。

验收：

- 面试时可以稳定演示、稳定解释、稳定回答追问。

---

## 16. 4 周开发计划

### 第 1 周：仓库接入 + 预处理骨架

目标：把“输入仓库 URL -> 本地可扫描”的链路跑通。

任务：

1. 搭后端骨架和基础前端页面。
2. 实现 GitHub clone。
3. 实现文件扫描和过滤。
4. 定义数据模型和 workspace 目录。

周结果：

- 可以拉取仓库并列出目标文件。

### 第 2 周：AST + chunk + 向量索引

目标：把代码理解前处理链路跑通。

任务：

1. 实现 Python AST 工具。
2. 实现按函数 / 类 / README 标题切块。
3. 接入 embedding 和向量库。
4. 生成 repo map。

周结果：

- 可以对仓库产生检索基础设施。

### 第 3 周：双 Agent + Summary Agent

目标：把真正的 Agent 工作流跑通。

任务：

1. 实现 Architecture Agent。
2. 实现 Security Agent。
3. 实现 Summary Agent。
4. 打通 orchestrator。
5. 生成结构化 JSON / Markdown 报告。

周结果：

- 后端已经具备完整分析能力。

### 第 4 周：Demo 打磨 + 稳定性 + 面试材料

目标：从“能跑”变成“能展示”。

任务：

1. 做一个极简但完整的前端展示页。
2. 增加任务进度和错误提示。
3. 选择 3 个代表性仓库跑结果。
4. 修正明显误报。
5. 补 README 和项目说明。
6. 准备演示话术和技术亮点。

周结果：

- 有稳定 Demo，有截图，有报告样例，有讲法。

---

## 17. 面试时怎么讲这个项目

这里不要讲成“我做了一个 AI 平台”，那会显得空，也会被追着问平台细节。

### 一句话讲法

**我做了一个面向 GitHub Python 仓库的垂直 Agent 原型，能自动拉取公开仓库，做代码切块、RAG 检索和多 Agent 分析，最后输出结构化架构与安全报告。**

### 30 秒讲法

这个项目聚焦代码仓库理解，不做泛聊天。我把输入限制在公开 Python 仓库，围绕这个场景定制了 AST 解析、依赖分析、安全规则扫描和向量检索工具，再用 Architecture Agent、Security Agent 和 Summary Agent 组成一个最小协作流。核心不是把全仓库扔给大模型，而是先做 repo map 和结构化切块，再按任务检索上下文，最后产出带证据的报告。

### 1 分钟讲法

我想验证的不是“LLM 会不会总结代码”，而是“能不能把代码理解做成一个可运行的 Agent 工作流原型”。所以我把问题收得很窄：只分析公开 Python 仓库，只做架构分析和安全审查两类任务。实现上，我先 clone 仓库，过滤文件，基于 Python AST 提取函数、类、入口和 import，再按结构切块并做向量索引。Architecture Agent 关注目录、入口、模块和依赖；Security Agent 关注危险调用和硬编码风险；Summary Agent 只汇总前两者结果，不重复扫仓库。这样既能体现领域工具深度，也能控制上下文成本和输出可验证性。

### 面试官最可能追问的点

1. 为什么只支持 Python？
   - 回答：因为我要先证明工作流有效，Python 的 AST 和安全规则也更容易做出深度定制，能集中体现领域建模能力。

2. 为什么要多 Agent，而不是一个大 prompt？
   - 回答：因为架构分析和安全审查需要不同上下文和不同工具，拆开后更容易控制 prompt、检索和输出格式，Summary Agent 只做汇总，职责更清晰。

3. 你怎么控制大仓库成本？
   - 回答：靠文件过滤、结构化切块、repo map、按任务检索，而不是全量喂给模型。

4. 你的“领域定制”体现在哪？
   - 回答：Python AST、入口识别、依赖文件解析、安全规则库、报告模板和 Agent 提示词都是围绕代码仓库场景专门设计的。

5. 这个项目最有技术含量的部分是什么？
   - 回答：不是页面，而是代码预处理 + 检索上下文控制 + 多 Agent 编排这条链路。

---

## 18. 你这个项目在简历上的推荐写法

### 项目名

**DevMind · GitHub 仓库分析 Agent 原型**

### 简历描述版本

1. 设计并实现面向公开 Python GitHub 仓库的垂直分析 Agent 原型，支持输入仓库 URL 后自动完成仓库拉取、代码切块、向量检索与结构化报告生成。
2. 构建 2 个分析 Agent（Architecture / Security）和 1 个 Summary Agent 的协作工作流，结合 Python AST 解析、依赖分析与安全规则库，实现对仓库架构与潜在风险的分角色分析。
3. 通过 repo map、结构化 chunk 和按任务检索机制控制上下文成本，避免全仓库直接进入模型上下文，提升分析稳定性与可验证性。
4. 输出带文件路径与代码证据的 Markdown / JSON 报告，并完成最小 Demo 闭环，适用于技术展示与面试演示。

---

## 19. 最终落地建议

如果你只有 4 到 6 周，这个项目最重要的不是“功能数量”，而是下面四件事真的做实：

1. **真实仓库拉取**
2. **真实代码结构解析**
3. **真实检索驱动的 Agent 分析**
4. **真实结构化报告输出**

只要这四件事成立，这个项目就已经有足够强的面试说服力。反过来，如果一开始去做复杂前端、账号体系、多语言支持、在线平台包装，项目会很快变得热闹但空心。

这个版本最适合你的定位：一人可做、周期可控、技术点扎实、演示效果清楚。
