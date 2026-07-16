/**
 * RepoMind 前端 API 客户端。
 * 这里集中处理请求地址、FastAPI 错误格式和任务进度，避免各个页面重复拼装。
 */
export interface HealthResponse { status: "ok"; app_name: string; app_version: string; api_version: string; schema_version: string; instance_id: string; database_path: string; }
export interface CodeGraphStatsResponse { repo_id: string; snapshot_id: string; total_nodes: number; total_edges: number; functions: number; classes: number; files_analyzed: number; diagnostics: Record<string, unknown> | unknown[]; }
export interface CodeGraphNodeResponse { id: string; name: string; node_type: string; file_path: string; start_line: number | null; end_line: number | null; signature: string | null; importance: number; }
export interface CodeGraphSearchResponse { repo_id: string; snapshot_id: string; query: string; matches: CodeGraphNodeResponse[]; }
export interface CodeGraphImportantResponse { repo_id: string; snapshot_id: string; nodes: CodeGraphNodeResponse[]; }
export interface CodeGraphEdgeResponse { source_id: string; target_id: string; edge_type: string; depth: number; }
export interface CodeGraphCallChainResponse { repo_id: string; snapshot_id: string; symbol: string; direction: "callers" | "callees" | "both"; depth: number; root: CodeGraphNodeResponse | null; nodes: CodeGraphNodeResponse[]; edges: CodeGraphEdgeResponse[]; }
export interface CodeGraphClassResponse { repo_id: string; snapshot_id: string; class_name: string; class_node: CodeGraphNodeResponse | null; related_nodes: CodeGraphNodeResponse[]; relations: CodeGraphEdgeResponse[]; }
export interface RepoResponse { repo_id: string; alias: string; repo_path: string; remote_url: string | null; branch: string | null; current_commit: string | null; status: string; file_count: number; snapshot_id?: string | null; commit?: string | null; }
export interface SnapshotResponse { snapshot_id: string; repo_id: string; commit: string; branch: string | null; status: string; error: string | null; is_active: boolean; created_at: string; updated_at: string; finished_at: string | null; }
export interface SnapshotListResponse { repo_id: string; active_snapshot_id: string | null; snapshots: SnapshotResponse[]; }
export interface SnapshotRefreshResponse { repo_id: string; snapshot_id: string; commit: string; status: string; job_id: string | null; }
export interface FileRecordResponse { id: string; repo_id: string; snapshot_id: string; relative_path: string; language: string | null; file_type: string; extension: string | null; size_bytes: number; line_count: number | null; is_binary: boolean; is_test_file: boolean; ignored_reason: string | null; hash: string | null; parse_status: string; }
export interface FileDetailResponse extends FileRecordResponse { content: string | null; content_truncated: boolean; }
export interface ChunkDetailResponse { id: string; repo_id: string; snapshot_id: string; file_id: string; file_path: string; chunk_type: string; title: string | null; symbol_name: string | null; start_line: number | null; end_line: number | null; content: string; content_hash: string; token_count: number | null; embedding_status: string; source_type: string; metadata_json: string | null; parent_id: string | null; }
export interface Evidence { id: string; logical_id: string | null; snapshot_id: string; file_id: string; parent_id: string | null; unit_type: string; identity_key: string | null; language: string | null; title: string | null; symbol_name: string | null; start_line: number | null; end_line: number | null; content: string; content_hash: string; token_count: number | null; parser_name: string; parser_version: string; metadata_json: string | null; file_path: string; }
export interface Symbol { id: string; logical_id: string | null; snapshot_id: string; file_id: string; evidence_id: string | null; qualified_name: string; name: string; symbol_kind: string; identity_key: string | null; signature: string | null; start_line: number | null; end_line: number | null; visibility: string | null; metadata_json: string | null; file_path: string; }
export interface Relation { id: string; snapshot_id: string; source_symbol_id: string | null; source_evidence_id: string | null; target_symbol_id: string | null; target_evidence_id: string | null; target_ref: string | null; relation_type: string; identity_key: string; observed: number | boolean; inferred: number | boolean; resolver_status: string; confidence: number | null; evidence_id: string | null; extractor: string; extractor_version: string; metadata_json: string | null; }
export interface ParserDiagnostic { id: number; snapshot_id: string; file_id: string; severity: string; code: string; message: string; start_line: number | null; end_line: number | null; parser: string; identity_key: string; }
export interface ParserFactListResponse<T> { repo_id: string; snapshot_id: string; items: T[]; }
export interface IngestResponse { repo_id: string; status: string; indexed_file_count: number; chunk_count: number; job_id: string | null; }
export interface RepoCreateResponse { repo_id: string; status: string; current_commit: string | null; file_count: number; job_id: string | null; }
export interface RepoMapResponse { repo_id: string; alias: string; status: string; branch: string | null; current_commit: string | null; file_count: number; indexable_file_count: number; chunk_count: number; language_counts: Record<string, number>; category_counts: Record<string, number>; top_directories: Record<string, number>; key_files: Record<string, string[]>; reading_order: string[]; snapshot_id?: string | null; commit?: string | null; }
export interface RepoSummaryResponse { repo_id: string; alias: string; summary: string; languages: string[]; recommended_reading_order: string[]; next_steps: string[]; snapshot_id?: string | null; commit?: string | null; }
export interface EvidenceItem { file_path: string; chunk_id: string; start_line: number | null; end_line: number | null; source_type: string; score: number; reason: string; snippet: string; title: string | null; symbol_name: string | null; }
export interface QAResponse { answer: string; evidence: EvidenceItem[]; suggestions: string[]; confidence: string; used_context: number; trace_id: string; next_steps: string[]; token_count: number; snapshot_id?: string | null; commit?: string | null; }
export interface SearchResponse { repo_id: string; query: string; evidence: EvidenceItem[]; snapshot_id?: string | null; commit?: string | null; }
export interface WorkflowReportResponse { analysis_id: string; status: string; repo: { repo_id: string; alias: string; repo_path: string; remote_url: string | null; branch: string | null; current_commit: string | null; }; summary: string; sections: Array<{ key: string; title: string; findings: Array<{ title: string; detail: string; severity: string; evidence: EvidenceItem[]; }>; }>; next_steps: string[]; limitations: string[]; markdown: string; }
export interface AgentLLMOverride { model?: string; base_url?: string; api_key?: string; }
export interface CollaborateAgentRequest { name: string; role: string; llm_override?: AgentLLMOverride; }
export interface CollaborateResponse { topic: string; repo_id: string; contributions: Array<{ agent_name: string; role: string; content: string; used_llm: boolean; error: string | null; }>; summary: string; agents_used_llm: number; total_tokens_used: number; snapshot_id: string | null; commit: string | null; trace_id: string | null; mode: "legacy_multi_role"; }
export type CatalogKind = "symbol" | "file" | "directory" | "subsystem" | "repository_overview" | "reading_guide";
export type CatalogGenerationMethod = "rule" | "llm_enhanced";
export interface CatalogItemResponse { id: string; repo_id: string; snapshot_id: string; kind: CatalogKind; title: string; path: string | null; parent_id: string | null; summary: string; details: Record<string, unknown>; generation_method: CatalogGenerationMethod; model: string | null; prompt_version: string; token_count: number; source_evidence_ids: string[]; freshness: string; known_unknowns: string[]; created_at: string; updated_at: string; }
export interface CatalogListResponse { repo_id: string; snapshot_id: string; items: CatalogItemResponse[]; }
export interface CatalogTreeNode extends CatalogItemResponse { children: CatalogTreeNode[]; }
export interface CatalogTreeResponse { repo_id: string; snapshot_id: string; roots: CatalogTreeNode[]; }
export type AgentTraceStatus = "running" | "succeeded" | "failed" | "fallback";
export type AgentTraceStepStatus = "started" | "succeeded" | "failed" | "skipped";
export interface AgentTraceStep { id: string; trace_id: string; step_no: number; step_type: string; tool_name: string | null; status: AgentTraceStepStatus; input: Record<string, unknown>; output_summary: Record<string, unknown>; evidence_refs: Array<Record<string, unknown>>; token_count: number; duration_ms: number | null; error: string | null; created_at: string; completed_at: string | null; }
export interface AgentTraceResponse { id: string; repo_id: string; snapshot_id: string; session_id: string | null; entrypoint: string; question: string; mode: string; status: AgentTraceStatus; planner_version: string; final_answer: string | null; confidence: string | null; token_count: number; error: string | null; created_at: string; completed_at: string | null; steps: AgentTraceStep[]; }
export interface SettingsResponse { api_base_url: string; llm_api_key_configured: boolean; llm_api_key_hint: string | null; llm_base_url: string; llm_model: string; llm_temperature: number; llm_max_tokens: number; embedding_provider: "disabled" | "openai_compatible"; embedding_api_key_configured: boolean; embedding_api_key_hint: string | null; embedding_base_url: string; embedding_model: string; retrieval_limit: number; input_cost_per_1k_tokens: number; output_cost_per_1k_tokens: number; }
export type SecretUpdate = { action: "unchanged"; value?: never } | { action: "clear"; value?: never } | { action: "set"; value: string };
export interface SettingsUpdateRequest extends Partial<Omit<SettingsResponse, "llm_api_key_configured" | "llm_api_key_hint" | "embedding_api_key_configured" | "embedding_api_key_hint">> { llm_api_key_update?: SecretUpdate; embedding_api_key_update?: SecretUpdate; }
export interface JobRecordResponse { id: string; repo_id: string | null; job_type: string; status: string; progress: number; message: string | null; error: string | null; started_at: string | null; finished_at: string | null; created_at: string; updated_at: string; }

interface FastApiErrorBody {
  detail?: unknown;
  error?: {
    code?: unknown;
    message?: unknown;
    detail?: unknown;
    trace_id?: unknown;
  };
}

export let DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api/v1";
let apiBaseUrl = DEFAULT_API_BASE_URL;

export function setApiBaseUrl(url: string): void { apiBaseUrl = url.replace(/\/$/, ""); }
export function getApiBaseUrl(): string { return apiBaseUrl; }

// FastAPI 既可能返回标准 detail，也可能返回项目自定义的 error.message。
export function parseApiError(status: number, body: string): string {
  const fallback = body.trim() || "请求失败";

  try {
    const parsed = JSON.parse(body) as FastApiErrorBody;
    if (typeof parsed.error?.message === "string" && parsed.error.message.trim()) {
      return parsed.error.message;
    }
    if (typeof parsed.error?.detail === "string" && parsed.error.detail.trim()) {
      return parsed.error.detail;
    }
    if (typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail;
    }
    if (Array.isArray(parsed.detail)) {
      const messages = parsed.detail
        .map((item) => item && typeof item === "object" && "msg" in item ? String(item.msg) : "")
        .filter(Boolean);
      if (messages.length > 0) {
        return messages.join("；");
      }
    }
  } catch {
    // 非 JSON 响应保留原文，便于排查反向代理或服务启动错误。
  }

  return `HTTP ${status}: ${fallback}`;
}

// 后端当前使用 0~1 的小数；同时兼容未来直接返回 0~100 百分比的情况。
export function jobProgressPercent(progress: number | null | undefined): number {
  const value = Number.isFinite(progress) ? Number(progress) : 0;
  const percent = value >= 0 && value <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, Math.round(percent)));
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = apiBaseUrl + path;
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(parseApiError(response.status, text));
  }
  return response.json() as Promise<T>;
}

const repoPath = (repoId: string) => encodeURIComponent(repoId);

// 可选快照统一放进查询参数或请求体；undefined 会保持旧客户端请求完全不变。
const snapshotQuery = (snapshotId?: string) => snapshotId
  ? "?" + new URLSearchParams({ snapshot_id: snapshotId })
  : "";

export async function getHealth(): Promise<HealthResponse> { return request<HealthResponse>("/health"); }
export async function getJob(jobId: string): Promise<JobRecordResponse> { return request<JobRecordResponse>("/jobs/" + encodeURIComponent(jobId)); }
export async function registerRepository(repoPathValue: string, remoteUrl?: string, branch?: string, alias?: string): Promise<RepoCreateResponse> { return request<RepoCreateResponse>("/repos", { method: "POST", body: JSON.stringify({ repo_path: repoPathValue, remote_url: remoteUrl, branch, alias }) }); }
export async function listRepositories(limit = 100): Promise<RepoResponse[]> { return request<RepoResponse[]>("/repos?" + new URLSearchParams({ limit: String(limit) })); }
export async function getRepository(repoId: string): Promise<RepoResponse> { return request<RepoResponse>("/repos/" + repoPath(repoId)); }
export async function listRepositorySnapshots(repoId: string, limit = 100): Promise<SnapshotListResponse> { return request<SnapshotListResponse>("/repos/" + repoPath(repoId) + "/snapshots?" + new URLSearchParams({ limit: String(limit) })); }
export async function getRepositorySnapshot(repoId: string, snapshotId: string): Promise<SnapshotResponse> { return request<SnapshotResponse>("/repos/" + repoPath(repoId) + "/snapshots/" + encodeURIComponent(snapshotId)); }
export async function refreshRepository(repoId: string): Promise<SnapshotRefreshResponse> { return request<SnapshotRefreshResponse>("/repos/" + repoPath(repoId) + "/refresh", { method: "POST" }); }
export async function getRepositoryFiles(repoId: string, limit = 100, snapshotId?: string): Promise<FileRecordResponse[]> { const params = new URLSearchParams({ limit: String(limit) }); if (snapshotId) params.set("snapshot_id", snapshotId); return request<FileRecordResponse[]>("/repos/" + repoPath(repoId) + "/files?" + params); }
export async function getRepositoryFileDetail(repoId: string, fileId: string, snapshotId?: string): Promise<FileDetailResponse> { return request<FileDetailResponse>("/repos/" + repoPath(repoId) + "/files/" + encodeURIComponent(fileId) + snapshotQuery(snapshotId)); }
export async function getRepositoryChunkDetail(repoId: string, chunkId: string, snapshotId?: string): Promise<ChunkDetailResponse> { return request<ChunkDetailResponse>("/repos/" + repoPath(repoId) + "/chunks/" + encodeURIComponent(chunkId) + snapshotQuery(snapshotId)); }
export async function listEvidence(repoId: string, options: { snapshotId?: string; fileId?: string; query?: string; limit?: number } = {}): Promise<ParserFactListResponse<Evidence>> {
  const params = new URLSearchParams();
  if (options.snapshotId) params.set("snapshot_id", options.snapshotId);
  if (options.fileId) params.set("file_id", options.fileId);
  if (options.query) params.set("query", options.query);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  return request<ParserFactListResponse<Evidence>>("/repos/" + repoPath(repoId) + "/evidence" + (params.size ? "?" + params : ""));
}
export async function listSymbols(repoId: string, options: { snapshotId?: string; query?: string; limit?: number } = {}): Promise<ParserFactListResponse<Symbol>> {
  const params = new URLSearchParams();
  if (options.snapshotId) params.set("snapshot_id", options.snapshotId);
  if (options.query) params.set("query", options.query);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  return request<ParserFactListResponse<Symbol>>("/repos/" + repoPath(repoId) + "/symbols" + (params.size ? "?" + params : ""));
}
export async function listRelations(repoId: string, limit = 1000, snapshotId?: string): Promise<ParserFactListResponse<Relation>> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (snapshotId) params.set("snapshot_id", snapshotId);
  return request<ParserFactListResponse<Relation>>("/repos/" + repoPath(repoId) + "/relations?" + params);
}
export async function listParserDiagnostics(repoId: string, options: { snapshotId?: string; fileId?: string; limit?: number } = {}): Promise<ParserFactListResponse<ParserDiagnostic>> {
  const params = new URLSearchParams();
  if (options.snapshotId) params.set("snapshot_id", options.snapshotId);
  if (options.fileId) params.set("file_id", options.fileId);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  return request<ParserFactListResponse<ParserDiagnostic>>("/repos/" + repoPath(repoId) + "/parser-diagnostics" + (params.size ? "?" + params : ""));
}
export async function ingestRepository(repoId: string): Promise<IngestResponse> { return request<IngestResponse>("/repos/" + repoPath(repoId) + "/ingest", { method: "POST" }); }
export async function getRepositoryMap(repoId: string, snapshotId?: string): Promise<RepoMapResponse> { return request<RepoMapResponse>("/repos/" + repoPath(repoId) + "/map" + snapshotQuery(snapshotId)); }
export async function getRepositorySummary(repoId: string, snapshotId?: string): Promise<RepoSummaryResponse> { return request<RepoSummaryResponse>("/repos/" + repoPath(repoId) + "/summary" + snapshotQuery(snapshotId)); }
export async function askRepository(repoId: string, question: string, snapshotId?: string): Promise<QAResponse> { return request<QAResponse>("/repos/" + repoPath(repoId) + "/ask", { method: "POST", body: JSON.stringify({ question, ...(snapshotId ? { snapshot_id: snapshotId } : {}) }) }); }
export async function searchRepository(repoId: string, query: string, snapshotId?: string): Promise<SearchResponse> { return request<SearchResponse>("/repos/" + repoPath(repoId) + "/search", { method: "POST", body: JSON.stringify({ query, ...(snapshotId ? { snapshot_id: snapshotId } : {}) }) }); }
export async function analyzeRepositoryWorkflow(repoId: string): Promise<WorkflowReportResponse> { return request<WorkflowReportResponse>("/repos/" + repoPath(repoId) + "/analysis/workflow", { method: "POST" }); }
export async function analyzeGithubRepository(githubUrl: string, alias?: string, autoIngest = true): Promise<WorkflowReportResponse> { return request<WorkflowReportResponse>("/analysis/analyze", { method: "POST", body: JSON.stringify({ github_url: githubUrl, alias, auto_ingest: autoIngest }) }); }
export async function runCollaboration(repoId: string, topic: string, agents?: CollaborateAgentRequest[], snapshotId?: string): Promise<CollaborateResponse> { return request<CollaborateResponse>("/collaborate", { method: "POST", body: JSON.stringify({ repo_id: repoId, topic, agents, ...(snapshotId ? { snapshot_id: snapshotId } : {}) }) }); }
export async function listRepositoryCatalog(repoId: string, options: { snapshotId?: string; kind?: string } = {}): Promise<CatalogListResponse> { const params = new URLSearchParams(); if (options.snapshotId) params.set("snapshot_id", options.snapshotId); if (options.kind) params.set("kind", options.kind); return request<CatalogListResponse>("/repos/" + repoPath(repoId) + "/catalog" + (params.size ? "?" + params : "")); }
export async function getRepositoryCatalogTree(repoId: string, snapshotId?: string): Promise<CatalogTreeResponse> { return request<CatalogTreeResponse>("/repos/" + repoPath(repoId) + "/catalog/tree" + snapshotQuery(snapshotId)); }
export async function getRepositoryCatalogItem(repoId: string, itemId: string, snapshotId?: string): Promise<CatalogItemResponse> { return request<CatalogItemResponse>("/repos/" + repoPath(repoId) + "/catalog/" + encodeURIComponent(itemId) + snapshotQuery(snapshotId)); }
export async function getRepositoryTrace(repoId: string, traceId: string): Promise<AgentTraceResponse> { return request<AgentTraceResponse>("/repos/" + repoPath(repoId) + "/traces/" + encodeURIComponent(traceId)); }
export async function readSettings(): Promise<SettingsResponse> { return request<SettingsResponse>("/settings"); }
export async function updateSettings(settings: SettingsUpdateRequest): Promise<SettingsResponse> { return request<SettingsResponse>("/settings", { method: "PUT", body: JSON.stringify(settings) }); }
export async function getCodeGraphStats(repoId: string, snapshotId?: string): Promise<CodeGraphStatsResponse> { return request<CodeGraphStatsResponse>("/code-graph/" + repoPath(repoId) + "/stats" + snapshotQuery(snapshotId)); }
export async function searchCodeFunctions(repoId: string, query: string, limit = 20, snapshotId?: string): Promise<CodeGraphSearchResponse> { const params = new URLSearchParams({ q: query, limit: String(limit) }); if (snapshotId) params.set("snapshot_id", snapshotId); return request<CodeGraphSearchResponse>("/code-graph/" + repoPath(repoId) + "/search?" + params); }
export async function getCallChain(repoId: string, symbol: string, direction: "callers" | "callees" | "both" = "both", depth = 3, snapshotId?: string): Promise<CodeGraphCallChainResponse> { const params = new URLSearchParams({ symbol, direction, depth: String(depth) }); if (snapshotId) params.set("snapshot_id", snapshotId); return request<CodeGraphCallChainResponse>("/code-graph/" + repoPath(repoId) + "/call-chain?" + params); }
export async function getClassHierarchy(repoId: string, className: string, snapshotId?: string): Promise<CodeGraphClassResponse> { const params = new URLSearchParams({ class_name: className }); if (snapshotId) params.set("snapshot_id", snapshotId); return request<CodeGraphClassResponse>("/code-graph/" + repoPath(repoId) + "/class?" + params); }
export async function getImportantFunctions(repoId: string, limit = 20, snapshotId?: string): Promise<CodeGraphImportantResponse> { const params = new URLSearchParams({ limit: String(limit) }); if (snapshotId) params.set("snapshot_id", snapshotId); return request<CodeGraphImportantResponse>("/code-graph/" + repoPath(repoId) + "/important?" + params); }
