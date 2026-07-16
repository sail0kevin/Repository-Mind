/**
 * 注册完成后的首次索引流程。
 *
 * 新仓库尚没有 succeeded 快照，不能在启动索引前请求 files；这个小模块
 * 让界面和测试共享同一条严格的“索引 -> 成功 -> 加载”顺序。
 */
export interface IngestStartResult {
  job_id: string | null;
}

export interface InitialRepositoryLoadDependencies {
  ingestRepository: (repoId: string) => Promise<IngestStartResult>;
  pollIngestJob: (jobId: string, repoId: string) => Promise<void>;
  loadRepository: (repoId: string) => Promise<void>;
  refreshRepositoryInsights: (repoId: string) => Promise<void>;
}

/**
 * 只发起一次 ingest；异步任务成功后才读取依赖 active succeeded 快照的资源。
 * 没有 job_id 时后端已经同步完成，所以也可以直接加载。
 */
export async function ingestThenLoadRepository(
  repoId: string,
  dependencies: InitialRepositoryLoadDependencies,
): Promise<void> {
  const ingest = await dependencies.ingestRepository(repoId);
  if (ingest.job_id) {
    await dependencies.pollIngestJob(ingest.job_id, repoId);
  }
  await dependencies.loadRepository(repoId);
  await dependencies.refreshRepositoryInsights(repoId);
}
