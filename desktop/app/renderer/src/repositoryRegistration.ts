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

/** 只发起一次 ingest；异步任务成功后才读取依赖 active succeeded 快照的资源。 */
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

export interface WorkflowReportRepositoryLoadDependencies {
  setWorkflowReport: (value: unknown) => void;
  setActiveWorkflowSection: (value: string) => void;
  loadRepository: (repoId: string, snapshotId: string) => Promise<void>;
  refreshRepositoryInsights: (repoId: string, snapshotId: string) => Promise<void>;
  loadRepositoryKnowledge: (repoId: string, snapshotId: string) => Promise<void>;
  setRegisterProgress: (value: string) => void;
}

/** 已有索引仓库返回 workflow_report 时只加载报告指向的快照，绝不重复 ingest。 */
export async function loadWorkflowReportRepository(
  response: { response_type: "workflow_report"; repo: { repo_id: string }; sections: Array<{ key: string }>; snapshot_id: string },
  dependencies: WorkflowReportRepositoryLoadDependencies,
): Promise<void> {
  dependencies.setWorkflowReport(response);
  dependencies.setActiveWorkflowSection(response.sections[0]?.key || "");
  await dependencies.loadRepository(response.repo.repo_id, response.snapshot_id);
  await dependencies.refreshRepositoryInsights(response.repo.repo_id, response.snapshot_id);
  await dependencies.loadRepositoryKnowledge(response.repo.repo_id, response.snapshot_id);
  dependencies.setRegisterProgress("索引完成，可以开始浏览 Catalog、问答和代码图谱查询");
}
