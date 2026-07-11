/**
 * API Client for AgentFlow
 */
export interface HealthResponse { status: string; app_name: string; database_path: string; }
export interface RepoResponse { repo_id: string; alias: string; repo_path: string; remote_url: string | null; branch: string | null; current_commit: string | null; status: string; file_count: number; }
export interface FileRecordResponse { id: string; repo_id: string; relative_path: string; language: string | null; file_type: string; extension: string | null; size_bytes: number; line_count: number | null; is_binary: boolean; is_test_file: boolean; ignored_reason: string | null; hash: string | null; parse_status: string; }
export interface IngestResponse { repo_id: string; status: string; indexed_file_count: number; chunk_count: number; job_id: string | null; }
export interface RepoCreateResponse { repo_id: string; status: string; current_commit: string | null; file_count: number; job_id: string | null; }
export interface RepoMapResponse { repo_id: string; alias: string; status: string; branch: string | null; current_commit: string | null; file_count: number; indexable_file_count: number; chunk_count: number; language_counts: Record<string, number>; category_counts: Record<string, number>; top_directories: Record<string, number>; key_files: Record<string, string[]>; reading_order: string[]; }
export interface RepoSummaryResponse { repo_id: string; alias: string; summary: string; languages: string[]; recommended_reading_order: string[]; next_steps: string[]; }
export interface EvidenceItem { file_path: string; chunk_id: string; start_line: number | null; end_line: number | null; source_type: string; score: number; reason: string; snippet: string; title: string | null; symbol_name: string | null; }
export interface QAResponse { answer: string; evidence: EvidenceItem[]; suggestions: string[]; confidence: string; used_context: number; trace_id: string; next_steps: string[]; token_count: number; }
export interface WorkflowReportResponse { analysis_id: string; status: string; repo: { repo_id: string; alias: string; repo_path: string; remote_url: string | null; branch: string | null; current_commit: string | null; }; summary: string; sections: Array<{ key: string; title: string; findings: Array<{ title: string; detail: string; severity: string; evidence: EvidenceItem[]; }>; }>; next_steps: string[]; limitations: string[]; markdown: string; }
export interface AgentLLMOverride { model?: string; base_url?: string; api_key?: string; }
export interface CollaborateAgentRequest { name: string; role: string; llm_override?: AgentLLMOverride; }
export interface CollaborateResponse { topic: string; repo_id: string; contributions: Array<{ agent_name: string; role: string; content: string; used_llm: boolean; error: string | null; }>; summary: string; agents_used_llm: number; total_tokens_used: number; }
export interface SettingsResponse { api_base_url: string; llm_api_key: string; llm_base_url: string; llm_model: string; llm_temperature: number; llm_max_tokens: number; embedding_model: string; retrieval_limit: number; input_cost_per_1k_tokens: number; output_cost_per_1k_tokens: number; }
export interface JobRecordResponse { id: string; repo_id: string | null; job_type: string; status: string; progress: number; message: string | null; error: string | null; started_at: string | null; finished_at: string | null; created_at: string; updated_at: string; }
export let DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api/v1";
let apiBaseUrl = DEFAULT_API_BASE_URL;
export function setApiBaseUrl(url: string): void { apiBaseUrl = url; }
export function getApiBaseUrl(): string { return apiBaseUrl; }
async function request<T>(path: string, options: RequestInit = {}): Promise<T> { const url = apiBaseUrl + path; const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options }); if (!response.ok) { const text = await response.text(); throw new Error("HTTP " + response.status + ": " + text); } return response.json() as Promise<T>; }
export async function getHealth(): Promise<HealthResponse> { return request<HealthResponse>("/health"); }
export async function getJob(jobId: string): Promise<JobRecordResponse> { return request<JobRecordResponse>("/jobs/" + jobId); }
export async function registerRepository(repoPath: string, remoteUrl?: string, branch?: string, alias?: string): Promise<RepoCreateResponse> { return request<RepoCreateResponse>("/repos", { method: "POST", body: JSON.stringify({ repo_path: repoPath, remote_url: remoteUrl, branch, alias }) }); }
export async function getRepository(repoId: string): Promise<RepoResponse> { return request<RepoResponse>("/repos/" + repoId); }
export async function getRepositoryFiles(repoId: string, limit = 100): Promise<FileRecordResponse[]> { return request<FileRecordResponse[]>("/repos/" + repoId + "/files?limit=" + limit); }
export async function ingestRepository(repoId: string): Promise<IngestResponse> { return request<IngestResponse>("/repos/" + repoId + "/ingest", { method: "POST" }); }
export async function getRepositoryMap(repoId: string): Promise<RepoMapResponse> { return request<RepoMapResponse>("/repos/" + repoId + "/map"); }
export async function getRepositorySummary(repoId: string): Promise<RepoSummaryResponse> { return request<RepoSummaryResponse>("/repos/" + repoId + "/summary"); }
export async function askRepository(repoId: string, question: string): Promise<QAResponse> { return request<QAResponse>("/repos/" + repoId + "/ask", { method: "POST", body: JSON.stringify({ question }) }); }
export async function searchRepository(repoId: string, query: string): Promise<{ repo_id: string; query: string; evidence: EvidenceItem[] }> { return request("/repos/" + repoId + "/search", { method: "POST", body: JSON.stringify({ query }) }); }
export async function analyzeRepositoryWorkflow(repoId: string): Promise<WorkflowReportResponse> { return request<WorkflowReportResponse>("/repos/" + repoId + "/analysis/workflow", { method: "POST" }); }
export async function analyzeGithubRepository(githubUrl: string, alias?: string, autoIngest = true): Promise<WorkflowReportResponse> { return request<WorkflowReportResponse>("/analysis/analyze", { method: "POST", body: JSON.stringify({ github_url: githubUrl, alias, auto_ingest: autoIngest }) }); }
export async function runCollaboration(repoId: string, topic: string, agents?: CollaborateAgentRequest[]): Promise<CollaborateResponse> { return request<CollaborateResponse>("/collaborate", { method: "POST", body: JSON.stringify({ repo_id: repoId, topic, agents }) }); }
export async function readSettings(): Promise<SettingsResponse> { return request<SettingsResponse>("/settings"); }
export async function updateSettings(settings: Partial<SettingsResponse>): Promise<SettingsResponse> { return request<SettingsResponse>("/settings", { method: "PUT", body: JSON.stringify(settings) }); }
export async function getCodeGraphStats(repoId: string): Promise<any> { return request("/code-graph/" + repoId + "/stats"); }
export async function searchCodeFunctions(repoId: string, q: string, limit = 20): Promise<any> { return request("/code-graph/" + repoId + "/search?q=" + encodeURIComponent(q) + "&limit=" + limit); }
export async function getCallChain(repoId: string, fn: string, direction = "both", depth = 3): Promise<any> { return request("/code-graph/" + repoId + "/call-chain?function=" + encodeURIComponent(fn) + "&direction=" + direction + "&depth=" + depth); }
export async function getClassHierarchy(repoId: string, className: string): Promise<any> { return request("/code-graph/" + repoId + "/class?class_name=" + encodeURIComponent(className)); }
export async function getImportantFunctions(repoId: string, limit = 20): Promise<any> { return request("/code-graph/" + repoId + "/important?limit=" + limit); }
