# RepoMind MCP 零配置接入方案（MCP Zero-Config Installer Plan）

> 状态：**阶段 A（A1 `--index` CLI + A2 预建索引打进 exe）、阶段 B（`scripts/setup_mcp.py`）、阶段 C（Inno Setup 安装器）均已执行并端到端验证** · 制定日期 2026-08-06 · 对应分支 `main`
> 目标：让用户下载 → 安装 → 打开 Claude Code / Codex 就能直接用 RepoMind 的 MCP 服务，**全程零手写、零命令**。
> 本报告同时列出**必须在 GitHub 各 `.md` 上同步的修改点**，避免文档与能力脱节。

---

## 1. 背景与目标

### 1.1 现状痛点

简历上写的核心卖点是 **MCP 服务可被他人使用**，但目前的真实使用路径是：

```
用户下载 RepoMind（或源码）
  → 打开桌面端导入并索引仓库      ← 必须碰桌面 UI
  → 手动编辑 Claude Code/Codex 配置   ← 手写 JSON
  → 重启会话
  → 才能用 MCP
```

这带来三个问题：

1. **MCP 开箱不可用**：打包版只带 demo **源码**（10 个文件），**没有预建索引**。官方指南明确要求"先在桌面端导入并索引仓库，再把冻结后端作为 MCP 命令"（`docs/2026-08-01_MCP_SERVER_GUIDE_MCP服务使用指南.md` L72）。MCP 服务依赖桌面端，和简历"不需要桌面端"的卖点冲突。
2. **配置靠手写**：用户要自己往 Claude Code / Codex 配置里加几行 JSON/TOML。
3. **面试叙事有漏洞**：面试官一追问"别人到底怎么用"，就绕不开桌面端和手改配置。

### 1.2 目标形态

```
用户下载 RepoMind_Setup.exe
  → 下一步下一步安装（无需管理员、不装 Python）
  → 安装器自动完成 3 件事：
      ① 写入 Claude Code 全局配置（~/.claude.json 的 mcpServers）
      ② 写入 Claude Code 自动放行（~/.claude/settings.json 的 permissions.allow）
      ③ 写入 Codex 全局配置（~/.codex/config.toml 的 mcp_servers）
  → 用户重开 Claude Code / Codex 会话
  → /mcp 里直接看到 repomind，7 个只读工具可用，开箱即查内置 demo 仓库
```

### 1.3 本次勘察核实的结论

> **勘察时点快照（2026-08-06，阶段 A/B/C 执行前）**：下表描述的是制定本方案时核实到的基线状态，不是当前状态。其中标 ❌ 的项已被后续执行阶段改变：`--index` CLI（阶段 A1）、预建索引打进 exe（阶段 A2）、安装器自动注册（阶段 C）均已落地，当前状态以 §5 各阶段"已执行"说明与 §7 验收清单为准。

| 检查项 | 勘察时点结果 | 依据（勘察时点） |
| --- | --- | --- |
| 打包 exe 支持 `--mcp` | ✅ 支持，且独立于 Electron 运行 | `backend/service/launcher.py` L8 检测 `--mcp`，绕过 `main.py` |
| exe 运行时自动建索引 | ❌ 不建，只查询已有 sqlite | MCP 工具全部走 `storage.get_connection()` 读库 |
| 包内带预建索引 | ❌ 只有 demo 源码，无索引 | 勘察时 spec 无 datas 注入；**阶段 A2 已改为注入预建索引**（见 `backend/repomind-backend.spec` L27-36） |
| 无 UI 建索引 CLI | ✅ 有源码脚本 | `scripts/rebuild_holdout_index.py` / `index_location_benchmark.py` / `profile_ingest.py` |
| 冻结 exe 有 `--index` 开关 | ❌ 勘察时没有 | 勘察时 launcher 只分 `--mcp` / HTTP 两路；**阶段 A1 已加** |

### 1.4 首次建索引耗时：必须告知用户的预期（新增，用户明确要求）

> **原则：任何让用户"建索引"的入口（README、MCP 指南、安装器、`--index` CLI），都必须先告诉用户建索引要多久、为什么要建，否则用户会以为程序卡死或没生效。**
> 参考数据全部来自本仓库真实评测产物（见下表来源列），不是估算。

**为什么必须建索引才能检索？** RepoMind 不扫描仓库做问答——它先把仓库解析成符号、关系、证据并建成可检索的 SQLite 索引（FTS5 词法 + 可选向量），之后的查询全部走索引。**不建索引，`list_repositories` 为空，任何工具都无法返回结果。**

**参考耗时（实测，词法/无 Key 模式）：**

| 场景 | 规模 | 实测耗时 | 数据来源 |
| --- | --- | --- | --- |
| 内置 demo 仓库（10 文件 / 159 chunks） | 极小 | **约 1.5 秒** | 2026-08-06 实测（`index_location_benchmark.py`，Python 3.13） |
| 中型仓库（196 文件 / 8,386 chunks） | 中等 | **约 61 秒** | `benchmark-runs/p0-1-bm25-20260730-rerun/runtime-manifest.local.json`（`elapsed_seconds: 61.11`） |

**启用语义索引（embedding）会显著变慢**：每个 chunk 都要调用 embedding 模型生成向量（网络 + 计算密集），同样 196 文件仓库实测约 **5~20 分钟**（依赖 provider 延迟）。因此默认不启用语义索引——用户不应为了首次使用等上 20 分钟。

**需要写进文档/安装器的用户话术（示例）：**

> RepoMind 会先把仓库解析并建立检索索引（词法模式：内置 demo 约 1~2 秒，中型仓库约 1 分钟；启用语义检索会更久）。索引建立后，后续查询直接复用，不再重复建。**建索引是检索的前提**，请耐心等待首屏进度。

**落地位置（三处必须同步）：**
1. **README.md** —— "最快体验"段新增"首次建索引需要多久"小节。
2. **MCP 使用指南** —— 前置条件段补充：首次使用需先建索引及其耗时。
3. **安装器 / `--index` CLI** —— 运行时打印预计耗时，并明示"正在建索引，请不要中断"。
| 客户端可自动注册 | ✅ Claude Code / Codex 均可 | 见 §3.3 |

---

## 2. 总体方案（分 3 阶段）

| 阶段 | 交付物 | 解决什么 | 是否必须 |
| --- | --- | --- | --- |
| **阶段 A** | 预建 demo 索引打进 exe + `--index` CLI | 解决"MCP 开箱无索引" | **必须先做** |
| **阶段 B** | `scripts/setup_mcp.py` 一键注册脚本 | 解决"配置靠手写"（源码用户） | 推荐做 |
| **阶段 C** | Inno Setup 安装器，安装时自动注册 | 解决"下载即用"（打包用户） | 终极形态 |

阶段 A 是地基：**没有预建索引，注册得再顺也没内容可查**。阶段 C 依赖 A + B 的注册逻辑，本质是"把 B 的注册逻辑搬进安装器 post-install"。

---

## 3. 已核实的实现细节（勘察结论）

> **勘察时点快照（2026-08-06，阶段 A/B/C 执行前）**：本节的代码行号与描述均为制定方案时的勘察快照，阶段 A/B/C 已按其落地并端到端验证，具体差异见 §5 各阶段说明与 §7 验收清单。

### 3.1 打包链路

- **入口**：`backend/service/launcher.py`（PyInstaller one-file 模式，spec 在 `backend/repomind-backend.spec` L40 `Analysis([launcher.py])`）。
- **`--mcp` 分发**：`launcher.py` L8 `if "--mcp" in sys.argv[1:]` → 导入 `service.mcp_server.__main__` 运行 MCP stdio server；否则走 FastAPI HTTP。
- **产物**：`backend-dist/repomind-backend.exe`（单文件，约 47 MB，console=True, upx=True；spec 用 `excludes` 排除可选重型 ML 依赖后实测 46.8 MB）。
- **spec 的 datas（勘察时为空）**：勘察时 `datas = []`，只 `collect_data_files("mcp")` + tree-sitter 的 `collect_all`。**阶段 A2 已在 spec 注入预建索引**（见 `backend/repomind-backend.spec` L27-36：存在 `index.marker` + `repomind.sqlite3` 时把两者写入 datas）。
- **桌面端位置**：`desktop/app/release/win-unpacked/resources/backend/repomind-backend.exe`（electron-builder extraResources 拷贝，`main.ts` L216 引用）。
- **包版本校验**：`package_windows.ps1` L109-117 比较打包后 exe 与 `backend-dist` 哈希一致，L119-139 校验 demo 目录**恰好 10 个文件**（demo 目录不能塞别的）。
- `smoke_mcp.ps1` L75 断言"空库时 list_repositories 为空"——**若默认注册预建索引需同步改这条 smoke**。

### 3.2 无 UI 建索引（已存在，可复用）

核心链路（`scripts/rebuild_holdout_index.py` L19-61，与 `index_location_benchmark.py` / `profile_ingest.py` 一致）：

```python
# 1) 指向隔离数据目录
settings_module._settings = Settings(
    paths=Paths(data_dir=<DATA_DIR>, database_path=<DATA_DIR>/"repomind.sqlite3"))
from service.storage.sqlite_db import reset_database_initialization
reset_database_initialization()  # 清连接缓存，重建表

# 2) 注册仓库（需要真实 git checkout，必须有 .git，且工作区干净）
registration = create_repository(RepoCreateRequest(
    repo_path=str(repo_path), alias="RepoMind Demo", remote_url=None, branch=None))

# 3) 同步 ingest（scan→parse→facts→chunks→code_graph→catalog→validate→publish）
result = ingest_repository_snapshot(registration.repo_id,
                                    expected_commit=<SHA or None>)
```

- 产物就是单文件 `<data-dir>/repomind.sqlite3`（demo 10 文件约 1.4 MB；159 chunks、48 catalog_items，词法 BM25，无向量）。无 Key、无网络、无 sqlite_vec。
- **实测耗时**：demo 全流程 **1.47 s**（Windows / Python 3.13）；196 文件仓库词法 61 s；带 embedding 才需分钟级。
- **Demo 确定性**：demo 是合成夹具（10 个源文件、自身无 .git）。需按 `desktop/app/electron/main.ts` `prepareDemoRepository()` 的逻辑先复制 10 文件到临时目录，再以**固定身份/日期** `git init --initial-branch=main && add && commit`（固定环境变量 HOME/USERPROFILE、GIT_AUTHOR_*、固定时间戳），得到**确定性 commit `94d4aa637070d37ff0f08c820ba4413b66b66296`**（已验证）。
- ⚠️ **历史 commit 注意**：当前 demo fixture 的确定性 commit 是 `94d4aa63`，但 README 和 gold fixtures 引用的旧 commit 是 `8c5ac33542fbed5e117bfee19af1457e60bd166c`（旧 fixture 含空 README.md；2026-08-03 commit `4b4f698` 把 README.md 改名 `OLD_REPOMIND_DEMO_README.md`）。**预建索引要用当前 fixture（94d4aa63），README 的旧 demo 指标数字对不上新的索引**——这是文档要同步修改的点之一（见 §4）。

### 3.3 客户端自动注册（已核实，来自官方文档/源码）

#### Claude Code

- **用户级注册命令**（作用于所有项目）：
  ```
  claude mcp add repomind -s user -t stdio [-e KEY=VALUE ...] -- <command> [args...]
  ```
  写入 `%USERPROFILE%\.claude.json` 的顶层 `mcpServers` 键。
- **自动放行**（免每个工具弹确认框）：写入 `%USERPROFILE%\.claude\settings.json` 的 `permissions.allow`：
  ```json
  { "permissions": { "allow": ["mcp__repomind__*"] } }
  ```
  注意：全局 `mcp__*` / 裸 `*` 在 allow 里会被忽略；**全限定 `mcp__repomind__<tool>` 最可靠**（有 bug 报告通配符仍弹框：claude-code#34739）。
- ⚠️ **Windows 坑**：`claude mcp add <name> -- cmd /c <cmd>` 会把 `/c` 改写成 `C:/`。**安装器优先直接写配置文件**，或对纯 exe 路径用 `claude mcp add-json`。
- ⚠️ **必须重启会话**：MCP server 只在会话启动时加载，已运行的会话不会热加载新注册的 server。

#### Codex

- 配置文件：`%USERPROFILE%\.codex\config.toml`（若设了 `CODEX_HOME` 则在其下）。全局文件对所有项目生效。
- 注册片段（自动放行关键字段）：
  ```toml
  [mcp_servers.repomind]
  command = "C:\\...\\repomind-backend.exe"
  args = ["--mcp"]
  env = { REPOMIND_PATHS__DATA_DIR = "...", REPOMIND_PATHS__DATABASE_PATH = "...", PYTHONIOENCODING = "utf-8" }
  default_tools_approval_mode = "auto"   # 默认就是 auto：只读工具不弹框
  enabled = true
  required = false                        # 千万别设 true，否则 server 挂了连 Codex 都起不来
  ```
- 或官方 CLI：`codex mcp add repomind --env K=V -- "C:\...\repomind-backend.exe" --mcp`（自动安全合并，非交互）。
- 同样需要**新开会话**才生效。

#### 安装器建议（Inno Setup）

- **选 Inno Setup**（优于 NSIS / MSIX）：`PrivilegesRequired=lowest`（无 UAC 提权）、`DefaultDirName={localappdata}\RepoMind`，安装/卸载都按安装用户身份运行，`%USERPROFILE%` 解析正确。
- **post-install 注册**：优先**直接改配置文件**（merge-never-overwrite + 先写 `.bak`），不依赖 `claude`/`codex` CLI 是否在 PATH；若检测到 CLI 在 PATH，可额外调用官方命令做二次保险（失败不致命）。
- **卸载策略**：默认**不删除**注册条目（用户数据，悬空条目最多一条无害警告）；若做清理，仅当条目 `command` 仍精确等于安装写入的路径时才删除，绝不整表删除。
- 全程**不改 PATH**（用户级 PATH 有 ~2048 字符限制且要广播 WM_SETTINGCHANGE），配置里存绝对路径即可。

---

## 4. GitHub `.md` 修改清单（与实现同步推进）

> 所有措辞必须以真实能力为准：**预建索引 + 自动注册落地之前，禁止在 README/指南里宣称"零配置"**。

### 4.1 `README.md`

| 位置 | 现内容 | 改法 |
| --- | --- | --- |
| L56（接入 Coding Agent 段） | "Windows Setup 安装版可直接使用内置的 `repomind-backend.exe --mcp`，不需要另装 Python" | **预建索引落地后**改为：安装版内置 demo 预建索引，安装后自动注册到 Claude Code / Codex，重开会话即用；`list_repositories` 直接返回 demo 仓库 |
| L27-43 本地运行 | clone + venv + npm | 新增一行"想更快？用一键安装器"，链接 docs 新指南 |
| L142-152 当前验证 | 列测试通过数 | 新增验证项：`--index` 建索引成功、打包版自动注册 smoke 通过 |
| L164-170 文档列表 | 现有链接 | 追加新文档链接 |
| L80-94 demo 指标 | 引用旧 commit `8c5ac335` | **若换新 fixture 预建索引**，需说明 demo 指标基于旧 fixture，或补新索引的复算数字（遵守"测试数据不比原版好就不提交"红线） |
| **新增**（建议紧跟 L43 本地运行之后） | 无 | **新增"首次建索引需要多久"小节**：放 §1.4 的参考耗时表 + 用户话术，说明"建索引是检索的前提、后续查询复用" |

### 4.2 `docs/2026-08-01_MCP_SERVER_GUIDE_MCP服务使用指南.md`

- L72 **"先在桌面端导入并索引仓库"**——这是"MCP 依赖桌面端"的源头表述。预建索引落地后改为："安装版已内置 demo 预建索引，开箱即用；索引你自己的仓库可选①桌面端导入 ②`repomind-backend.exe --index --repo <路径>`。"
- **新增章节"零配置一键接入"**（放在 L32 前置条件之后、L34 本地启动之前，符合"最简单路径放最前"）：
  - 安装器用户：下载 → 安装 → 重开会话 → 已注册。
  - 源码用户：`python scripts/setup_mcp.py` 一键注册（阶段 B 交付后补）。
- L68 遥测说明同步措辞。
- **前置条件段（L19-32）补充"首次建索引耗时"**：放 §1.4 参考耗时表，明确"不建索引 `list_repositories` 为空、无法检索"。

### 4.3 `docs/2026-08-01_DOCUMENTATION_INDEX_文档导航.md`

- 在"当前入口"表格（L21-30）追加本报告链接：`docs/后续开发指导/2026-08-06_MCP_ZERO_CONFIG_INSTALLER_PLAN_MCP零配置接入方案.md`，注明"MCP 零配置接入的执行方案（待审批）"。

### 4.4 `docs/后续开发指导/2026-08-01_IMPROVEMENT_PLAN_V2_当前改进执行计划.md`

- 在 L618"对下一个 AI 的交接说明"追加一条：MCP 零配置接入方案见本报告，阶段 A 优先级高于既有 P0（它是 MCP 卖点的前置条件）。

### 4.5 新增文档（本报告本身）

- 本文档即阶段计划。执行完成后如需留存为"能力说明"，再决定是否提级为 `docs/` 顶层当前依据文档；执行期间保持 `后续开发指导/` 地位。

---

## 5. 执行计划（按顺序）

### 阶段 A1：给冻结 exe 加 `--index` CLI（方案 B 的能力）

在 `backend/service/launcher.py` 增加 `--index` 分支（兄弟分支，与 `--mcp` 并列）：

```
repomind-backend.exe --index --repo <git路径> --data-dir <目录> [--alias <名称>]
```

- 直接复用已内联的 `create_repository` + `ingest_repository_snapshot`（spec 已传递收集 ingest 代码，无需改 spec）。同步执行、带进度打印，最后打印 `repo_id`。
- **启动时打印预计耗时**（对照 §1.4 参考数据：词法 10 文件约 1.5 秒、196 文件约 61 秒；启用 embedding 提示分钟级），并明示"正在建索引，请不要中断"；结束时打印实际耗时。
- 默认词法索引（无 key）；`REPOMIND_SQLITE_READ_ONLY=true` 时只读。
- 改 `backend/tests/` 补 `--index` 测试 + `scripts/smoke_mcp.ps1` 兼容。

### 阶段 A2：预建 demo 索引打进 exe

1. 脚本化确定性 demo 构建（复制 10 文件 → 固定身份 git commit → 得 `94d4aa63`）→ 无 UI 建索引 → 产出 `<build>/prebuilt/repomind.sqlite3` + `index.marker`。
2. 改 `backend/repomind-backend.spec` datas 追加：
   ```python
   prebuilt_index_root = backend_root / "resources" / "prebuilt"
   datas += [(str(prebuilt_index_root / "repomind.sqlite3"), "index")]
   datas += [(str(prebuilt_index_root / "index.marker"), "index")]
   ```
   （one-file 模式解压到运行时 `sys._MEIPASS/index/...`；exe 体积增大 ~1.4 MB。）
3. MCP server 启动时检测 marker：存在则把 `REPOMIND_PATHS__DATABASE_PATH` 指向 `sys._MEIPASS/index/repomind.sqlite3`（读 `getattr(sys, "_MEIPASS", ...)`），并默认 `REPOMIND_SQLITE_READ_ONLY=true`（避免迁移/WAL/遥测写坏只读索引）。
4. 打包流水线产物：源码版 `backend-dist/repomind-backend.exe`（自带索引）；桌面版 resources 里 exe 同样自带索引。
5. **同步改 smoke**：`smoke_mcp.ps1` L75 空库断言 → 改为"预建索引存在时 `list_repositories` 返回 demo 仓库"。

### 阶段 B：`scripts/setup_mcp.py` 一键注册（源码用户）

```
python scripts/setup_mcp.py            # 自动检测 claude / codex
python scripts/setup_mcp.py --dry-run  # 只打印将写入什么，不改文件
```

- 写 `%USERPROFILE%\.claude.json` 的 `mcpServers.repomind`（stdio，command 指向 `python -m service.mcp_server` 或已装 exe），**merge 不覆盖 + 先写 .bak**。
- 写 `%USERPROFILE%\.claude\settings.json` 的 `permissions.allow += ["mcp__repomind__*"]`。
- 写 `%USERPROFILE%\.codex\config.toml` 的 `[mcp_servers.repomind]`（TOML merge，仅当同名不存在；绝不用 `required=true`）。
- 校验：`claude mcp get repomind` / `codex mcp list`；提示"请重启会话"。

### 阶段 C：Inno Setup 安装器

- 复用阶段 B 的注册逻辑（直接写配置文件的路径）。
- 打包 `backend-dist/repomind-backend.exe`（自带预建索引）+ 可选 desktop 资源。
- 安装完成页提示"已注册到 Claude Code 与 Codex，请重开会话"。
- **安装/首次建索引时告知耗时**：若提供"导入并索引你的仓库"入口，必须先展示预计耗时（对照 §1.4 参考数据），并明示"建索引是检索的前提，请不要中断"。demo 预建索引开箱即用，无需用户等待。

**阶段 C 已执行（2026-08-07）**，交付物与实测：

- 新增 `installer/RepoMind_Setup.iss`（UTF-8 BOM，Inno Setup 6 语法）：`PrivilegesRequired=lowest`、`DefaultDirName={localappdata}\RepoMind`、打包 `repomind-backend.exe` + `demo/repomind-demo`（10 文件，`Excludes: __pycache__,*.pyc,.git`）+ `scripts/register_repomind.ps1`。
- 新增 `scripts/register_repomind.ps1`（纯 ASCII PowerShell 5.1，把 `setup_mcp.py` 的 merge + `.bak` + 原子写逻辑搬到安装器 post-install，**不需要 Python**；`-Force` 让重装时把注册的 `command` 更新为当前安装路径；写入 `{app}\registration-status.txt` 供完成页如实显示）。
- 新增 `scripts/build_installer.ps1`；`package_windows.ps1` 增加 "Windows installer" 阶段（版本与 `package.json` 一致）。产物 `installer-output\RepoMindSetup-<version>.exe` 已 gitignore，不入库。
- 编译环境：本机无管理员权限，无法跑官方安装器（IsAdmin=False），改用 `innoextract` 从 Inno Setup 6.0.5 安装包无管理员解出便携 `ISCC.exe`（放本机工具目录，路径不入库；`build_installer.ps1` 按 `INNO_SETUP_ISCC` 环境变量 → Program Files → `scripts\local-iscc-path.txt`（gitignored 本机专属）→ `-ISCCPath` 参数 的顺序定位 ISCC）。`.iss` 只用 6.x 通用指令，CI（GitHub Actions 预装最新版）可直接编译。
- 向导为英文（6.0.5 便携包不含中文语言包），安装完成页为中文（[Code] 按 `registration-status.txt` 显示"已注册到 Claude Code 与 Codex，请重开会话"或失败提示）。
- 安装器**不提供**"导入并索引你的仓库"入口（demo 预建索引开箱即用；用户自己的仓库走桌面端或 `--index` CLI），故无需在安装器内展示建索引耗时；`--index` CLI 已打印预计/实际耗时并提示"请不要中断"。
- 卸载安全：只删 `{app}` 下安装清单内文件；运行时生成的 `registration-status.txt` 用 `[UninstallDelete]` 显式删除；`.claude.json` / `.claude\settings.json` / `.codex\config.toml` 一律不动。
- 端到端实测（沙盒 USERPROFILE 隔离真实配置）：静默安装 exit 0 → 文件齐、demo 10 文件 0 污染、`overall=ok` → 已安装 exe `--mcp` 通过 `smoke_mcp.ps1` 预建模式（tools=7、discovery=ok）→ 卸载 exit 0、`{app}` 完整移除、配置条目与原有内容全保留、真实配置未被动过。

---

## 6. 风险与诚实边界

1. **预建索引只是 demo**：只覆盖内置 demo 仓库，用户自己的仓库仍需索引（桌面端导入或 `--index`）。README/话术不得写成"装完就能查任意仓库"。
2. **demo fixture 切换**：预建索引基于当前 fixture（commit `94d4aa63`），与 README 旧 demo 指标（基于 `8c5ac335`）不一致。要么保留旧 fixture 说明、要么复算新索引指标——**遵守红线：测试数据没有原版好就不提交**。
3. **只读索引**：`REPOMIND_SQLITE_READ_ONLY=true` 走 immutable 只读 URI，跳过迁移/WAL/遥测——这是特性（保护预建索引），但意味着 MCP 不会为预建索引写遥测，文档要如实写。
4. **配置 merge 风险**：`.claude.json` 还存 userID/projects 等状态，写坏会导致 Claude Code 打不开。必须 merge + `.bak` + 原子写（临时文件+rename），并防并发（Claude Code 运行时别改）。
5. **未签名安装器**：SmartScreen "未知发布者"是预期行为，不是病毒结论。购买 OV/EV 证书（约 $100-500/年）或 Microsoft Trusted Signing（约 $10-15/月）；绝不自签名（比不签更糟）。
6. **客户端版本**：老版本 Claude Code（约 2.1.119-2.1.123）存在用户级 MCP 写后不读的 bug（claude-code#54803），当前 2.1.223 正常。安装器最好校验最小版本或用 `claude mcp get` 验证。
7. **不修改目标仓库**：MCP 只读，无 Shell/写文件工具——保持现有安全边界不变。

---

## 7. 验收标准

- [x] `repomind-backend.exe --index --repo <demo checkout> --data-dir <dir>` 产出 sqlite，`list_repositories` 返回 demo。（实测：10 文件 / 159 chunks / commit `94d4aa63` / 0.4 s；`smoke_mcp.ps1 -IndexRepo` 通过）
- [x] 打包后 exe 自带预建索引，`--mcp` 启动（不设任何 env）即能查到 demo 仓库。（`smoke_mcp.ps1` 预建模式通过，tools=7、discovery=ok）
- [x] `smoke_mcp.ps1` 在"有预建索引"和"空库"两种情形都通过。（prebuilt-index / empty-database / shared-index 三种模式全部通过）
- [x] `setup_mcp.py --dry-run` 打印正确配置；真实运行 merge 不覆盖、写 `.bak`、`required=false`。（隔离 HOME 实测）
- [x] Inno Setup 安装器：静默安装到临时目录 → 已安装 exe `--mcp` 通过 `smoke_mcp.ps1` 预建模式（tools=7、discovery=ok、list_repositories 返回内置 demo）。（阶段 C，2026-08-07 实测）
- [x] 卸载不破坏 `.claude.json` / `config.toml` 其他内容：卸载后配置条目与既有内容全保留、真实配置未被动过；`{app}` 完整移除。（阶段 C，2026-08-07 实测）
- [x] 后端测试全绿（**337 passed**，329 基线 + 新增 `--index`/预建索引检测 8 条），README/指南/文档导航同步更新且措辞如实。
- [x] README 与 MCP 指南包含"首次建索引耗时"小节（§1.4 参考数据），并说明"建索引是检索的前提、后续查询复用"。
- [x] `--index` CLI 打印预计/实际耗时，并提示"请不要中断"。（安装器不设"导入并索引你的仓库"入口——demo 预建索引开箱即用，用户自己的仓库走桌面端或 `--index`，故安装器内无需建索引耗时展示）
