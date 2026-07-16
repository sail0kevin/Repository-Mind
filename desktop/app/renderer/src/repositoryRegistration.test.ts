import { describe, expect, it, vi } from "vitest";

import { ingestThenLoadRepository } from "./repositoryRegistration";

describe("ingestThenLoadRepository", () => {
  it("注册后的真实顺序是 ingest、任务成功、文件加载，且只发起一次 ingest", async () => {
    const events: string[] = [];
    const ingestRepository = vi.fn(async () => {
      events.push("ingest");
      return { job_id: "job-1" };
    });
    const pollIngestJob = vi.fn(async () => { events.push("succeeded"); });
    const loadRepository = vi.fn(async () => { events.push("files"); });
    const refreshRepositoryInsights = vi.fn(async () => { events.push("insights"); });

    await ingestThenLoadRepository("repo-1", {
      ingestRepository,
      pollIngestJob,
      loadRepository,
      refreshRepositoryInsights,
    });

    expect(ingestRepository).toHaveBeenCalledTimes(1);
    expect(pollIngestJob).toHaveBeenCalledWith("job-1", "repo-1");
    expect(events).toEqual(["ingest", "succeeded", "files", "insights"]);
  });

  it("同步完成的 ingest 不重复调用而直接加载文件", async () => {
    const ingestRepository = vi.fn(async () => ({ job_id: null }));
    const pollIngestJob = vi.fn();
    const loadRepository = vi.fn();
    const refreshRepositoryInsights = vi.fn();

    await ingestThenLoadRepository("repo-1", {
      ingestRepository,
      pollIngestJob,
      loadRepository,
      refreshRepositoryInsights,
    });

    expect(ingestRepository).toHaveBeenCalledTimes(1);
    expect(pollIngestJob).not.toHaveBeenCalled();
    expect(loadRepository).toHaveBeenCalledWith("repo-1");
    expect(refreshRepositoryInsights).toHaveBeenCalledWith("repo-1");
  });
});
