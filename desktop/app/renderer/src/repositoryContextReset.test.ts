import { describe, expect, it, vi } from "vitest";

import { beginRepositoryRegistration, createRepositoryContextGuard, resetRepositoryContextState, runRepositoryContextOperation } from "./repositoryContextReset";

describe("仓库上下文切换重置", () => {
  it("仓库或快照选择开始时同步递增代次并淘汰旧令牌", () => {
    const guard = createRepositoryContextGuard();
    const oldRepo = guard.begin("repo-old", "snapshot-old");
    expect(guard.isCurrent(oldRepo)).toBe(true);

    const newRepo = guard.begin("repo-new", null);
    expect(guard.isCurrent(oldRepo)).toBe(false);
    expect(guard.isCurrent(newRepo)).toBe(true);

    const selectedSnapshot = guard.selectSnapshot(newRepo.generation, "repo-new", "snapshot-new");
    expect(guard.isCurrent(newRepo)).toBe(false);
    expect(guard.isCurrent(selectedSnapshot)).toBe(true);
  });

  it("旧仓库 QA 完成后不会回写成功、错误或 finally 状态", async () => {
    const guard = createRepositoryContextGuard();
    const qaContext = guard.begin("repo-old", "snapshot-old");
    let resolveQa!: (value: string) => void;
    const qa = new Promise<string>((resolve) => { resolveQa = resolve; });
    const onSuccess = vi.fn();
    const onError = vi.fn();
    const onFinally = vi.fn();

    const pending = runRepositoryContextOperation(guard, qaContext, () => qa, { onSuccess, onError, onFinally });
    guard.begin("repo-new", "snapshot-new");
    resolveQa("stale answer");
    await pending;

    expect(onSuccess).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
    expect(onFinally).not.toHaveBeenCalled();
  });

  it("旧快照 workflow 完成后不会覆盖新快照报告", async () => {
    const guard = createRepositoryContextGuard();
    const workflowContext = guard.begin("repo", "snapshot-old");
    let resolveWorkflow!: (value: { analysis_id: string }) => void;
    const workflow = new Promise<{ analysis_id: string }>((resolve) => { resolveWorkflow = resolve; });
    const onSuccess = vi.fn();

    const pending = runRepositoryContextOperation(guard, workflowContext, () => workflow, { onSuccess });
    guard.begin("repo", "snapshot-new");
    resolveWorkflow({ analysis_id: "old-report" });
    await pending;

    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("当前上下文操作仍正常提交成功和 finally", async () => {
    const guard = createRepositoryContextGuard();
    const context = guard.begin("repo", "snapshot");
    const onSuccess = vi.fn();
    const onFinally = vi.fn();

    await runRepositoryContextOperation(guard, context, async () => "answer", { onSuccess, onFinally });

    expect(onSuccess).toHaveBeenCalledWith("answer");
    expect(onFinally).toHaveBeenCalledTimes(1);
  });

  it("注册开始同时失效旧请求、清除 loading/导出/回答状态并失效代码图请求", () => {
    const guard = createRepositoryContextGuard();
    const stale = guard.begin("repo-old", "snapshot-old");
    const resetters = {
      setWorkflowReport: vi.fn(), setActiveWorkflowSection: vi.fn(), setAnswer: vi.fn(),
      setEvidence: vi.fn(), setEvidenceSnapshotId: vi.fn(), setSelectedChunk: vi.fn(),
      setSelectedTrace: vi.fn(), setIsEvidenceDrawerOpen: vi.fn(), setCollaborateResult: vi.fn(),
      setDebateMessages: vi.fn(), setIsAsking: vi.fn(), setIsDebating: vi.fn(),
      setExportStatus: vi.fn(), setAgentsIdle: vi.fn(), setError: vi.fn(),
    };
    const invalidateCodeGraph = vi.fn();
    const invalidateKnowledgeRequest = vi.fn();

    const registration = beginRepositoryRegistration({ guard, resetters, invalidateCodeGraph, invalidateKnowledgeRequest });

    expect(guard.isCurrent(stale)).toBe(false);
    expect(guard.isCurrent(registration)).toBe(true);
    expect(registration).toMatchObject({ repoId: null, snapshotId: null });
    expect(resetters.setIsAsking).toHaveBeenCalledWith(false);
    expect(resetters.setIsDebating).toHaveBeenCalledWith(false);
    expect(resetters.setExportStatus).toHaveBeenCalledWith("");
    expect(resetters.setAnswer).toHaveBeenCalledWith(null);
    expect(resetters.setEvidence).toHaveBeenCalledWith([]);
    expect(resetters.setWorkflowReport).toHaveBeenCalledWith(null);
    expect(resetters.setSelectedTrace).toHaveBeenCalledWith(null);
    expect(resetters.setAgentsIdle).toHaveBeenCalledTimes(1);
    expect(invalidateCodeGraph).toHaveBeenCalledTimes(1);
    expect(invalidateKnowledgeRequest).toHaveBeenCalledTimes(1);
  });

  it("在加载新知识前清空全部旧工作流和抽屉状态", () => {
    const resetters = {
      setWorkflowReport: vi.fn(),
      setActiveWorkflowSection: vi.fn(),
      setAnswer: vi.fn(),
      setEvidence: vi.fn(),
      setEvidenceSnapshotId: vi.fn(),
      setSelectedChunk: vi.fn(),
      setSelectedTrace: vi.fn(),
      setIsEvidenceDrawerOpen: vi.fn(),
      setCollaborateResult: vi.fn(),
      setDebateMessages: vi.fn(),
      setIsAsking: vi.fn(),
      setIsDebating: vi.fn(),
      setExportStatus: vi.fn(),
      setAgentsIdle: vi.fn(),
      setError: vi.fn(),
    };

    resetRepositoryContextState(resetters);

    expect(resetters.setWorkflowReport).toHaveBeenCalledWith(null);
    expect(resetters.setActiveWorkflowSection).toHaveBeenCalledWith("");
    expect(resetters.setAnswer).toHaveBeenCalledWith(null);
    expect(resetters.setEvidence).toHaveBeenCalledWith([]);
    expect(resetters.setEvidenceSnapshotId).toHaveBeenCalledWith(null);
    expect(resetters.setSelectedChunk).toHaveBeenCalledWith(null);
    expect(resetters.setSelectedTrace).toHaveBeenCalledWith(null);
    expect(resetters.setIsEvidenceDrawerOpen).toHaveBeenCalledWith(false);
    expect(resetters.setCollaborateResult).toHaveBeenCalledWith(null);
    expect(resetters.setDebateMessages).toHaveBeenCalledWith([]);
    expect(resetters.setIsAsking).toHaveBeenCalledWith(false);
    expect(resetters.setIsDebating).toHaveBeenCalledWith(false);
    expect(resetters.setExportStatus).toHaveBeenCalledWith("");
    expect(resetters.setAgentsIdle).toHaveBeenCalledTimes(1);
    expect(resetters.setError).toHaveBeenCalledWith(null);
  });
});
