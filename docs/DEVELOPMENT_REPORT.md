# RepoMind / AgentFlow 开发报告

更新时间：2026-07-11

## 项目定位

RepoMind 是一个本地桌面版 GitHub / Git 仓库知识助手。目标是让用户不用终端，也能通过可视化界面完成：

1. 配置 OpenAI 兼容模型，例如 LongCat-2.0。
2. 添加公开 GitHub URL 或本地 Git 仓库路径。
3. 扫描、解析、索引仓库内容。
4. 基于证据向代码库提问。
5. 使用工作流视角理解项目结构。
6. 使用代码图谱查询函数、类和调用链。

项目边界仍然是只读分析工具，不执行被分析仓库代码，不自动修改仓库，不提交 PR。

## 当前已完成

### 后端能力

- FastAPI 后端入口已存在，统一挂载 `/api/v1`。
- 已有健康检查接口：`GET /api/v1/health`。
- 已有本地仓库注册接口：`POST /api/v1/repos`。
- 已有 GitHub URL 分析入口：`POST /api/v1/analysis/analyze`。
- 已有异步索引任务：`POST /api/v1/repos/{repo_id}/ingest`。
- 已有任务轮询：`GET /api/v1/jobs/{job_id}`。
- 已有仓库地图、摘要、搜索、问答接口。
- 已有设置接口：`GET/PUT /api/v1/settings`，可保存 API Key、Base URL、模型名、费用单价等。
- 已有多智能体协作接口：`POST /api/v1/collaborate`。
- 已有代码图谱接口：
  - `/code-graph/{repo_id}/stats`
  - `/code-graph/{repo_id}/important`
  - `/code-graph/{repo_id}/search`
  - `/code-graph/{repo_id}/call-chain`
  - `/code-graph/{repo_id}/class`

### 前端能力

- 前端已重写为中文三栏工作台：
  - 左侧：仓库接入、智能体配置，并支持拖动分隔条调整宽度（240–520 px，自动记住宽度）。
  - 中间：智能问答、协作辩论、工作流分析、代码图谱。
  - 右侧：Token / 费用估算、仓库概览、文件样例、证据流、系统日志。
- 设置弹窗已加入 LongCat-2.0 预设：
  - Base URL: `https://api.longcat.chat/openai/v1`
  - Model: `LongCat-2.0`
- GitHub URL 流程已改正：
  - GitHub URL 使用 `/analysis/analyze` 克隆并注册。
  - 本地路径使用 `/repos` 注册。
  - 注册完成后统一启动 `/ingest` 并轮询 job 进度。
- 使用指南已恢复为正常中文。
- 费用估算已明确为本地估算，不代表官方账单。

### 构建验证

已通过：

```bash
cd desktop/app
npm run build
```

已通过：

```bash
python -m compileall backend\service
```

说明：PowerShell 控制台可能把中文显示成乱码，但文件按 UTF-8 读取是正常中文。

## 发布与验收结果

### Windows 桌面交付物

已完成 Electron 目录包重新构建，并整体同步到：

```text
release-web-local/desktop-app/RepoMind.exe
```

关键修复：

- Vite 使用相对资源路径，解决 Electron `file://` 页面空白。
- 打包页的 `Origin: null` 已加入后端 CORS 白名单。
- 渲染器启动时主动请求 Electron 启动后端，并最多等待约 15 秒健康就绪，避免冷启动时误报“无法连接后端”。
- Electron 关闭时在 Windows 上结束 PyInstaller 后端进程树，避免 8000 端口残留。
- Electron 只内嵌冻结后端 EXE，不再复制整套 `backend-source`。
- 发布脚本支持 `-IncludeDesktop`，并优先复用本机 Electron ZIP 缓存，避免下载超时。

后端 EXE SHA-256（恢复后重打包）：

```text
027e7369040f2a393f08b316a6e0de566314ecc70ebdda93177b4a1e30f774e5
```

对应文件：

```text
backend-dist/repomind-backend.exe
```

构建命令：

```powershell
cd backend
pyinstaller --onefile --name repomind-backend `
  --paths . `
  --hidden-import service.main `
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols.http.auto `
  --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import uvicorn.lifespan.on `
  --hidden-import fastapi --hidden-import pydantic --hidden-import pydantic_settings `
  --hidden-import openai --hidden-import sqlite3 --hidden-import asyncio `
  --workpath ../../backend-build --distpath ../../backend-dist `
  --clean --noconfirm service/main.py
```

### 桌面运行验证

已直接启动发布目录中的 `RepoMind.exe` 并实际驱动界面：

- 窗口标题为 `AgentFlow - Multi-Agent Collaboration System`。
- 中文三栏 UI 正常显示，无 Vite 开发服务器依赖。
- 页面显示“系统在线”，无连接错误框。
- 自动启动的健康检查返回 `status: ok`。
- 数据库位于 Electron 用户目录：
  `C:\Users\32799\AppData\Roaming\repomind-desktop\repomind.sqlite3`。
- 左侧面板拖动实测从 280 px 调整到 400 px，布局即时更新并写入 `localStorage`。
- 通过正常关闭桌面窗口验证，Electron 与后端均退出，8000 端口释放。

### 无 Key 与联网端到端验证

使用本地夹具和公开仓库 `https://github.com/sail0kevin/demoblaze-manual-test.git` 完成：

1. 本地 Git 仓库注册成功，扫描到 2 个文件。
2. ingest job 最终状态为 `succeeded`，进度 100%。
3. 搜索 `calculate_total_price FastAPI` 返回 2 条证据，命中 `app.py`。
4. 无 Key 问答返回 HTTP 200、规则降级回答和 2 条证据。
5. 工作流分析返回 `succeeded` 和 4 个结构化章节。
6. 公开 GitHub 仓库克隆、注册和索引成功：10 个文件、42 个 chunk，搜索返回 10 条证据。
7. 修复前端 `/analysis/analyze` 与后端旧 `/analyze` 不一致的问题，并保留旧路由兼容。
8. 代码图谱 stats、函数搜索、调用链和类关系接口均返回 HTTP 200。
9. 图谱构建现会明确报告 Python-only 支持范围；文档型或 JS/TS 仓库不再显示无解释的空图。
10. 无 Key 协作返回 2 个智能体贡献，`agents_used_llm = 0`，符合未配置模型时的降级预期。

代码图谱当前使用 Python AST。没有 Python 源码的仓库会返回 `no_supported_sources` 诊断；这是已知语言支持边界，不再被视为图谱构建成功但内容异常。

## 当前仍需完成

### 1. LongCat 在线增强验收

已使用用户临时提供且仅保存在本地设置中的凭据，完成 `LongCat-2.0` 真实调用：

- 公开仓库重新注册并完成 4 个章节的工作流分析。
- 证据问答成功，返回 10 条证据并报告 2202 tokens；回答正确识别该仓库是 Demoblaze 手工测试文档项目，而非传统代码项目。
- 四个默认 Agent 均继承全局 `LongCat-2.0` 并成功调用模型：`agents_used_llm = 4`。
- 多 Agent 协作合计报告 5081 tokens，四个角色均返回非空内容且无模型错误。
- 凭据未写入源码、测试、命令、构建日志或开发报告。

由于这枚临时 Key 已经在聊天中公开出现，项目验收后应在 LongCat 平台撤销并重新生成长期使用的 Key。

### 2. 代码图谱语言扩展

代码图谱的 Python AST 构建、持久化和回归测试已通过；JavaScript / TypeScript 当前会返回明确的不支持语言诊断。后续如需展示这些语言的函数和调用关系，再引入对应解析器。

### 3. 智能体独立模型配置

已支持“全局默认、逐 Agent 可选覆盖”：

- 默认所有 Agent 使用全局模型配置。
- 同平台低成本任务可只覆盖模型名。
- 更换 Base URL 时必须填写该 Agent 自己的 API Key，禁止全局 Key 跨接口发送。
- Agent 专属 Key 仅用于当次协作，不持久化，前端请求结束后自动清除。

后续可增加常用低成本模型预设和任务复杂度推荐，但不会自动替用户选择或保存独立凭据。

## 已知限制

- Token 统计依赖模型供应商返回 usage。如果供应商不返回，只能估算。
- 费用估算按用户设置的单价计算，不是官方账单。
- GitHub URL 只适合公开仓库；当前不做私有仓库授权。
- 索引大仓库时仍可能耗时较长，需要后续继续优化增量索引和进度展示。
- 代码图谱目前主要基于静态分析，不等价于运行时真实调用关系。

## 开发日志

### 2026-07-10

- 搭建 FastAPI + Electron + React 基础结构。
- 实现仓库注册、文件扫描、chunk、搜索、问答等主链路。
- 增加设置页和 LongCat/OpenAI 兼容模型配置。
- 增加工作流分析和多智能体协作实验能力。
- 增加代码图谱模块。
- 发现前端 `main.tsx` 和 `UserGuide.tsx` 曾出现中文显示/结构损坏问题。

### 2026-07-11

- 修复 Electron 打包产物命名配置。
- 重写前端主界面，使 GitHub URL 和本地路径分别走正确后端接口。
- 修复使用指南中文内容。
- 验证前端 `npm run build` 通过。
- 验证后端 `python -m compileall backend\service` 通过。
- 确认后端 Python 文件的中文内容本身为 UTF-8，PowerShell 显示乱码不是文件损坏。
- 修复 Vite 打包静态资源路径，发布版桌面 UI 不再空白。
- 修复 Electron `file://` 跨域与后端冷启动等待逻辑。
- 修复问答设置兼容调用和代码图谱数据库路径。
- 增加左侧面板拖动、键盘调整和宽度持久化。
- 重新构建后端 EXE、Electron 目录包并同步 `release-web-local`。
- 完成本地仓库无 Key 注册、索引、搜索、问答、工作流、协作和图谱接口验收。
- 验证正常关闭桌面窗口后端进程树退出且 8000 端口释放。

## 下一步优先级

1. 为 JavaScript / TypeScript 增加代码图谱解析器。
2. 增加低成本模型预设与任务复杂度推荐。
3. 继续优化大仓库增量索引。
4. 在发布前撤销本轮已公开的临时 Key，并使用新 Key 作为长期凭据。
