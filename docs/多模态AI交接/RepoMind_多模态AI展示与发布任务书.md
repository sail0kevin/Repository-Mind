# RepoMind 多模态 AI 展示与发布任务书

> 本文是交给下一位多模态 AI 的主任务书。执行者应先理解项目、检查当前工作区，再继续完成真实截图、演示、导出、README、安全文档和发布准备。不要从头重做已经完成的 M0–M5，也不要把 Legacy 多角色包装成当前核心架构。

## 1. 任务目标

把 RepoMind 从“技术核心已经实现的本地仓库智能助手”完善为“面试官能在三分钟内理解、无需 API Key 就能体验、能看到真实证据和产物、可以从 GitHub 下载”的求职展示项目。

最终公开展示必须回答：

1. 项目解决什么问题？
2. 软件能否真实运行？
3. AI Agent、RAG、Snapshot、Evidence 和 Trace 是否真实实现？
4. 面试官不配置模型时能看到什么？
5. 回答能否回溯到 commit、文件路径和源码行？
6. 工程测试、CI、安全和 Windows 发布是否可信？
7. 项目当前有哪些诚实限制？

## 2. 项目位置与技术定位

项目根目录：

```text
<repository-root>
```

RepoMind 是一个面向 Windows 的本地 Git 仓库知识助手。它将指定 Git commit 构建为不可变 Repository Snapshot，再通过结构化解析、本地检索、Evidence Bundle 和受约束的 Main Agent，帮助用户理解陌生仓库。

核心产物包括：

- Repository Snapshot；
- Repository Catalog；
- 文件、Symbol、Relation、Parser Diagnostic；
- FTS5/BM25 和可选 Embedding 检索；
- Evidence Bundle；
- 带 commit/path/line 引用的回答；
- Main Agent 路由和 Specialist Tool Trace；
- 仓库工作流分析和代码图谱查询。

它不是：

- 自动编程或自动提交 PR 的工具；
- 执行目标仓库代码的沙箱；
- 固定启动多个角色讨论的“多 Agent 聊天室”；
- 云端分布式代码平台；
- 完整运行时调用图或完整安全审计产品。

当前 Main Agent 采用确定性路由。普通局部解释可以直接回答；概览、依赖影响、测试、安全或语言结构问题才按需调用只读 Specialist Tool。执行层最多允许两个工具，现有互斥规则通常选择零个或一个，不存在无限自主循环。

## 3. 必须遵守的安全和产品边界

1. 目标仓库只读：不执行、不安装依赖、不修改、不提交、不推送。
2. 所有运行验证使用临时数据库和临时 Git 仓库；不得使用真实用户数据库。
3. Chat 与 Embedding 配置和密钥相互独立。
4. 没有 Key 时必须保留 Snapshot、Catalog、FTS5/BM25、规则回答和确定性工具。
5. Embedding 关闭或失败必须明确显示 `lexical-only`，不能伪装为语义检索。
6. 不在日志、截图、示例 JSON 或 Markdown 中暴露 API Key、用户私有路径和私有源码。
7. 不提交数据库、EXE、安装包、`node_modules`、构建目录、日志和缓存。
8. 不执行 `git clean -fd(x)`、`git reset --hard` 或宽泛的 `git add .`。
9. 不自动 commit、push、tag、创建 Release 或替换远端 main；所有远端行为必须获得用户明确批准。
10. 保留 Electron 身份：
    - package：`repomind-desktop`
    - appId：`com.repomind.app`
    - productName：`RepoMind`
    - 默认 userData：`%APPDATA%\repomind-desktop`
11. 保留 `/api/v1` 兼容和 Legacy `/collaborate` 兼容；Legacy 只是高级/已弃用入口。
12. 写代码时使用与项目一致、初学者能看懂的中文注释。

## 4. 先阅读哪些文档

按以下顺序阅读，不要只看 README 就开始改代码。

### 4.1 首页与产品定位

```text
README.md
```

当前 README 详细但较长，技术内容可信。后续要把它重构成面试官三分钟可读的中英双语首页，详细内容下沉到 docs。

### 4.2 当前真实实现与验收记录

```text
docs/后续开发指导/DEVELOPMENT_REPORT.md
```

阅读重点：M0–M5、测试结果、Snapshot、Parser、检索、Main Agent、Electron、Windows 构建和当前限制。

### 4.3 架构与术语

```text
docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md
docs/后续开发指导/RAG_VS_AGENTIC.md
```

必须理解：RepoMind 是“增强型 RAG 知识底座 + 轻量、受约束 Agent 调度”，而不是 RAG 与 Agent 二选一。

### 4.4 GitHub 上传边界

```text
docs/后续开发指导/GITHUB_UPLOAD_GUIDE.md
```

此文档定义哪些源码和文档可上传，哪些本地数据、历史资料、密钥和构建产物禁止上传。

### 4.5 代码入口

```text
backend/service/main.py
backend/service/api/v1/repos.py
backend/service/core/ingest_service.py
backend/service/core/parsing/
backend/service/core/retrieval/
backend/service/core/agent/main_agent.py
backend/service/storage/migrations/
desktop/app/electron/main.ts
desktop/app/electron/preload.ts
desktop/app/renderer/services/apiClient.ts
desktop/app/renderer/src/main.tsx
```

## 5. 当前已完成的工作

### 5.1 M0–M5 技术核心

已经实现：

- Schema 7 版本化迁移、备份和完整性保护；
- commit 级不可变 Snapshot；
- Python AST、JS/TS tree-sitter、Markdown、JSON/YAML/TOML 和 fallback ParserAdapter；
- Evidence、Symbol、Relation、Diagnostic；
- SQLite FTS5/BM25、可选 Embedding、RRF、结构扩展和 Token 预算；
- Repository Catalog；
- 确定性 Main Agent 和五类只读 Specialist Tool；
- Agent Trace；
- 无 Key 规则回答；
- Electron + React + TypeScript 桌面工作区；
- PyInstaller、Electron Builder、NSIS、Portable；
- Windows CI 和 Release workflow。

历史验证基线：

```text
后端：87 passed（后续新增测试后数量可能增加）
桌面端旧基线：22 passed
当前桌面端：24 passed
Renderer production build：通过
Electron TypeScript build：通过
Schema：7
冻结后端 smoke：通过
```

### 5.2 桌面端“无法连接后端”已经修复

根因：Renderer 给 GET 添加 JSON Content-Type，引发 CORS 预检；手写 OPTIONS 中间件返回裸 200；Vite Origin 也未精确加入白名单。

已经修改：

```text
backend/service/main.py
backend/service/config/settings.py
desktop/app/renderer/services/apiClient.ts
backend/tests/test_m0_contract.py
desktop/app/renderer/services/apiClient.test.ts
```

真实 Electron 日志已经从重复失败 OPTIONS 变为成功的：

```text
GET /api/v1/health 200
GET /api/v1/settings 200
GET /api/v1/repos?limit=100 200
```

### 5.3 已增加隔离 userData

`desktop/app/electron/main.ts` 支持：

```text
REPOMIND_USER_DATA_PATH=<临时目录>
```

未设置时仍保持 `%APPDATA%\repomind-desktop`。所有自动化和截图演示应显式使用临时路径。

### 5.4 已增加一键内置 Demo

演示语料：

```text
demo/repomind-demo/
```

桌面端已有“打开内置 Demo”按钮。它会：

1. 把合成语料复制到当前 userData；
2. 仅在运行副本中初始化 Git；
3. 使用固定作者、固定时间创建 commit；
4. 注册并 ingest；
5. 加载 succeeded Snapshot、Catalog、摘要和文件；
6. 提供三个推荐问题。

已真实验证的固定 commit：

```text
e718d4a31f9df9d74b8b74fe5f5e49b92625862b
```

真实结果：

```text
main 分支
10 个文件
150 个 Evidence/知识片段
Snapshot succeeded 且 active
Catalog 正常生成
无网络、无 Chat Key、无 Embedding Key
```

### 5.5 已修复 Demo 暴露的 Markdown Evidence 缺陷

同一 Markdown 章节多个 paragraph 之前共享 logical ID，导致唯一约束和关系外键错误。现已让 paragraph identity 包含父 Evidence logical ID 和 part，并增加回归测试：

```text
backend/service/core/parsing/markdown_adapter.py
backend/tests/test_m2_stage2.py
```

### 5.6 已修复 Code Graph Snapshot 一致性

Renderer 的 stats、important、search、call-chain 和 class 查询现在都传递当前 `snapshot_id`，并通过 request generation 丢弃切换仓库/快照前返回的旧响应。

## 6. 当前工作区状态（开始前必须重新确认）

本文编写时改动尚未提交，包含 CORS、Demo、Markdown identity、Code Graph 和文档改动。执行者先运行：

```bash
git status --short
git diff --stat
git diff --check
```

不要覆盖、回退或遗漏这些修改。重点预期文件：

```text
backend/service/config/settings.py
backend/service/core/parsing/markdown_adapter.py
backend/service/main.py
backend/tests/test_m0_contract.py
backend/tests/test_m2_stage2.py
desktop/app/electron-builder.yml
desktop/app/electron/main.ts
desktop/app/electron/preload.ts
desktop/app/renderer/services/apiClient.ts
desktop/app/renderer/services/apiClient.test.ts
desktop/app/renderer/src/main.tsx
desktop/app/renderer/src/features/repositories/RepositoryAccessPanel.tsx
docs/后续开发指导/DEVELOPMENT_REPORT.md
demo/repomind-demo/
```

本地存在一张验证截图：

```text
demo-verification.png
```

它是真实 Electron 截图，但在正式采用前必须由多模态 AI 查看画面、检查乱码、路径和隐私，再决定裁剪、重拍或删除。不要未经检查直接上传。

## 7. 下一位多模态 AI 要完成的事项

以下按优先级执行。不要先增加新 Agent、Provider 或复杂编排。

### P0：完整真实验收当前 Demo

使用临时 `REPOMIND_USER_DATA_PATH`，确保 Chat/Embedding Key 为空，启动修改后的真实 Electron。

必须通过界面完成：

1. 点击“打开内置 Demo”；
2. 等待 ingest 100%；
3. 确认 Snapshot succeeded、commit 正确；
4. 查看 Catalog；
5. 查看 `repomind_demo/app/main.py` 和源码行；
6. 执行局部解释问题：
   ```text
   GreetingService.build_message 方法是做什么的？
   ```
   验证 0 个 Specialist Tool；
7. 执行安全问题：
   ```text
   这个仓库有哪些安全风险线索？
   ```
   验证只选择 `security_review`；
8. 执行影响问题：
   ```text
   修改 GreetingService.build_message 可能影响哪些调用方和测试？
   ```
   验证只选择 `dependency_impact`；
9. 每个问题打开 Evidence；
10. 打开 Agent Trace；
11. 不存在 Trace ID 返回 HTTP 404；
12. 重复点击 Demo 不创建重复仓库或损坏 Snapshot；
13. 退出后 Electron、后端和 Vite 进程清理，无数据库/EXE 文件锁。

当前已经验证概览问题，结果为：

```text
mode: repository_navigation
tool: repository_navigator
status: fallback
generation_mode: rule_fallback
retrieval: lexical
Trace: 200
```

概览问题调用 Repository Navigator 是合理行为，不能拿它作为“普通问题 0 工具”的测试题。

### P0：修复真实展示中发现的问题

已观察到 Trace 的部分 lexical `evidence_refs` 中 `file_path` 为 `null`，规则回答因此出现空引用：

```text
[1] :
[2] :
```

必须定位检索结果到 Evidence/Chunk API 的字段映射，修复为真实文件路径和行号。要求：

- 回答引用显示 `path:start-end`；
- Trace retrieval evidence_refs 也有路径；
- 历史 Snapshot 读取持久化 Evidence，不读取当前工作树冒充历史证据；
- 增加回归测试；
- 重新通过真实 UI 查看 Evidence Drawer。

### P1：增加 Markdown 与 JSON 导出

优先于 Word/PDF。

Markdown：复用后端已有 `WorkflowReportResponse.markdown`，不要再写一套报告生成器。

JSON：用于导出 Snapshot、Catalog、Evidence、Trace 的机器可读摘要。

实现要求：

- Renderer 只有“导出”操作，不获得通用文件系统权限；
- preload 暴露最小 IPC；
- Electron 使用 `showSaveDialog`；
- 用户明确选择保存路径后才写文件；
- UTF-8；
- Windows 文件名清理；
- 取消保存不报错；
- 文件包含 repo alias、commit、snapshot ID、生成时间、检索模式、Evidence path/line、tool route 和 limitations；
- 不含完整 Key、临时 userData 或隐私路径。

建议按钮：

```text
导出 Markdown
导出 Trace JSON
```

### P1：生成可公开示例产物

基于内置 Demo 真实运行，放入：

```text
examples/outputs/
```

至少包括：

```text
repomind-demo-report.md
repomind-demo-trace.json
```

人工检查：

- commit 与 Snapshot 正确；
- file:line 引用可读；
- 无真实密钥和个人路径；
- 清楚标明无 Key、lexical、rule fallback；
- 安全结果标明“静态规则线索，不构成完整审计”；
- Trace JSON 可读且不过度庞大。

### P1：多模态视觉检查与正式截图

多模态 AI 必须实际看图，而不是只根据 DOM 或日志宣称界面好看。

使用真实 Electron + 内置 Demo 拍摄 3–5 张截图：

1. 一键 Demo 入口；
2. succeeded Snapshot + Catalog；
3. 局部解释回答 + Evidence；
4. 安全或影响问题 + Specialist Tool Trace；
5. 导出成功状态。

要求：

- 1280×800 或更高；
- 中文没有乱码、截断、重叠；
- 不出现个人路径、API Key、临时目录、用户数据库位置；
- 不把 Legacy 多角色放在主要视觉中心；
- 截图来自真实运行，不用设计稿；
- 适当裁剪但不得篡改产品结果；
- 保存到 `docs/assets/` 或类似公开媒体目录。

同时录制 45–90 秒 GIF 或视频：

```text
打开 RepoMind → 点击 Demo → ingest → Catalog → 提问 → Evidence → Trace → 导出
```

如果 GIF 过大，README 使用压缩 GIF 或 MP4/外部视频链接，不提交超大二进制。

### P1：重构 README

目标：面试官三分钟读懂，细节链接到 docs。

建议结构：

1. 双语 Hero（中文 + 简洁英文）；
2. 一句话解决的问题；
3. 真实 GIF/视频；
4. 三步内置 Demo；
5. 四个核心证明：
   - immutable commit Snapshot；
   - structured Evidence/Catalog；
   - hybrid retrieval + no-key fallback；
   - bounded Main Agent + Trace；
6. 一张准确架构图；
7. 三种示例问题与实际 Agent 路由；
8. 真实截图；
9. 测试/CI/构建状态；
10. Windows 安装与源码快速启动；
11. 只读和密钥安全边界；
12. 个人技术贡献；
13. 诚实限制；
14. docs 链接。

不要在 README 中声称：

- GitHub Actions 已通过（除非远端真实通过）；
- Release 已发布（除非真实发布）；
- Windows 已签名（当前没有证书）；
- 所有普通问题均为 0 工具；
- 安全工具等于完整审计；
- 静态关系等于运行时调用图；
- 支持私有 GitHub 仓库；
- 已完成大型仓库基准。

详细技术表、M0–M5 历史和长篇面试口径继续留在 docs，不全部堆在首页。

### P1：新增 SECURITY.md

内容必须包括：

- 当前支持版本；
- 私下报告漏洞的联系方式占位/用户确认项；
- 目标仓库只读、不执行；
- SQLite、克隆仓库、日志的数据位置和风险；
- DPAPI SecretStore；
- Chat/Embedding Key 分离；
- 设置 API 不返回完整 Key；
- 自定义 OpenAI-compatible Provider URL 的 SSRF/泄露风险控制说明；
- 不在 Issue 中粘贴真实密钥或私有源码；
- 凭据泄露后的轮换；
- Release SHA-256 验证。

LICENSE 不能由 AI 擅自决定。需要用户选择后再添加。

### P2：Windows Electron E2E 和 CI

增加可重复的真实 E2E：

```text
launch → open demo → ingest → catalog → ask 3 questions → evidence → trace → export → exit
```

要求：

- 临时 userData；
- 临时 SQLite；
- 空 Key；
- 不联网；
- finally 清理进程树和文件锁；
- 失败上传脱敏截图、renderer console 和 backend log；
- 不上传 SQLite；
- 不断言整段自然语言，断言结构化路由、Evidence path/line、Snapshot、Trace 和导出字段。

扩展现有：

```text
.github/workflows/ci-windows.yml
```

不要创建重复 CI。远端运行后再更新 README 徽章和状态。

### P2：发布准备

远端 CI 通过后，准备 `v0.1.0`：

- NSIS Setup；
- Portable；
- SHA256SUMS；
- Release notes；
- 安装步骤；
- 内置 Demo 使用步骤；
- Windows-only、未签名、无正式证书等已知限制。

没有用户明确批准时，不 push、不 tag、不发布 Release。

## 8. 推荐验证命令

以下均从项目对应目录执行，注意不要从用户主目录运行 pytest。

### 后端

```bash
cd backend
python -m pytest -q
```

### 桌面端

```bash
npm --prefix desktop/app test
npm --prefix desktop/app run build
```

### Demo 自身

```bash
cd demo/repomind-demo
python -m unittest discover -s tests -v
```

### Git 边界

```bash
git status --short
git diff --check
git diff --stat
git ls-files -- data backend-dist backend-build desktop/app/release desktop/app/node_modules docs/旧的文件 .claude
```

### 真实运行

使用唯一临时目录设置：

```text
REPOMIND_USER_DATA_PATH=<TEMP>
REPOMIND_CHAT__API_KEY=
REPOMIND_EMBEDDING__API_KEY=
```

开发模式应启动修改后的 Python 后端；不要误用旧 `backend-dist/repomind-backend.exe` 验证新源码。必要时临时移开该 EXE，验证结束后原样恢复。

## 9. 验收清单

最终交付前逐项勾选：

- [ ] 桌面启动无“无法连接后端”；
- [ ] Demo 一键打开，无网络、无 Key；
- [ ] 重复打开 Demo 幂等；
- [ ] Snapshot succeeded 且 commit 固定；
- [ ] Catalog、文件、源码行可浏览；
- [ ] 局部解释问题 0 工具；
- [ ] 安全问题只调用 Security Review；
- [ ] 影响问题只调用 Dependency Impact；
- [ ] 无 Key 返回 rule fallback，不是 500；
- [ ] Evidence 和 Trace 都有 path/line；
- [ ] 不存在 Trace 返回 404；
- [ ] Markdown/JSON 可真实导出；
- [ ] 示例输出无个人路径和密钥；
- [ ] 3–5 张真实截图通过视觉检查；
- [ ] 演示视频/GIF 清晰且不泄露隐私；
- [ ] README 中英双语、三分钟可读；
- [ ] SECURITY.md 完成；
- [ ] 后端和桌面测试通过；
- [ ] Renderer/Electron build 通过；
- [ ] Windows E2E 通过；
- [ ] 远端 CI 真实通过后再更新声明；
- [ ] Release 只在用户批准后发布；
- [ ] Git 中没有数据库、EXE、安装包、密钥、日志和本地历史资料。

## 10. 给多模态 AI 的可直接复制指令

```text
你现在负责继续完善 RepoMind 求职展示和公开发布准备。

项目路径：
<repository-root>

首先完整阅读：
1. docs/多模态AI交接/RepoMind_多模态AI展示与发布任务书.md
2. README.md
3. docs/后续开发指导/DEVELOPMENT_REPORT.md
4. docs/后续开发指导/ARCHITECTURE_FUTURE_ROADMAP.md
5. docs/后续开发指导/RAG_VS_AGENTIC.md
6. docs/后续开发指导/GITHUB_UPLOAD_GUIDE.md

开始前检查 git status 和 diff。当前工作区包含尚未提交的桌面连接修复、一键内置 Demo、Markdown Evidence identity 修复和 Code Graph Snapshot 一致性改动，禁止 reset、clean 或覆盖。

产品核心是：commit 级不可变 Snapshot + 结构化 Evidence/Catalog + FTS5/BM25/可选 Embedding + 受约束 Main Agent + commit/path/line 引用 + Agent Trace。Legacy 多角色不是主流程。

按任务书中的 P0 → P1 → P2 执行。先完成真实 Demo 三类问答验收和 Evidence file_path/line 修复，再做 Markdown/JSON 导出、真实截图/GIF、双语 README、SECURITY.md、Windows E2E 和 CI。不要先增加新 Agent 或模型 Provider。

所有运行使用临时 REPOMIND_USER_DATA_PATH、临时数据库、空 Chat/Embedding Key；不执行或修改目标仓库；不读取真实用户数据库。截图必须亲自查看，确认没有乱码、个人路径、密钥和隐私信息。

不要自动 commit、push、tag、发布 Release 或 force push。完成每一阶段后，报告修改文件、真实运行观察、测试结果、尚存风险和下一步。测试失败时如实报告，不能宣称完成。
```

## 11. 完成后的报告格式

下一位 AI 每完成一个阶段，输出：

```markdown
## 阶段名称

### 完成内容
- ...

### 修改文件
- path:line — 目的

### 真实运行观察
- 操作：...
- 结果：...
- 截图：...

### 自动化验证
- 命令：...
- 结果：...

### 未完成/风险
- ...

### 下一步
- ...
```

不要只说“测试通过”或“应该可以”。必须区分：代码实现、自动化回归、真实 UI 运行、远端 CI 和公开发布这五种不同状态。
