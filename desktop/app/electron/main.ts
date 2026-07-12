import { app, BrowserWindow, ipcMain } from "electron";
import * as path from "path";
import * as childProcess from "child_process";
import * as fs from "fs";

let mainWindow: BrowserWindow | null = null;
let backendProcess: childProcess.ChildProcess | null = null;

const isDev = process.env.NODE_ENV === "development";

// Write backend startup logs to a file the user can inspect.
const logPath = path.join(app.getPath("userData"), "repomind-backend-logs.txt");
function logBackend(message: string): void {
  const line = "[" + new Date().toISOString() + "] " + message + "\n";
  try {
    fs.appendFileSync(logPath, line);
  } catch {
    // ignore
  }
  console.log(message);
}

function startBackend(): void {
  if (backendProcess) {
    return;
  }
  // In dev __dirname is dist-electron/, in prod it's inside app.asar
  const repoRoot = app.isPackaged
    ? path.dirname(path.dirname(path.dirname(__dirname)))
    : path.join(__dirname, "..", "..", "..");
  const bundledExe = app.isPackaged
    ? path.join(process.resourcesPath, "backend", "repomind-backend.exe")
    : path.join(repoRoot, "backend-dist", "repomind-backend.exe");
  const backendRoot = path.join(repoRoot, "backend");

  // Prefer the bundled EXE; in dev, fall back to the local Python interpreter.
  if (!app.isPackaged && !fs.existsSync(bundledExe)) {
    const launcher = findPythonInterpreter();
    if (!launcher) {
      logBackend("Failed to locate any Python interpreter. RepoMind backend not started.");
      return;
    }
    logBackend("Starting backend via python: " + launcher + " (cwd=" + backendRoot + ")");
    try {
      backendProcess = childProcess.spawn(launcher, ["-m", "service.main"], {
        cwd: backendRoot,
        env: { ...process.env, PYTHONPATH: backendRoot },
        stdio: ["ignore", "pipe", "pipe"],
      });
      backendProcess.stdout?.on("data", (d) => logBackend("[py-out] " + d.toString().trim()));
      backendProcess.stderr?.on("data", (d) => logBackend("[py-err] " + d.toString().trim()));
      backendProcess.on("error", (err) => logBackend("backend spawn error: " + err.message));
      backendProcess.on("exit", (c) => logBackend("backend exited with code=" + c));
    } catch (err) {
      logBackend("Failed to start python backend: " + (err as Error).message);
    }
    return;
  }

  logBackend("Starting backend via exe: " + bundledExe);
  try {
    backendProcess = childProcess.spawn(bundledExe, [], { stdio: ["ignore", "pipe", "pipe"] });
    backendProcess.on("error", (err) => logBackend("backend spawn error: " + err.message));
  } catch (err) {
    logBackend("Failed to start backend: " + (err as Error).message);
  }
}

function findPythonInterpreter(): string | null {
  // Candidate absolute paths — avoids depending on PATH.
  const candidates: string[] = [];
  if (process.env.REPOMIND_PYTHON) {
    candidates.push(process.env.REPOMIND_PYTHON);
  }
  const gUser = "G:\\计算机科学与技术 软件\\python\\python.exe";
  if (fs.existsSync(gUser)) {
    candidates.push(gUser);
  }
  const localAppData = process.env.LOCALAPPDATA;
  if (localAppData) {
    candidates.push(path.join(localAppData, "Programs", "Python", "Python313", "python.exe"));
    candidates.push(path.join(localAppData, "Programs", "Python", "Python312", "python.exe"));
    candidates.push(path.join(localAppData, "Programs", "Python", "Python311", "python.exe"));
    candidates.push(path.join(localAppData, "Microsoft", "WindowsApps", "python.exe"));
  }
  const sysRoot = process.env.SystemRoot || "C:\\Windows";
  candidates.push(path.join(sysRoot, "py.exe"));

  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return null;
}

function stopBackend(): void {
  if (backendProcess) {
    try {
      if (backendProcess.pid == null) {
        return;
      }
      // Windows: kill the whole process tree to free the 8000 port
      const cmd = 'cmd.exe /c "taskkill /pid ' + backendProcess.pid + ' /t /f"';
      childProcess.execSync(cmd);
    } catch {
      // ignore - backend may have exited on its own
    }
    backendProcess = null;
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

  if (isDev) {
    mainWindow.loadURL("http://localhost:5173");
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "dist-renderer", "index.html"));
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  ipcMain.handle("backend:start", () => {
    startBackend();
    return true;
  });
  ipcMain.handle("backend:stop", () => {
    stopBackend();
    return true;
  });
  startBackend();
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("before-quit", () => {
  stopBackend();
});

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") {
    app.quit();
  }
});
