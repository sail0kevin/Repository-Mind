import { contextBridge, ipcRenderer } from "electron";

const desktopBridge = {
  backend: {
    start: () => ipcRenderer.invoke("backend:start") as Promise<{ started: boolean; apiBaseUrl: string }>,
    stop: () => ipcRenderer.invoke("backend:stop"),
  },
  demo: {
    prepare: () => ipcRenderer.invoke("demo:prepare") as Promise<{ repoPath: string; created: boolean }>,
  },
  export: {
    saveText: (request: { suggestedName: string; content: string; kind: "markdown" | "json" }) =>
      ipcRenderer.invoke("export:save-text", request) as Promise<{ saved: boolean; fileName?: string }>,
  },
};

contextBridge.exposeInMainWorld("repomind", desktopBridge);

export type DesktopBridge = typeof desktopBridge;
