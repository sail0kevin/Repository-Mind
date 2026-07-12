import { app, BrowserWindow, ipcMain } from "electron";
import * as path from "path";
import * as childProcess from "child_process";

let mainWindow: BrowserWindow | null = null;
let backendProcess: childProcess.ChildProcess | null = null;

const isDev = process.env.NODE_ENV === "development";

function startBackend(): void {
  if (backendProcess) {
    return;
  }
  const bundledExe = app.isPackaged
    ? path.join(process.resourcesPath, "backend", "repomind-backend.exe")
    : path.join(__dirname, "..", "..", "backend-dist", "repomind-backend.exe");
  const backendRoot = path.join(__dirname, "..", "..");

  // Prefer the bundled EXE; in dev, fall back to the local Python interpreter.
  if (!app.isPackaged && !require("fs").existsSync(bundledExe)) {
    const launcher = findPythonInterpreter();
    if (!launcher) {
      console.error("Failed to locate a Python interpreter for backend.");
      return;
    }
    try {
      backendProcess = childProcess.spawn(
        launcher,
        ["-m", "service.main"],
        { cwd: backendRoot, env: { ...process.env, PYTHONPATH: backendRoot }, stdio: "ignore" },
      );
      backendProcess.on("error", (err) => console.error("backend spawn error:", err));
    } catch (err) {
      console.error("Failed to start python backend:", err);
    }
    return;
  }

  try {
    backendProcess = childProcess.spawn(bundledExe, [], { stdio: "ignore" });
  } catch (err) {
    console.error("Failed to start backend:", err);
  }
}

function findPythonInterpreter(): string | null {
  // Candidate absolute paths — avoids depending on PATH.
  const candidates: string[] = [];
  if (process.env.REPOMIND_PYTHON) {
    candidates.push(process.env.REPOMIND_PYTHON);
  }
  const gUser = "G:\\计算机科学与技术 软件\\python\\python.exe";
  if (require("fs").existsSync(gUser)) {
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
    if (candidate && require("fs").existsSync(candidate)) {
      return candidate;
    }
  }
  return null;
}

function stopBackend(): void {
  if (backendProcess) {
    try {
      // Windows: kill the whole process tree to free the 8000 port
      childProcess.execSync(`taskkill /pid ${backendProcess.pid} /t /f`);
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
