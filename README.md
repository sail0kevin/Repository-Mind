# Repository-Mind / RepoMind

RepoMind 是一个面向 Windows 的本地 Git 仓库知识助手。它把仓库的 Git commit 构建为不可变知识快照，通过结构解析、SQLite FTS5/BM25、可选 Embedding、证据组装和条件式 Main Agent，帮助用户浏览仓库、检索源码并进行可追溯问答。

RepoMind 默认只读分析目标仓库：**不执行被分析代码、不安装目标仓库依赖、不修改目标仓库，也不自动提交代码或创建 PR。**

## 已实现能力

- 注册本地 Git 仓库，或通过 `https://github.com/owner/repo` 形式浅克隆公开 GitHub 仓库。
- 将已提交的 Git commit 构建为不可变 Snapshot；失败的新快照不会替换当前可用快照。
- 对 Python、JavaScript/TypeScript、Markdown 和配置文件进行结构解析；其他受支持文本使用 fallback 切片。
- 使用 SQLite FTS5/BM25 进行词法检索，并支持标识符、路径和配置键检索。
- 可选接入独立的 OpenAI-compatible Embedding；未配置或失败时明确降级为 `lexical-only`。
- 建立 Repository Catalog、目录树、文件视图、静态符号关系和代码图谱。
- Main Agent 先检索并裁剪 Evidence Bundle，再根据问题类型按需调用最多两个 Specialist Tool。
- Chat 与 Embedding 使用独立配置和独立 API Key；没有 Chat Key 时仍可返回规则型回答。
- 保存问答的 Snapshot、引用证据和 Agent Trace，可从界面查看路由、检索、工具和综合过程。
- 保留 Legacy 多角色协作接口，但它不再是普通问答的默认流程。
- Electron 桌面端可浏览仓库、切换 Snapshot、查看 Catalog、搜索、问答、查看源码证据和执行轨迹。

## 使用边界

### Git 仓库

- 本地仓库必须存在有效的 HEAD commit。
- 创建或刷新 Snapshot 前，目标仓库必须保持干净，不能有未提交或未跟踪文件。
- 索引期间如果 HEAD、分支或文件内容发生变化，本次 Snapshot 不会发布。
- GitHub URL 当前只支持无需认证的 `github.com` 公开仓库；尚未提供私有仓库授权。
- 系统必须能够从 PATH 调用 Git。

### 文件和解析

- 二进制文件及不支持的文件类型不会进入知识索引。
- Python、JavaScript/TypeScript、Markdown、JSON、YAML 和 TOML 等类型使用专用解析器。
- 无法结构解析的可读文本可能使用 fallback 切片，并在诊断信息中明确标记。
- 代码图谱来自源码静态分析，不等同于运行时调用图；完整度取决于语言、语法和静态链接能力。

### 模型与密钥

- Chat 和 Embedding 完全独立，Embedding 默认关闭。
- 未配置 Chat API Key 或模型调用失败时，问答会降级为规则型回答，而不是直接返回 500。
- 未配置或无法使用 Embedding 时，检索模式为 `lexical-only`。
- Windows 桌面版使用当前 Windows 用户的 DPAPI 加密保存密钥。
- 设置查询只返回是否已配置和脱敏提示，不返回完整密钥。

## 项目结构

```text
backend/                 FastAPI 后端、迁移、解析、检索、Catalog 和 Main Agent
backend/repomind-backend.spec
                         正式 PyInstaller 冻结构建配置
desktop/app/             Electron + React + TypeScript 桌面应用
scripts/                 Windows 构建、smoke 和身份验证脚本
.github/workflows/       Windows CI 与发布工作流
docs/后续开发指导/       当前开发报告和架构说明
```

## Windows 环境要求

推荐使用项目固定的构建基线：

- Windows 10/11 x64
- Python 3.12
- Node.js 20.18.0
- npm 10.x（项目声明 `npm@10.8.2`）
- Git
- Windows PowerShell 5.1 或 PowerShell 7
- 构建 Python 的 SQLite 必须支持 FTS5

版本提示文件：

```text
.python-version
.nvmrc
```

## 本地开发

### 后端

```powershell
python -m pip install -r backend/requirements-dev.txt
cd backend
python -m service.main
```

默认 API 地址：

```text
http://127.0.0.1:8000/api/v1
```

### 桌面端

```powershell
cd desktop/app
npm ci
npm run dev
```

开发模式允许 Electron 使用本机 Python 启动后端；正式打包模式只使用应用内置的 `repomind-backend.exe`，不会静默回退到系统 Python。

## Windows 构建与验证

先安装后端构建依赖：

```powershell
python -m pip install -r backend/requirements-build.txt
```

执行完整验证并生成 `win-unpacked`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/package_windows.ps1 `
  -PythonCommand python
```

生成 NSIS 安装包和 Portable 版本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/package_windows.ps1 `
  -PythonCommand python `
  -Release
```

完整发布链依次执行：

1. 产品身份和 `/api/v1` 契约检查；
2. 构建 Python 的 SQLite FTS5 检查；
3. 后端测试；
4. PyInstaller 正式 spec 构建；
5. 冻结后端隔离 smoke；
6. `npm ci` 和桌面端测试；
7. Vite Renderer 与 Electron TypeScript 构建；
8. `win-unpacked` 打包；
9. 源后端与内置后端 SHA-256 一致性检查；
10. 内置后端隔离 smoke；
11. 可选生成 NSIS、Portable 和 `SHA256SUMS.txt`。

主要产物：

```text
backend-dist/repomind-backend.exe
desktop/app/release/win-unpacked/
desktop/app/release/RepoMind-<version>-x64-setup.exe
desktop/app/release/RepoMind-<version>-x64-portable.exe
desktop/app/release/SHA256SUMS.txt
```

## Smoke 验证范围

`scripts/smoke_backend.ps1` 使用临时 `APPDATA`、临时数据库、随机端口和无 Key 环境启动冻结后端，并验证：

- RepoMind 后端身份、API v1 和启动会话身份；
- 实际数据库 Schema 7；
- 迁移序列 `1,2,3,4,6,7`；
- SQLite integrity、foreign key 和真实 FTS5 查询；
- Trace 相关表存在；
- Chat/Embedding Key 均未配置；
- 后端使用指定临时数据库；
- 退出后进程树和 EXE 文件锁已释放。

真实用户数据库不会用于构建 smoke。

## CI 与发布

- `.github/workflows/ci-windows.yml`：push、pull request 或手动触发 Windows 构建链。
- `.github/workflows/release-windows.yml`：`v*` Tag 或手动触发 Windows Release。
- Release workflow 会校验 Tag 与 `desktop/app/package.json` 版本是否一致，并上传 Setup、Portable 和 SHA-256 文件。

当前工作流已经配置完成，但必须在代码推送到 GitHub 后以远端 Actions 的真实运行结果作为最终 CI 结论。

## 常见问题

### Electron Builder 无法下载资源

Electron Builder 需要从 GitHub 下载 Windows 构建工具。网络受限时可以临时设置镜像：

```powershell
$env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"
$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
```

镜像属于本机构建辅助配置，不写入正式 GitHub Actions。

### `Cannot create symbolic link`

Windows 未开启开发者模式、当前终端没有相应权限时，Electron Builder 解压 `winCodeSign` 可能失败。推荐开启 Windows 开发者模式后重试。仅用于本地内容验证时，也可以临时传入：

```text
--config.win.signAndEditExecutable=false
```

该参数会跳过 Windows EXE 图标/资源编辑，不应被当作正式签名方案。

### 默认 Electron 图标

项目当前尚未配置正式应用图标和代码签名证书，因此本地构建会使用 Electron 默认图标，并可能显示 Windows 未知发布者提示。

## 当前限制

- 仅正式支持和验证 Windows 桌面端。
- 私有 GitHub 仓库授权尚未实现。
- Embedding 默认关闭，使用时需要独立配置兼容服务。
- 大型仓库的索引时间、存储空间和检索评测仍需继续优化。
- 静态安全工具只提供代码线索，不构成完整安全审计。
- 当前没有正式代码签名证书和产品图标。
- GitHub Actions 尚需在远端仓库实际运行后确认全绿。

更完整的实现状态和验收记录见 [开发报告](docs/后续开发指导/DEVELOPMENT_REPORT.md)。
