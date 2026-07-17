import { createHash } from "crypto";
import * as fs from "fs";
import * as path from "path";

/**
 * 与 Python 后端共享的数据库身份规范：非严格 realpath 解析链接/联接，统一为 /，
 * Windows 再转小写，最后对 UTF-8 字节计算 SHA-256。
 */
export function canonicalDatabasePath(databasePath: string, platform: NodeJS.Platform = process.platform): string {
  const absolutePath = path.resolve(databasePath);
  let canonicalPath: string;
  try {
    canonicalPath = fs.realpathSync.native(absolutePath);
  } catch {
    try {
      canonicalPath = fs.realpathSync.native(path.dirname(absolutePath)) + path.sep + path.basename(absolutePath);
    } catch {
      canonicalPath = absolutePath;
    }
  }
  const normalizedPath = canonicalPath.replace(/\\/g, "/");
  return platform === "win32" ? normalizedPath.toLowerCase() : normalizedPath;
}

export function computeDatabaseIdentity(databasePath: string): string {
  return createHash("sha256").update(canonicalDatabasePath(databasePath), "utf8").digest("hex");
}

export interface PythonLauncher { command: string; args: string[]; }

/** Windows 开发模式必须直接启动 python.exe，避免 py.exe 中间层破坏后端的直接父进程所有权校验。 */
export function pythonLauncherCandidates(
  platform: NodeJS.Platform = process.platform,
  configuredPython = process.env.REPOMIND_PYTHON,
): PythonLauncher[] {
  if (configuredPython) return [{ command: configuredPython, args: [] }];
  return platform === "win32"
    ? [{ command: "python", args: [] }]
    : [{ command: "python3", args: [] }, { command: "python", args: [] }];
}

/**
 * 把异步启动函数包装成单航班调用：同一时刻的所有调用共享一个 Promise，
 * 只有该 Promise 自己结束时才释放锁，避免旧调用清掉新一轮启动状态。
 */
export function createSingleFlight<T>(start: () => Promise<T>): () => Promise<T> {
  let inFlight: Promise<T> | null = null;
  return () => {
    if (inFlight) return inFlight;
    const current = start();
    inFlight = current;
    void current.finally(() => {
      if (inFlight === current) inFlight = null;
    }).catch(() => {
      // 调用方收到原始拒绝；这里仅消费 finally() 派生 Promise，避免未处理拒绝。
    });
    return current;
  };
}

export interface TrackedBackendReuseOptions<THealth> {
  hasTrackedProcess: boolean;
  port: number | null;
  apiToken: string | null;
  sessionId: string | null;
  expectedDatabaseIdentity: string;
  requestHealth: (port: number) => Promise<{ statusCode?: number; health?: THealth }>;
  isCompatibleHealth: (
    statusCode: number | undefined,
    health: THealth,
    expectedDatabaseIdentity: string,
    expectedSessionId: string,
  ) => boolean;
}

/**
 * 已跟踪子进程的所有权尚未由 exit/error 事件释放时，只能复核并复用它。
 * 元数据缺失、健康接口无响应或身份不匹配都必须报错，不能返回旧 URL，也不能再拉起第二个进程。
 */
export async function revalidateTrackedBackend<THealth>(
  options: TrackedBackendReuseOptions<THealth>,
): Promise<{ apiBaseUrl: string; apiToken: string } | null> {
  if (!options.hasTrackedProcess) return null;
  if (!options.port || !options.apiToken || !options.sessionId) {
    throw new Error("已跟踪的 RepoMind 后端所有权尚未释放，但启动元数据不完整；为避免重复进程，已拒绝再次启动。");
  }

  const probe = await options.requestHealth(options.port);
  if (!probe.health || !options.isCompatibleHealth(
    probe.statusCode,
    probe.health,
    options.expectedDatabaseIdentity,
    options.sessionId,
  )) {
    throw new Error("已跟踪的 RepoMind 后端无响应或数据库/会话身份不匹配；为避免重复进程，已拒绝再次启动。");
  }

  return {
    apiBaseUrl: `http://127.0.0.1:${options.port}/api/v1`,
    apiToken: options.apiToken,
  };
}

/** 旧 ChildProcess 的事件只能修改它自己所属的会话，不能清掉后启动的新会话。 */
export function ownsBackendSession<T>(
  trackedProcess: T | null,
  trackedSessionId: string | null,
  eventProcess: T,
  eventSessionId: string,
): boolean {
  return trackedProcess === eventProcess && trackedSessionId === eventSessionId;
}
