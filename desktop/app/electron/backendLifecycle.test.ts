import { describe, expect, it, vi } from "vitest";
import * as path from "path";
import { createHash } from "crypto";

import { canonicalDatabasePath, computeDatabaseIdentity, createSingleFlight, ownsBackendSession, pythonLauncherCandidates, revalidateTrackedBackend } from "./backendLifecycle";

describe("Electron 后端生命周期辅助函数", () => {
  it("数据库身份使用规范化真实路径的 UTF-8 SHA-256", () => {
    const databasePath = path.join(process.cwd(), "backend-data", "repomind.sqlite3");
    const expected = createHash("sha256").update(canonicalDatabasePath(databasePath), "utf8").digest("hex");
    expect(computeDatabaseIdentity(databasePath)).toBe(expected);
  });

  it("Windows 规范路径统一分隔符和大小写", () => {
    const canonical = canonicalDatabasePath(path.join(process.cwd(), "backend-data", "RepoMind.SQLite3"), "win32");
    expect(canonical).not.toMatch(/\\/);
    expect(canonical).toBe(canonical.toLowerCase());
  });

  it("Windows 开发启动只选择直接 python.exe，不经过 py launcher", () => {
    expect(pythonLauncherCandidates("win32", undefined)).toEqual([{ command: "python", args: [] }]);
    expect(pythonLauncherCandidates("win32", "C:\\Python311\\python.exe"))
      .toEqual([{ command: "C:\\Python311\\python.exe", args: [] }]);
  });

  it("并发启动调用共享同一个进行中的 Promise", async () => {
    let release!: (value: string) => void;
    const startImpl = vi.fn(() => new Promise<string>((resolve) => { release = resolve; }));
    const start = createSingleFlight(startImpl);

    const first = start();
    const second = start();
    expect(first).toBe(second);
    expect(startImpl).toHaveBeenCalledTimes(1);

    release("ready");
    await expect(first).resolves.toBe("ready");
    await Promise.resolve();
    const third = start();
    expect(third).not.toBe(first);
    expect(startImpl).toHaveBeenCalledTimes(2);
  });

  it("健康且数据库与会话身份一致时才复用已跟踪子进程", async () => {
    const requestHealth = vi.fn().mockResolvedValue({ statusCode: 200, health: { marker: "healthy" } });
    const isCompatibleHealth = vi.fn().mockReturnValue(true);

    await expect(revalidateTrackedBackend({
      hasTrackedProcess: true,
      port: 43123,
      apiToken: "api-token",
      sessionId: "session-current",
      expectedDatabaseIdentity: "database-current",
      requestHealth,
      isCompatibleHealth,
    })).resolves.toEqual({
      apiBaseUrl: "http://127.0.0.1:43123/api/v1",
      apiToken: "api-token",
    });
    expect(isCompatibleHealth).toHaveBeenCalledWith(
      200,
      { marker: "healthy" },
      "database-current",
      "session-current",
    );
  });

  it("已跟踪子进程无响应或身份不匹配时拒绝复用且不提供 URL", async () => {
    const requestHealth = vi.fn().mockResolvedValue({ statusCode: 200, health: { marker: "wrong-session" } });

    await expect(revalidateTrackedBackend({
      hasTrackedProcess: true,
      port: 43123,
      apiToken: "api-token",
      sessionId: "session-current",
      expectedDatabaseIdentity: "database-current",
      requestHealth,
      isCompatibleHealth: vi.fn().mockReturnValue(false),
    })).rejects.toThrow("无响应或数据库/会话身份不匹配");
    expect(requestHealth).toHaveBeenCalledTimes(1);
  });

  it("已跟踪子进程元数据不完整时拒绝再次启动且不探测其他进程", async () => {
    const requestHealth = vi.fn();

    await expect(revalidateTrackedBackend({
      hasTrackedProcess: true,
      port: 43123,
      apiToken: "api-token",
      sessionId: null,
      expectedDatabaseIdentity: "database-current",
      requestHealth,
      isCompatibleHealth: vi.fn(),
    })).rejects.toThrow("所有权尚未释放");
    expect(requestHealth).not.toHaveBeenCalled();
  });

  it("没有已跟踪子进程时允许调用方进入正常启动路径", async () => {
    await expect(revalidateTrackedBackend({
      hasTrackedProcess: false,
      port: null,
      apiToken: null,
      sessionId: null,
      expectedDatabaseIdentity: "database-current",
      requestHealth: vi.fn(),
      isCompatibleHealth: vi.fn(),
    })).resolves.toBeNull();
  });

  it("旧进程或旧会话事件不能清理当前后端状态", () => {
    const current = {};
    const old = {};
    expect(ownsBackendSession(current, "session-new", current, "session-new")).toBe(true);
    expect(ownsBackendSession(current, "session-new", old, "session-old")).toBe(false);
    expect(ownsBackendSession(current, "session-new", current, "session-old")).toBe(false);
  });
});
