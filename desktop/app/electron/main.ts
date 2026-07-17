import { app, BrowserWindow, dialog, ipcMain } from "electron";
import * as path from "path";
import * as childProcess from "child_process";
import * as fs from "fs";
import * as http from "http";
import * as net from "net";
import { randomUUID } from "crypto";

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
let backendProcessId: number | null = null;
let backendPort: number | null = null;
let backendSessionId: string | null = null;
let backendShutdownToken: string | null = null;
let stoppingBackend = false;
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
  database_path: string;
}

interface BackendStartResult {
  started: boolean;
  apiBaseUrl: string;
}

interface SaveTextRequest {
  suggestedName: string;
  content: string;
  kind: "markdown" | "json";
}

interface SaveTextResult {
  saved: boolean;
  fileName?: string;
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

function normalizedPath(value: string): string {
  return path.resolve(value).replace(/\//g, "\\").toLowerCase();
}

export function isCompatibleBackendHealth(
  statusCode: number | undefined,
  health: BackendHealth,
  expectedDatabasePath?: string,
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
    && (!expectedDatabasePath || normalizedPath(health.database_path) === normalizedPath(expectedDatabasePath))
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
    REPOMIND_SHUTDOWN_TOKEN: backendShutdownToken ?? "",
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

async function waitForBackendReady(port: number, sessionId: string, timeoutMs = 20000): Promise<boolean> {
  const { databasePath } = backendPaths();
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const probe = await requestHealth(port);
    if (probe.health && isCompatibleBackendHealth(probe.statusCode, probe.health, databasePath, sessionId)) {
      return true;
    }
    if (!backendProcess) return false;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  return false;
}

async function startBackend(): Promise<BackendStartResult> {
  if (backendProcess && backendPort) {
    return { started: true, apiBaseUrl: `http://127.0.0.1:${backendPort}/api/v1` };
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
  backendShutdownToken = randomUUID();
  const env = backendEnvironment(backendRoot, port, sessionId);

  if (app.isPackaged && fs.existsSync(bundledExe)) {
    logBackend("Starting bundled backend: " + bundledExe + " port=" + port);
    backendProcess = childProcess.spawn(bundledExe, [], {
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
    backendProcess = childProcess.spawn(launcher.command, [...launcher.args, "-m", "service.main"], {
      cwd: backendRoot,
      env,
      shell: false,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
  }

  backendProcessId = backendProcess.pid ?? null;
  backendPort = port;
  backendSessionId = sessionId;
  backendProcess.stdout?.on("data", (data) => logBackend("[backend-out] " + data.toString().trim()));
  backendProcess.stderr?.on("data", (data) => logBackend("[backend-err] " + data.toString().trim()));
  backendProcess.on("error", (error) => logBackend("backend spawn error: " + error.message));
  backendProcess.on("exit", (code) => {
    logBackend("backend exited with code=" + code);
    // PyInstaller 启动器退出后可能仍有同 PID 的后端进程存活，PID 只由 stopBackend 最终清空。
    backendProcess = null;
    backendPort = null;
    backendSessionId = null;
  });

  if (!await waitForBackendReady(port, sessionId)) {
    await stopBackend();
    throw new Error("后端没有通过 API、Schema、数据库路径和会话身份检查。");
  }
  return { started: true, apiBaseUrl: `http://127.0.0.1:${port}/api/v1` };
}

interface PythonLauncher { command: string; args: string[]; }

function findPythonInterpreter(): PythonLauncher | null {
  // Python fallback 只服务开发模式，不写入任何开发者个人绝对路径。
  if (process.env.REPOMIND_PYTHON) return { command: process.env.REPOMIND_PYTHON, args: [] };
  const commands: PythonLauncher[] = process.platform === "win32"
    ? [{ command: "py", args: ["-3"] }, { command: "python", args: [] }]
    : [{ command: "python3", args: [] }, { command: "python", args: [] }];
  for (const launcher of commands) {
    const result = childProcess.spawnSync(launcher.command, [...launcher.args, "--version"], {
      shell: false,
      stdio: "ignore",
    });
    if (!result.error && result.status === 0) return launcher;
  }
  return null;
}

function stopWindowsProcess(processId: number): void {
  // 只终止 Electron 启动并记录的后端 PID，不递归处理任何父子进程。
  try {
    childProcess.execFileSync(
      "powershell",
      [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        `Stop-Process -Id ${processId} -Force -ErrorAction SilentlyContinue`,
      ],
      { stdio: "ignore", timeout: 15_000 },
    );
  } catch {
    // 目标进程已经退出时无需继续处理。
  }
}

function requestBackendShutdown(port: number, token: string): Promise<void> {
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
        response.resume();
        response.once("end", resolve);
      },
    );
    request.once("timeout", () => { request.destroy(); resolve(); });
    request.once("error", () => resolve());
    request.end();
  });
}

async function stopBackend(): Promise<void> {
  if (stoppingBackend || (!backendProcess && backendProcessId == null)) return;
  stoppingBackend = true;
  const processToStop = backendProcess;
  const processId = processToStop?.pid ?? backendProcessId;
  try {
    if (backendProcess && backendPort && backendShutdownToken) {
      await requestBackendShutdown(backendPort, backendShutdownToken);
    }
    const deadline = Date.now() + 3000;
    while (processToStop && !processToStop.killed && processToStop.exitCode === null && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (process.platform === "win32" && processId != null) {
      stopWindowsProcess(processId);
    } else if (processToStop?.exitCode === null) {
      processToStop.kill("SIGKILL");
    }
  } catch {
    // 进程可能已经自行退出。
  } finally {
    if (backendProcess === processToStop) backendProcess = null;
    backendProcessId = null;
    backendPort = null;
    backendSessionId = null;
    backendShutdownToken = null;
    stoppingBackend = false;
  }
}

interface DemoPrepareResult {
  repoPath: string;
  created: boolean;
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

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    title: "RepoMind",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  if (isDev) mainWindow.loadURL("http://localhost:5173");
  else mainWindow.loadFile(path.join(__dirname, "..", "dist-renderer", "index.html"));
  mainWindow.on("closed", () => { mainWindow = null; });
}

app.whenReady().then(async () => {
  ipcMain.handle("backend:start", () => startBackend());
  ipcMain.handle("backend:stop", async () => { await stopBackend(); return true; });
  ipcMain.handle("demo:prepare", () => prepareDemoRepository());
  ipcMain.handle("export:save-text", async (_event, request: SaveTextRequest): Promise<SaveTextResult> => {
    if (!request || typeof request.content !== "string" || request.content.length > 10 * 1024 * 1024) {
      throw new Error("导出内容无效或超过 10 MB 限制。");
    }
    const kind = request.kind === "json" ? "json" : "markdown";
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

app.on("before-quit", (event) => {
  if (stoppingBackend || backendProcessId == null) return;
  event.preventDefault();
  void stopBackend().finally(() => app.quit());
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    void stopBackend().finally(() => app.quit());
  }
});
