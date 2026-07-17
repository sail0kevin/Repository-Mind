/** Electron 主进程、preload 和 renderer 共同使用的桌面桥契约。 */
export type ExportKind = "markdown" | "json";

export interface BackendStartResult {
  started: boolean;
  apiBaseUrl: string;
  apiToken: string;
}

export interface DemoPrepareResult {
  repoPath: string;
  created: boolean;
}

export interface SaveTextRequest {
  suggestedName: string;
  content: string;
  kind: ExportKind;
}

export interface SaveTextResult {
  saved: boolean;
  fileName?: string;
}

export interface DesktopBridge {
  backend: {
    start: () => Promise<BackendStartResult>;
    stop: () => Promise<unknown>;
  };
  demo: {
    prepare: () => Promise<DemoPrepareResult>;
  };
  export: {
    saveText: (request: SaveTextRequest) => Promise<SaveTextResult>;
  };
}
