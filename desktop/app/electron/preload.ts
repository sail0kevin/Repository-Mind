import { contextBridge, ipcRenderer } from "electron";

const desktopBridge = {
  backend: {
    start: () => ipcRenderer.invoke("backend:start") as Promise<{ started: boolean; apiBaseUrl: string }>,
    stop: () => ipcRenderer.invoke("backend:stop"),
  },
};

contextBridge.exposeInMainWorld("repomind", desktopBridge);

export type DesktopBridge = typeof desktopBridge;
