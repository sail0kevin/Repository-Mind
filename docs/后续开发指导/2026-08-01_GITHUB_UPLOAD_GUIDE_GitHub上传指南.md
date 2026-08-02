# GitHub 上传清单

本文用于说明 RepoMind 哪些文件应该进入 GitHub，哪些文件只保留在本机。执行上传时不要直接使用 `git add .` 或 `git add -A`，应按目录显式暂存并逐批检查。

## 一、应该上传

### 1. 项目说明和版本配置

```text
2026-08-01_REPOMIND_README_项目说明.md
.gitignore
.env.example
.nvmrc
.python-version
```

说明：`.env.example` 只能包含变量名、空值和示例值，不能包含真实 API Key。

### 2. 后端源码、迁移和测试

```text
backend/service/
backend/tests/
backend/requirements.txt
backend/requirements-dev.txt
backend/requirements-build.txt
backend/pytest.ini
backend/repomind-backend.spec
```

`backend/tests/` 中只上传测试代码和人工构造的 fixtures，不上传 `.tmp/`、SQLite 数据库或测试运行生成的备份。

### 3. 桌面端源码和测试

```text
desktop/app/electron/
desktop/app/renderer/
desktop/app/package.json
desktop/app/package-lock.json
desktop/app/electron-builder.yml
desktop/app/vite.config.ts
```

`package-lock.json` 必须上传，因为 GitHub Actions 使用 `npm ci` 安装固定版本依赖。

### 4. 构建与发布配置

```text
scripts/build_backend.ps1
scripts/package_windows.ps1
scripts/smoke_backend.ps1
scripts/verify_identity_contract.ps1
scripts/verify_runtime_contract.ps1
scripts/verify_release_hashes.ps1
.github/workflows/ci-windows.yml
.github/workflows/release-windows.yml
```

这些是从源码重新生成后端 EXE、Electron 应用、NSIS 安装包和 Portable 版本所必需的工程文件。

Windows CI 和 Release 都会使用锁定的 Python `3.12`、Node `20.18.0`、npm `10.8.2` 执行同一套打包链。链路必须在包内后端 HTTP/MCP smoke、隔离的 Electron E2E 通过后，重新核验 `SHA256SUMS.txt`：清单必须覆盖 release 目录中除清单自身外的每一个文件，且没有重复、不安全路径或哈希不匹配。只有该 CI 产物或 tag Release 才可作为当前 schema v009 桌面包的发布证据。

### 5. 当前正式文档

```text
docs/2026-08-01_REPOMIND_README_项目说明.md
docs/后续开发指导/2026-08-01_IMPROVEMENT_PLAN_V2_当前改进执行计划.md
docs/后续开发指导/2026-07-28_ARCHITECTURE_FUTURE_ROADMAP_未来架构路线图.md
docs/后续开发指导/2026-07-26_RAG_VS_AGENTIC_RAG与智能体检索定位.md
docs/后续开发指导/2026-08-01_GITHUB_UPLOAD_GUIDE_GitHub上传指南.md
docs/旧的文件/
```

`docs/旧的文件/` 中的资料用于保留已废弃决策的追溯链；其中不得包含密钥、真实仓库数据、运行数据库或机器专属路径。

## 二、本地保留，但不上传

```text
.claude/
data/
```

- `.claude/` 包含本地会话、工具状态和历史 worktree。
- `data/` 可能包含真实用户仓库、索引、问答、Evidence 和 Agent Trace。

这些目录不能使用全局清理命令批量删除。

## 三、可删除且不上传的再生产物

```text
backend/tests/.tmp/
backend/.pytest_cache/
backend/**/__pycache__/
backend-build/
backend-dist/
desktop/app/node_modules/
desktop/app/dist-electron/
desktop/app/dist-renderer/
desktop/app/release/
```

这些文件都能通过测试或构建命令重新生成。Windows 安装包和 Portable 应通过 GitHub Actions Artifact 或 GitHub Release 发布，而不是直接提交进 Git。

## 四、绝不能上传

```text
.env
.env.local
secrets.json
secrets.json.tmp
*.sqlite
*.sqlite3
*.db
数据库备份、WAL、SHM
*.pem
*.key
*.p12
*.pfx
日志文件
真实用户仓库缓存
API Key、Token、密码、私钥
```

如果真实密钥曾进入 Git 历史，仅删除文件是不够的；必须立即在供应商平台撤销并轮换密钥，必要时清理 Git 历史。

## 五、推荐的分批暂存顺序

### 第 1 批：上传边界

```bash
git add -- .gitignore
```

### 第 2 批：README 和正式文档

```bash
git add -- 2026-08-01_REPOMIND_README_项目说明.md "docs/后续开发指导"
```

如果是在尚未完成旧文档迁移的工作树中整理，还需要先用 `git status` 确认旧路径确实存在，再显式暂存对应删除；全新 clone 不需要执行旧路径迁移命令。

### 第 3 批：工程和依赖配置

```bash
git add -- .env.example .nvmrc .python-version
git add -- backend/requirements.txt backend/requirements-dev.txt backend/requirements-build.txt
git add -- backend/pytest.ini backend/repomind-backend.spec
git add -- desktop/app/package.json desktop/app/package-lock.json
git add -- desktop/app/electron-builder.yml desktop/app/vite.config.ts
```

### 第 4 批：后端源码

```bash
git add -- backend/service
```

### 第 5 批：后端测试

```bash
git add -- backend/tests
```

### 第 6 批：桌面端源码和测试

```bash
git add -- desktop/app/electron desktop/app/renderer
```

### 第 7 批：脚本和 GitHub Actions

```bash
git add -- scripts .github/workflows
```

## 六、每批暂存后检查

```bash
git status --short
git diff --cached --stat
git diff --cached --name-status
git diff --cached --name-only
```

禁止路径不应出现在暂存列表中：

```text
.claude/
node_modules/
backend-build/
backend-dist/
release/
dist-electron/
dist-renderer/
backend/tests/.tmp/
data/
```

误暂存时只撤销暂存，不删除本地文件：

```bash
git restore --staged -- <path>
```

## 七、推送建议

首次整理上传建议创建单独分支并通过 Pull Request 检查最终文件树，不直接推送到 `main`：

```bash
git switch -c chore/github-publication-boundary
git push -u origin chore/github-publication-boundary
```

只有在用户明确要求后才执行 commit 和 push。远端 Windows Actions 通过后，再合并到 `main`。
