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

// productName 只控制显示名称；用户数据目录必须始终沿用历史 package name，防止升级后出现一套空数据库。
app.setPath("userData", path.join(app.getPath("appData"), USER_DATA_BASENAME));
app.setAppUserModelId(APP_ID);

let mainWindow: BrowserWindow | null = null;
let backendProcess: childProcess.ChildProcess | null = null;
let backendPort: number | null = null;
let backendSessionId: string | null = null;
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
  const env = backendEnvironment(backendRoot, port, sessionId);

  if (fs.existsSync(bundledExe)) {
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

  backendPort = port;
  backendSessionId = sessionId;
  backendProcess.stdout?.on("data", (data) => logBackend("[backend-out] " + data.toString().trim()));
  backendProcess.stderr?.on("data", (data) => logBackend("[backend-err] " + data.toString().trim()));
  backendProcess.on("error", (error) => logBackend("backend spawn error: " + error.message));
  backendProcess.on("exit", (code) => {
    logBackend("backend exited with code=" + code);
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

async function stopBackend(): Promise<void> {
  if (stoppingBackend || !backendProcess || backendProcess.pid == null) return;
  stoppingBackend = true;
  const processToStop = backendProcess;
  try {
    // 先请求普通终止，给 SQLite 一次正常关闭机会；超时后才清理进程树。
    processToStop.kill("SIGTERM");
    const deadline = Date.now() + 3000;
    while (!processToStop.killed && processToStop.exitCode === null && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (process.platform === "win32" && processToStop.pid != null) {
      // PyInstaller 单文件后端可能派生子进程；即使启动器已退出，也要尝试清理其原进程树。
      try {
        childProcess.execFileSync(
          "taskkill",
          ["/pid", String(processToStop.pid), "/t", "/f"],
          { stdio: "ignore" },
        );
      } catch {
        // taskkill 在进程已完全退出时会返回非零，此时无需继续处理。
      }
    } else if (processToStop.exitCode === null) {
      processToStop.kill("SIGKILL");
    }
  } catch {
    // 进程可能已经自行退出。
  } finally {
    if (backendProcess === processToStop) backendProcess = null;
    backendPort = null;
    backendSessionId = null;
    stoppingBackend = false;
  }
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

app.on("before-quit", () => { void stopBackend(); });
app.on("window-all-closed", () => {
  void stopBackend().finally(() => { if (process.platform !== "darwin") app.quit(); });
});
