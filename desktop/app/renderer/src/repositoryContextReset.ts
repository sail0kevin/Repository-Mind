export interface RepositoryContextToken {
  generation: number;
  repoId: string | null;
  snapshotId: string | null;
}

export interface RepositoryContextGuard {
  begin: (repoId: string | null, snapshotId?: string | null) => RepositoryContextToken;
  selectSnapshot: (generation: number, repoId: string, snapshotId: string | null) => RepositoryContextToken;
  capture: (repoId: string | null, snapshotId: string | null) => RepositoryContextToken;
  isCurrent: (token: RepositoryContextToken) => boolean;
}

/** 为仓库/快照异步操作提供同步递增的上下文代次，阻止旧请求回写新界面。 */
export function createRepositoryContextGuard(): RepositoryContextGuard {
  let current: RepositoryContextToken = { generation: 0, repoId: null, snapshotId: null };
  return {
    begin(repoId, snapshotId = null) {
      current = { generation: current.generation + 1, repoId, snapshotId };
      return { ...current };
    },
    selectSnapshot(generation, repoId, snapshotId) {
      if (current.generation === generation && current.repoId === repoId) {
        current = { generation, repoId, snapshotId };
      }
      return { ...current };
    },
    capture(repoId, snapshotId) {
      return { generation: current.generation, repoId, snapshotId };
    },
    isCurrent(token) {
      return token.generation === current.generation
        && token.repoId === current.repoId
        && token.snapshotId === current.snapshotId;
    },
  };
}

export async function runRepositoryContextOperation<T>(
  guard: RepositoryContextGuard,
  token: RepositoryContextToken,
  operation: () => Promise<T>,
  handlers: {
    onSuccess: (value: T) => void;
    onError?: (error: unknown) => void;
    onFinally?: () => void;
  },
): Promise<void> {
  try {
    const value = await operation();
    if (guard.isCurrent(token)) handlers.onSuccess(value);
  } catch (error) {
    if (guard.isCurrent(token)) handlers.onError?.(error);
  } finally {
    if (guard.isCurrent(token)) handlers.onFinally?.();
  }
}

export interface RepositoryRegistrationResetOptions {
  guard: RepositoryContextGuard;
  resetters: RepositoryContextResetters;
  invalidateCodeGraph: () => void;
  invalidateKnowledgeRequest: () => void;
}

/** 注册新来源前同步失效全部旧异步上下文，并清除会卡住界面的工作流状态。 */
export function beginRepositoryRegistration(options: RepositoryRegistrationResetOptions): RepositoryContextToken {
  const token = options.guard.begin(null, null);
  resetRepositoryContextState(options.resetters);
  options.invalidateCodeGraph();
  options.invalidateKnowledgeRequest();
  return token;
}

export interface RepositoryContextResetters {
  setWorkflowReport: (value: null) => void;
  setActiveWorkflowSection: (value: string) => void;
  setAnswer: (value: null) => void;
  setEvidence: (value: never[]) => void;
  setEvidenceSnapshotId: (value: null) => void;
  setSelectedChunk: (value: null) => void;
  setSelectedTrace: (value: null) => void;
  setIsEvidenceDrawerOpen: (value: boolean) => void;
  setCollaborateResult: (value: null) => void;
  setDebateMessages: (value: never[]) => void;
  setIsAsking: (value: boolean) => void;
  setIsDebating: (value: boolean) => void;
  setExportStatus: (value: string) => void;
  setAgentsIdle: () => void;
  setError: (value: null) => void;
}

/** 在任何异步知识加载开始前，同步清除属于旧仓库或旧快照的工作流状态。 */
export function resetRepositoryContextState(resetters: RepositoryContextResetters): void {
  resetters.setWorkflowReport(null);
  resetters.setActiveWorkflowSection("");
  resetters.setAnswer(null);
  resetters.setEvidence([]);
  resetters.setEvidenceSnapshotId(null);
  resetters.setSelectedChunk(null);
  resetters.setSelectedTrace(null);
  resetters.setIsEvidenceDrawerOpen(false);
  resetters.setCollaborateResult(null);
  resetters.setDebateMessages([]);
  resetters.setIsAsking(false);
  resetters.setIsDebating(false);
  resetters.setExportStatus("");
  resetters.setAgentsIdle();
  resetters.setError(null);
}
