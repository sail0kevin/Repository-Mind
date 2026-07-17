import { contextBridge, ipcRenderer } from "electron";
import type { DesktopBridge } from "./bridgeContract";

const desktopBridge: DesktopBridge = {
  backend: {
    start: () => ipcRenderer.invoke("backend:start"),
    stop: () => ipcRenderer.invoke("backend:stop"),
  },
  demo: {
    prepare: () => ipcRenderer.invoke("demo:prepare"),
  },
  export: {
    saveText: (request) => ipcRenderer.invoke("export:save-text", request),
  },
};

contextBridge.exposeInMainWorld("repomind", desktopBridge);

export type { DesktopBridge } from "./bridgeContract";
