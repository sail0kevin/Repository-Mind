import { app, BrowserWindow, dialog, ipcMain, screen } from "electron";
import * as path from "path";
import * as childProcess from "child_process";
import * as fs from "fs";
import * as http from "http";
import * as net from "net";
import { randomUUID } from "crypto";
import { computeDatabaseIdentity, createSingleFlight, ownsBackendSession, pythonLauncherCandidates, revalidateTrackedBackend } from "./backendLifecycle";
import { validateSaveTextRequest } from "./exportContract";
import type { PythonLauncher } from "./backendLifecycle";
import type { BackendStartResult, DemoPrepareResult, SaveTextResult } from "./bridgeContract";

const APP_ID = "com.repomind.app";
const USER_DATA_BASENAME = "repomind-desktop";
const EXPECTED_INSTANCE_ID = "repomind-desktop-backend";
const EXPECTED_BACKEND_CONTRACT_VERSION = "1";
export const MIN_BACKEND_SCHEMA_VERSION = 7;

export function resolveUserDataPath(appDataPath: string, overridePath?: string): string {
  return overridePath
    ? path.resolve(overridePath)
    : path.join(appDataPath, USER_DATA_BASENAME);
}

// 默认继续使用稳定历史目录；本地验收可显式指定隔离目录，避免接触真实用户数据库。
app.setPath(
  "userData",
  resolveUserDataPath(app.getPath("appData"), process.env.REPOMIND_USER_DATA_PATH),
);
app.setAppUserModelId(APP_ID);

let mainWindow: BrowserWindow | null = null;
let backendProcess: childProcess.ChildProcess | null = null;
let backendPort: number | null = null;
let backendSessionId: string | null = null;
let backendApiToken: string | null = null;
let backendShutdownToken: string | null = null;
let stoppingBackend = false;
let quitCoordinationStarted = false;
const isDev = process.env.NODE_ENV === "development";

interface BackendHealth {
  status: string;
  app_name: string;
  api_version: string;
  schema_version: string;
  database_schema_version: string;
  supported_schema_version: string;
  backend_contract_version: string;
  instance_id: string;
  session_id: string | null;
  database_identity: string;
}

export function sanitizeExportFileName(value: string, extension: string): string {
  const stem = value
    .replace(/[<>:"/\\|?*\u0000-\u001F]/g, "-")
    .replace(/[. ]+$/g, "")
    .trim()
    .slice(0, 100) || "repomind-export";
  return stem.toLowerCase().endsWith(extension) ? stem : stem + extension;
}

export function isPathInside(parentPath: string, childPath: string): boolean {
  const relative = path.relative(path.resolve(parentPath), path.resolve(childPath));
  return relative !== "" && relative !== ".." && !relative.startsWith(".." + path.sep) && !path.isAbsolute(relative);
}

function resolveE2eExportPath(fileName: string): string | null {
  if (process.env.REPOMIND_E2E !== "1" || !process.env.REPOMIND_E2E_EXPORT_DIR) return null;
  const userDataPath = fs.realpathSync(app.getPath("userData"));
  const exportDir = path.resolve(process.env.REPOMIND_E2E_EXPORT_DIR);
  if (!isPathInside(userDataPath, exportDir)) {
    throw new Error("E2E 导出目录必须位于当前临时 userData 内。");
  }
  fs.mkdirSync(exportDir, { recursive: true });
  const canonicalExportDir = fs.realpathSync(exportDir);
  if (!isPathInside(userDataPath, canonicalExportDir)) {
    throw new Error("E2E 导出目录不能通过链接离开当前临时 userData。");
  }
  const filePath = path.join(canonicalExportDir, fileName);
  if (!isPathInside(canonicalExportDir, filePath)) {
    throw new Error("E2E 导出文件路径无效。");
  }
  return filePath;
}

// 后端日志只写入当前 Electron userData，且调用方不会把密钥传入本函数。
function logBackend(message: string): void {
  const logPath = path.join(app.getPath("userData"), "repomind-backend-logs.txt");
  const line = "[" + new Date().toISOString() + "] " + message + "\n";
  try {
    fs.mkdirSync(path.dirname(logPath), { recursive: true });
    fs.appendFileSync(logPath, line);
  } catch {
    // 日志失败不能掩盖真正的启动结果。
  }
  console.log(message);
}

export function isCompatibleBackendHealth(
  statusCode: number | undefined,
  health: BackendHealth,
  expectedDatabaseIdentity?: string,
  expectedSessionId?: string,
): boolean {
  const schemaVersion = Number.parseInt(health.database_schema_version || health.schema_version, 10);
  return statusCode === 200
    && health.status === "ok"
    && health.instance_id === EXPECTED_INSTANCE_ID
    && health.api_version === "v1"
    && health.backend_contract_version === EXPECTED_BACKEND_CONTRACT_VERSION
    && Number.isInteger(schemaVersion)
    && schemaVersion >= MIN_BACKEND_SCHEMA_VERSION
    && (!expectedDatabaseIdentity || health.database_identity === expectedDatabaseIdentity)
    && (!expectedSessionId || health.session_id === expectedSessionId);
}

function reserveFreePort(): Promise<number> {
  // 让系统分配空闲高端口，避免误复用 8000 上的其他服务。
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close();
        reject(new Error("无法分配 RepoMind 后端端口。"));
        return;
      }
      const port = address.port;
      server.close((error) => error ? reject(error) : resolve(port));
    });
  });
}

function backendPaths(): { dataDir: string; databasePath: string } {
  const dataDir = path.join(app.getPath("userData"), "backend-data");
  fs.mkdirSync(dataDir, { recursive: true });
  return { dataDir, databasePath: path.join(dataDir, "repomind.sqlite3") };
}

function backendEnvironment(backendRoot: string, port: number, sessionId: string): NodeJS.ProcessEnv {
  const { dataDir, databasePath } = backendPaths();
  return {
    ...process.env,
    PYTHONPATH: backendRoot,
    REPOMIND_PATHS__DATA_DIR: dataDir,
    REPOMIND_PATHS__DATABASE_PATH: databasePath,
    REPOMIND_INSTANCE_ID: EXPECTED_INSTANCE_ID,
    REPOMIND_SESSION_ID: sessionId,
    REPOMIND_API_TOKEN: backendApiToken ?? "",
    REPOMIND_SHUTDOWN_TOKEN: backendShutdownToken ?? "",
    // 后端会在启动时验证这是自己的直接父进程，再以 Windows HANDLE 等待其生命周期。
    REPOMIND_ELECTRON_PARENT_PID: String(process.pid),
    REPOMIND_PORT: String(port),
  };
}

function requestHealth(port: number, timeoutMs = 800): Promise<{ statusCode?: number; health?: BackendHealth }> {
  return new Promise((resolve) => {
    const request = http.get(
      { host: "127.0.0.1", port, path: "/api/v1/health", timeout: timeoutMs },
      (response) => {
        let body = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => { body += chunk; });
        response.on("end", () => {
          try {
            resolve({ statusCode: response.statusCode, health: JSON.parse(body) as BackendHealth });
          } catch {
            resolve({ statusCode: response.statusCode });
          }
        });
      },
    );
    request.on("timeout", () => { request.destroy(); resolve({}); });
    request.on("error", () => resolve({}));
  });
}

async function waitForBackendReady(
  processToWaitFor: childProcess.ChildProcess,
  port: number,
  sessionId: string,
  timeoutMs = 20000,
): Promise<boolean> {
  const { databasePath } = backendPaths();
  const expectedDatabaseIdentity = computeDatabaseIdentity(databasePath);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const probe = await requestHealth(port);
    if (probe.health && isCompatibleBackendHealth(
      probe.statusCode,
      probe.health,
      expectedDatabaseIdentity,
      sessionId,
    )) {
      return true;
    }
    if (!ownsBackendSession(backendProcess, backendSessionId, processToWaitFor, sessionId)) return false;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  return false;
}

async function startBackendImpl(): Promise<BackendStartResult> {
  const { databasePath } = backendPaths();
  const reusableBackend = await revalidateTrackedBackend({
    hasTrackedProcess: backendProcess !== null,
    port: backendPort,
    apiToken: backendApiToken,
    sessionId: backendSessionId,
    expectedDatabaseIdentity: computeDatabaseIdentity(databasePath),
    requestHealth,
    isCompatibleHealth: isCompatibleBackendHealth,
  });
  if (reusableBackend) {
    return { started: true, ...reusableBackend };
  }

  const repoRoot = app.isPackaged
    ? path.dirname(path.dirname(path.dirname(__dirname)))
    : path.join(__dirname, "..", "..", "..");
  const bundledExe = app.isPackaged
    ? path.join(process.resourcesPath, "backend", "repomind-backend.exe")
    : path.join(repoRoot, "backend-dist", "repomind-backend.exe");
  const backendRoot = path.join(repoRoot, "backend");
  const port = await reserveFreePort();
  const sessionId = randomUUID();
  backendApiToken = randomUUID();
  backendShutdownToken = randomUUID();
  const env = backendEnvironment(backendRoot, port, sessionId);

  let spawnedProcess: childProcess.ChildProcess;
  if (app.isPackaged && fs.existsSync(bundledExe)) {
    logBackend("Starting bundled backend: " + bundledExe + " port=" + port);
    spawnedProcess = childProcess.spawn(bundledExe, [], {
      env,
      shell: false,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } else if (app.isPackaged) {
    // 正式发布物绝不能悄悄依赖用户机器上的 Python。
    throw new Error("打包应用缺少后端组件：" + bundledExe);
  } else {
    const launcher = findPythonInterpreter();
    if (!launcher) {
      throw new Error("开发模式未找到 Python，请设置 REPOMIND_PYTHON 或把 Python 加入 PATH。");
    }
    logBackend("Starting development backend via Python: " + launcher.command + " port=" + port);
    spawnedProcess = childProcess.spawn(launcher.command, [...launcher.args, "-m", "service.main"], {
      cwd: backendRoot,
      env,
      shell: false,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
  }

  backendProcess = spawnedProcess;
  backendPort = port;
  backendSessionId = sessionId;
  spawnedProcess.stdout?.on("data", (data) => logBackend("[backend-out] " + data.toString().trim()));
  spawnedProcess.stderr?.on("data", (data) => logBackend("[backend-err] " + data.toString().trim()));
  spawnedProcess.on("error", (error) => {
    logBackend("backend spawn error: " + error.message);
    if (ownsBackendSession(backendProcess, backendSessionId, spawnedProcess, sessionId)) {
      backendProcess = null;
      backendPort = null;
      backendSessionId = null;
      backendApiToken = null;
      backendShutdownToken = null;
    }
  });
  spawnedProcess.on("exit", (code) => {
    logBackend("backend exited with code=" + code);
    // 旧进程晚到的退出事件不能清理后来启动的新会话。
    if (ownsBackendSession(backendProcess, backendSessionId, spawnedProcess, sessionId)) {
      backendProcess = null;
      backendPort = null;
      backendSessionId = null;
      backendApiToken = null;
      backendShutdownToken = null;
    }
  });

  if (!await waitForBackendReady(spawnedProcess, port, sessionId)) {
    await stopBackend();
    throw new Error("后端没有通过 API、Schema、数据库身份和会话身份检查。");
  }
  return { started: true, apiBaseUrl: `http://127.0.0.1:${port}/api/v1`, apiToken: backendApiToken! };
}

const startBackend = createSingleFlight(startBackendImpl);

function findPythonInterpreter(): PythonLauncher | null {
  // Python fallback 只服务开发模式，不写入任何开发者个人绝对路径。
  if (process.env.REPOMIND_PYTHON) return { command: process.env.REPOMIND_PYTHON, args: [] };
  const commands = pythonLauncherCandidates();
  for (const launcher of commands) {
    const result = childProcess.spawnSync(launcher.command, [...launcher.args, "--version"], {
      shell: false,
      stdio: "ignore",
    });
    if (!result.error && result.status === 0) return launcher;
  }
  return null;
}

function requestBackendShutdown(port: number, token: string): Promise<boolean> {
  return new Promise((resolve) => {
    const request = http.request(
      {
        host: "127.0.0.1",
        port,
        path: "/api/v1/runtime/shutdown",
        method: "POST",
        timeout: 1000,
        headers: { "X-RepoMind-Shutdown-Token": token },
      },
      (response) => {
        const accepted = response.statusCode === 202;
        response.resume();
        response.once("end", () => resolve(accepted));
      },
    );
    request.once("timeout", () => { request.destroy(); resolve(false); });
    request.once("error", () => resolve(false));
    request.end();
  });
}

async function stopBackend(): Promise<void> {
  if (stoppingBackend || (!backendProcess && backendPort == null)) return;
  stoppingBackend = true;
  const processToStop = backendProcess;
  try {
    // 只有会话端口和关闭令牌仍在内存中时，才发送可证明归属的优雅退出请求。
    const shutdownAccepted = backendPort != null && backendShutdownToken
      ? await requestBackendShutdown(backendPort, backendShutdownToken)
      : false;
    if (shutdownAccepted) {
      const deadline = Date.now() + 5000;
      while (processToStop?.exitCode === null && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
    }
    if (processToStop?.exitCode === null) {
      // 不能继续证明该 PID 仍属于本次会话时绝不强杀，也不扫描机器上的其他进程。
      logBackend("Backend did not confirm a clean shutdown; leaving the unproven process untouched.");
    }
  } catch {
    // 关闭请求失败时宁可留下待系统回收的进程，也不冒险终止未知 PID。
  } finally {
    const processExited = !processToStop || processToStop.exitCode !== null;
    // 只有观察到本次 ChildProcess 已退出后才清空会话句柄；关闭失败时保留句柄和令牌供后续重试。
    if (processExited && backendProcess === processToStop) {
      backendProcess = null;
      backendPort = null;
      backendSessionId = null;
      backendApiToken = null;
      backendShutdownToken = null;
    }
    stoppingBackend = false;
  }
}

// 内置 Demo 只在用户数据目录生成运行副本；绝不修改打包资源或源码目录。
function prepareDemoRepository(): DemoPrepareResult {
  const repoRoot = path.join(__dirname, "..", "..", "..");
  const sourcePath = app.isPackaged
    ? path.join(process.resourcesPath, "demo", "repomind-demo")
    : path.join(repoRoot, "demo", "repomind-demo");
  const targetPath = path.join(app.getPath("userData"), "demo-workspaces", "repomind-demo-v1");
  const gitPath = path.join(targetPath, ".git");

  if (!fs.existsSync(sourcePath)) {
    throw new Error("内置 Demo 资源缺失：" + sourcePath);
  }
  if (fs.existsSync(gitPath)) {
    return { repoPath: targetPath, created: false };
  }

  // 半成品目录不作为有效 Demo；只清理应用自己管理的版本化目标目录。
  fs.rmSync(targetPath, { recursive: true, force: true });
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.cpSync(sourcePath, targetPath, { recursive: true });

  const gitEnv: NodeJS.ProcessEnv = {
    ...process.env,
    GIT_AUTHOR_NAME: "RepoMind Demo",
    GIT_AUTHOR_EMAIL: "demo@repomind.local",
    GIT_COMMITTER_NAME: "RepoMind Demo",
    GIT_COMMITTER_EMAIL: "demo@repomind.local",
    GIT_AUTHOR_DATE: "2026-01-01T00:00:00Z",
    GIT_COMMITTER_DATE: "2026-01-01T00:00:00Z",
  };
  const runGit = (args: string[]) => childProcess.execFileSync(
    "git",
    args,
    { cwd: targetPath, env: gitEnv, stdio: "ignore" },
  );
  try {
    runGit(["init", "--initial-branch=main"]);
    runGit(["add", "--all"]);
    runGit(["commit", "-m", "Create RepoMind built-in demo"]);
  } catch (error) {
    fs.rmSync(targetPath, { recursive: true, force: true });
    const message = error instanceof Error ? error.message : String(error);
    throw new Error("初始化内置 Demo Git 仓库失败：" + message);
  }
  return { repoPath: targetPath, created: true };
}

export function isAllowedRendererNavigation(currentUrl: string, targetUrl: string): boolean {
  try {
    const current = new URL(currentUrl);
    const target = new URL(targetUrl);
    // 开发模式只允许留在同一个 Vite Origin；打包模式只允许同一个本地 HTML 文件内跳转。
    if (current.protocol === "http:" || current.protocol === "https:") {
      return target.origin === current.origin;
    }
    return current.protocol === "file:"
      && target.protocol === "file:"
      && path.normalize(decodeURIComponent(target.pathname)) === path.normalize(decodeURIComponent(current.pathname));
  } catch {
    return false;
  }
}

function createWindow(): void {
  const { width: workWidth, height: workHeight } = screen.getPrimaryDisplay().workAreaSize;
  const contentWidth = Math.min(1280, Math.max(900, workWidth - 32));
  const contentHeight = Math.min(800, Math.max(640, workHeight - 64));
  mainWindow = new BrowserWindow({
    width: contentWidth,
    height: contentHeight,
    // 小白说明：默认尽量提供 1280×800 内容区，小屏幕会按 Windows 可用工作区自动缩小，避免窗口底部跑出屏幕。
    useContentSize: true,
    title: "RepoMind",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  if (isDev) mainWindow.loadURL("http://localhost:5173");
  else mainWindow.loadFile(path.join(__dirname, "..", "dist-renderer", "index.html"));

  // RepoMind 不需要打开外部窗口；任何 window.open 或 target=_blank 都直接拒绝。
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("will-navigate", (event, targetUrl) => {
    const currentUrl = mainWindow?.webContents.getURL();
    if (!currentUrl || !isAllowedRendererNavigation(currentUrl, targetUrl)) {
      event.preventDefault();
    }
  });
  mainWindow.on("closed", () => { mainWindow = null; });
}

app.whenReady().then(async () => {
  ipcMain.handle("backend:start", () => startBackend());
  ipcMain.handle("backend:stop", async () => { await stopBackend(); return true; });
  ipcMain.handle("demo:prepare", () => prepareDemoRepository());
  ipcMain.handle("export:save-text", async (_event, rawRequest: unknown): Promise<SaveTextResult> => {
    const request = validateSaveTextRequest(rawRequest);
    const kind = request.kind;
    const extension = kind === "json" ? ".json" : ".md";
    const defaultPath = sanitizeExportFileName(request.suggestedName, extension);
    const e2eFilePath = resolveE2eExportPath(defaultPath);
    if (e2eFilePath) {
      fs.writeFileSync(e2eFilePath, request.content, { encoding: "utf8", flag: "w" });
      return { saved: true, fileName: path.basename(e2eFilePath) };
    }
    const result = await dialog.showSaveDialog(mainWindow ?? undefined, {
      title: kind === "json" ? "导出 Trace JSON" : "导出 Markdown 报告",
      defaultPath,
      filters: [{ name: kind === "json" ? "JSON" : "Markdown", extensions: [extension.slice(1)] }],
    });
    if (result.canceled || !result.filePath) return { saved: false };
    fs.writeFileSync(result.filePath, request.content, { encoding: "utf8", flag: "w" });
    return { saved: true, fileName: path.basename(result.filePath) };
  });
  try {
    await startBackend();
    createWindow();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    logBackend("Backend startup failed: " + message);
    dialog.showErrorBox("RepoMind 启动失败", message);
    app.quit();
    return;
  }
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

async function coordinateQuitOnce(): Promise<void> {
  if (quitCoordinationStarted) return;
  quitCoordinationStarted = true;
  await stopBackend();
  if (backendProcess?.exitCode === null) {
    logBackend("Backend remains after the authenticated shutdown attempt; Electron will close without force cleanup.");
  }
  app.quit();
}

app.on("before-quit", (event) => {
  if (quitCoordinationStarted || (!backendProcess && backendPort == null)) return;
  event.preventDefault();
  void coordinateQuitOnce();
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    void coordinateQuitOnce();
  }
});
