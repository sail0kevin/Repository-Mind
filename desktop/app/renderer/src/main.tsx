import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom/client";
import {
  Activity,
  AlertCircle,
  BarChart3,
  Bot,
  CircleDollarSign,
  Code2,
  Database,
  Eye,
  EyeOff,
  FileCode2,
  GitBranch,
  Loader2,
  MessageSquareText,
  Pause,
  Play,
  RefreshCcw,
  Save,
  Search,
  Send,
  Settings,
  Terminal,
  Workflow,
  X,
} from "lucide-react";

import {
  DEFAULT_API_BASE_URL,
  analyzeGithubRepository,
  analyzeRepositoryWorkflow,
  askRepository,
  getCallChain,
  getClassHierarchy,
  getCodeGraphStats,
  getHealth,
  getImportantFunctions,
  getJob,
  getRepository,
  getRepositoryCatalogItem,
  getRepositoryCatalogTree,
  getRepositoryChunkDetail,
  getRepositoryFiles,
  getRepositoryMap,
  getRepositorySummary,
  getRepositoryTrace,
  ingestRepository,
  jobProgressPercent,
  listRepositories,
  listRepositorySnapshots,
  readSettings,
  registerRepository,
  runCollaboration,
  searchCodeFunctions,
  searchRepository,
  setApiBaseUrl,
  updateSettings,
} from "../services/apiClient";
import type {
  AgentTraceResponse,
  CatalogItemResponse,
  CatalogTreeNode,
  ChunkDetailResponse,
  CollaborateResponse,
  EvidenceItem,
  FileRecordResponse,
  HealthResponse,
  JobRecordResponse,
  QAResponse,
  RepoMapResponse,
  RepoResponse,
  RepoSummaryResponse,
  SettingsResponse,
  SnapshotResponse,
  WorkflowReportResponse,
} from "../services/apiClient";
import { AppHeader } from "./app/AppHeader";
import { AppShell } from "./app/AppShell";
import type { AgentConfig, CodeGraphMode, DebateMessage, WorkspaceTab } from "./app/types";
import { CatalogWorkspace } from "./features/catalog/CatalogWorkspace";
import { RepositoryKnowledgeNavigator } from "./features/catalog/RepositoryKnowledgeNavigator";
import { EvidenceDrawer } from "./features/evidence/EvidenceDrawer";
import { LegacyAgentPanel } from "./features/legacy/LegacyAgentPanel";
import { RepositoryAccessPanel } from "./features/repositories/RepositoryAccessPanel";
import { UserGuide } from "./UserGuide";
import { ingestThenLoadRepository } from "./repositoryRegistration";
import "./styles.css";

const DEFAULT_SETTINGS: SettingsResponse = {
  api_base_url: DEFAULT_API_BASE_URL,
  llm_api_key_configured: false,
  llm_api_key_hint: null,
  llm_base_url: "https://api.longcat.chat/openai/v1",
  llm_model: "LongCat-2.0",
  llm_temperature: 0.2,
  llm_max_tokens: 2048,
  embedding_provider: "disabled",
  embedding_api_key_configured: false,
  embedding_api_key_hint: null,
  embedding_base_url: "https://api.openai.com/v1",
  embedding_model: "text-embedding-3-small",
  retrieval_limit: 8,
  input_cost_per_1k_tokens: 0,
  output_cost_per_1k_tokens: 0,
};

const ROLE_OPTIONS = [
  { value: "developer", label: "开发工程师" },
  { value: "tester", label: "测试工程师" },
  { value: "pm", label: "产品经理" },
  { value: "architect", label: "架构师" },
  { value: "security", label: "安全工程师" },
  { value: "docs", label: "文档分析师" },
];

const DEFAULT_AGENTS: AgentConfig[] = [
  { id: "agent-developer", name: "代码审查员", role: "developer", status: "idle", avatar: "代", apiKey: "", baseUrl: "", model: "" },
  { id: "agent-tester", name: "测试工程师", role: "tester", status: "idle", avatar: "测", apiKey: "", baseUrl: "", model: "" },
  { id: "agent-pm", name: "产品经理", role: "pm", status: "idle", avatar: "产", apiKey: "", baseUrl: "", model: "" },
  { id: "agent-architect", name: "架构师", role: "architect", status: "idle", avatar: "架", apiKey: "", baseUrl: "", model: "" },
];

const PRICING_PRESETS = [
  { provider: "LongCat", model: "LongCat-2.0", input: 0, output: 0, note: "请以美团 LongCat 控制台实际账单为准" },
  { provider: "OpenAI", model: "gpt-4o-mini", input: 0.00015, output: 0.0006, note: "公开价格可能变化，请定期核对" },
  { provider: "OpenAI", model: "gpt-4o", input: 0.0025, output: 0.01, note: "适合复杂分析，成本更高" },
  { provider: "DeepSeek", model: "deepseek-chat", input: 0.00027, output: 0.0011, note: "不同计费区域可能不同" },
];

function nowTime() {
  return new Date().toLocaleTimeString("zh-CN", { hour12: false });
}

function roleLabel(role: string) {
  return ROLE_OPTIONS.find((item) => item.value === role)?.label ?? role;
}

function extractErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "未知错误";
}

function estimateCost(tokens: number, settings: SettingsResponse) {
  return (tokens * 0.7 * (settings.input_cost_per_1k_tokens || 0)) / 1000
    + (tokens * 0.3 * (settings.output_cost_per_1k_tokens || 0)) / 1000;
}

function normalizeResultList(value: unknown): any[] {
  if (Array.isArray(value)) {
    return value;
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (Array.isArray(record.matches)) {
      return record.matches;
    }
    if (Array.isArray(record.nodes)) {
      return record.nodes;
    }
    if (Array.isArray(record.results)) {
      return record.results;
    }
    if (Array.isArray(record.functions)) {
      return record.functions;
    }
  }
  return [];
}

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [settings, setSettings] = useState<SettingsResponse>(DEFAULT_SETTINGS);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<string[]>(["[INFO] RepoMind 已启动，等待后端连接"]);

  const [githubUrl, setGithubUrl] = useState("");
  const [repoPath, setRepoPath] = useState("");
  const [alias, setAlias] = useState("");
  const [repositories, setRepositories] = useState<RepoResponse[]>([]);
  const [repo, setRepo] = useState<RepoResponse | null>(null);
  const [snapshots, setSnapshots] = useState<SnapshotResponse[]>([]);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string | null>(null);
  const [catalogRoots, setCatalogRoots] = useState<CatalogTreeNode[]>([]);
  const [selectedCatalogItem, setSelectedCatalogItem] = useState<CatalogItemResponse | null>(null);
  const [isKnowledgeLoading, setIsKnowledgeLoading] = useState(false);
  const [files, setFiles] = useState<FileRecordResponse[]>([]);
  const [repoMap, setRepoMap] = useState<RepoMapResponse | null>(null);
  const [repoSummary, setRepoSummary] = useState<RepoSummaryResponse | null>(null);
  const [workflowReport, setWorkflowReport] = useState<WorkflowReportResponse | null>(null);
  const [activeWorkflowSection, setActiveWorkflowSection] = useState("");

  const [activeTab, setActiveTab] = useState<WorkspaceTab>("qa");
  const [isRegistering, setIsRegistering] = useState(false);
  const [activeJob, setActiveJob] = useState<JobRecordResponse | null>(null);
  const [registerProgress, setRegisterProgress] = useState("等待添加仓库");

  const [agents, setAgents] = useState<AgentConfig[]>(DEFAULT_AGENTS);
  const [newAgentName, setNewAgentName] = useState("");
  const [newAgentRole, setNewAgentRole] = useState("developer");
  const [editingAgentId, setEditingAgentId] = useState<string | null>(null);

  const [debateTopic, setDebateTopic] = useState("这个项目的核心架构、风险和下一步开发重点是什么？");
  const [debateMessages, setDebateMessages] = useState<DebateMessage[]>([]);
  const [collaborateResult, setCollaborateResult] = useState<CollaborateResponse | null>(null);
  const [isDebating, setIsDebating] = useState(false);
  const [userIntervention, setUserIntervention] = useState("");

  const [question, setQuestion] = useState("这个项目的入口文件和核心模块分别是什么？");
  const [isAsking, setIsAsking] = useState(false);
  const [answer, setAnswer] = useState<QAResponse | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [evidenceSnapshotId, setEvidenceSnapshotId] = useState<string | null>(null);
  const [selectedChunk, setSelectedChunk] = useState<ChunkDetailResponse | null>(null);
  const [selectedTrace, setSelectedTrace] = useState<AgentTraceResponse | null>(null);
  const [isEvidenceDrawerOpen, setIsEvidenceDrawerOpen] = useState(false);

  const [totalTokens, setTotalTokens] = useState(0);
  const [totalCost, setTotalCost] = useState(0);

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isPricingOpen, setIsPricingOpen] = useState(false);
  const [isGuideOpen, setIsGuideOpen] = useState(false);
  const [leftPanelWidth, setLeftPanelWidth] = useState(() => {
    const savedWidth = Number(window.localStorage.getItem("repomind:left-panel-width"));
    return Number.isFinite(savedWidth) && savedWidth >= 240 && savedWidth <= 520 ? savedWidth : 280;
  });
  const [isResizingLeftPanel, setIsResizingLeftPanel] = useState(false);

  const [codeGraphMode, setCodeGraphMode] = useState<CodeGraphMode>("overview");
  const [codeGraphStats, setCodeGraphStats] = useState<Record<string, unknown> | null>(null);
  const [importantFunctions, setImportantFunctions] = useState<any[]>([]);
  const [functionQuery, setFunctionQuery] = useState("");
  const [functionResults, setFunctionResults] = useState<any[]>([]);
  const [callFunctionName, setCallFunctionName] = useState("");
  const [callChain, setCallChain] = useState<unknown>(null);
  const [className, setClassName] = useState("");
  const [classHierarchy, setClassHierarchy] = useState<unknown>(null);

  const logRef = useRef<HTMLDivElement | null>(null);
  const streamRef = useRef<HTMLDivElement | null>(null);
  const knowledgeRequestRef = useRef(0);
  const catalogRequestRef = useRef(0);
  const canUseRepo = !!repo
    && !!selectedSnapshotId
    && snapshots.some((snapshot) => snapshot.snapshot_id === selectedSnapshotId && snapshot.status === "succeeded")
    && !isRegistering;
  const indexedPercent = activeJob ? jobProgressPercent(activeJob.progress) : repoMap ? 100 : 0;

  const currentWorkflowSection = useMemo(() => {
    if (!workflowReport) {
      return null;
    }
    return workflowReport.sections.find((section) => section.key === activeWorkflowSection)
      ?? workflowReport.sections[0]
      ?? null;
  }, [workflowReport, activeWorkflowSection]);

  useEffect(() => {
    void initializeApp();
  }, []);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs]);

  useEffect(() => {
    if (streamRef.current) {
      streamRef.current.scrollTop = streamRef.current.scrollHeight;
    }
  }, [debateMessages]);

  useEffect(() => {
    if (!isResizingLeftPanel) {
      return;
    }

    function resizeLeftPanel(event: PointerEvent) {
      const workspacePadding = 16;
      const nextWidth = Math.max(240, Math.min(520, event.clientX - workspacePadding));
      setLeftPanelWidth(nextWidth);
    }

    function stopResizingLeftPanel() {
      setIsResizingLeftPanel(false);
      document.body.classList.remove("af-is-resizing");
    }

    document.body.classList.add("af-is-resizing");
    window.addEventListener("pointermove", resizeLeftPanel);
    window.addEventListener("pointerup", stopResizingLeftPanel);
    window.addEventListener("pointercancel", stopResizingLeftPanel);

    return () => {
      document.body.classList.remove("af-is-resizing");
      window.removeEventListener("pointermove", resizeLeftPanel);
      window.removeEventListener("pointerup", stopResizingLeftPanel);
      window.removeEventListener("pointercancel", stopResizingLeftPanel);
    };
  }, [isResizingLeftPanel]);

  useEffect(() => {
    window.localStorage.setItem("repomind:left-panel-width", String(leftPanelWidth));
  }, [leftPanelWidth]);

  function addLog(message: string) {
    setLogs((previous) => [...previous.slice(-120), `[${nowTime()}] ${message}`]);
  }

  async function initializeApp() {
    setError(null);
    try {
      const desktopBridge = (window as Window & {
        repomind?: { backend?: { start?: () => Promise<{ started: boolean; apiBaseUrl: string }> } };
      }).repomind;
      const backendResult = await desktopBridge?.backend?.start?.();
      if (backendResult?.apiBaseUrl) {
        setApiBaseUrl(backendResult.apiBaseUrl);
      }

      let healthResponse: HealthResponse | null = null;
      let lastError: unknown = null;
      for (let attempt = 0; attempt < 30; attempt += 1) {
        try {
          healthResponse = await getHealth();
          break;
        } catch (err) {
          lastError = err;
          await new Promise((resolve) => window.setTimeout(resolve, 500));
        }
      }
      if (!healthResponse) {
        throw lastError instanceof Error ? lastError : new Error("后端启动超时");
      }

      const settingsResponse = await readSettings();
      setHealth(healthResponse);
      setSettings(settingsResponse);
      // Electron 使用本次启动后端的随机端口；纯浏览器开发模式仍沿用保存的 API 地址。
      setApiBaseUrl(backendResult?.apiBaseUrl || settingsResponse.api_base_url);
      const repositoryResponse = await listRepositories(100);
      setRepositories(repositoryResponse);
      const initialRepo = repositoryResponse.find((item) => !!item.snapshot_id) ?? repositoryResponse[0];
      if (initialRepo) {
        void loadRepositoryKnowledge(initialRepo.repo_id);
      }
      addLog(`[INFO] 后端在线：${healthResponse.app_name}`);
    } catch (err) {
      setHealth(null);
      setError("无法连接后端。桌面端已尝试自动启动，请稍后重试或查看 RepoMind 后端日志。");
      addLog(`[ERROR] 后端连接失败：${extractErrorMessage(err)}`);
    }
  }

  async function loadRepository(repoId: string, snapshotId?: string) {
    const [repoResponse, fileResponse] = await Promise.all([
      getRepository(repoId),
      getRepositoryFiles(repoId, 120, snapshotId),
    ]);
    setRepo(repoResponse);
    setRepositories((previous) => {
      const withoutCurrent = previous.filter((item) => item.repo_id !== repoResponse.repo_id);
      return [repoResponse, ...withoutCurrent];
    });
    setFiles(fileResponse);
    addLog(`[INFO] 已载入仓库：${repoResponse.alias}，文件 ${fileResponse.length} 个`);
  }

  async function refreshRepositoryList() {
    setIsKnowledgeLoading(true);
    try {
      setRepositories(await listRepositories(100));
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setIsKnowledgeLoading(false);
    }
  }

  async function loadRepositoryKnowledge(repoId: string, requestedSnapshotId?: string) {
    const requestId = knowledgeRequestRef.current + 1;
    knowledgeRequestRef.current = requestId;
    catalogRequestRef.current += 1;
    setIsKnowledgeLoading(true);
    setError(null);
    // 每次切换仓库时先清空旧卡片和证据，防止异步请求期间展示跨仓库内容。
    setCatalogRoots([]);
    setSelectedCatalogItem(null);
    setSelectedChunk(null);
    setSelectedTrace(null);
    setEvidenceSnapshotId(null);
    setIsEvidenceDrawerOpen(false);
    try {
      const [repoResponse, snapshotResponse] = await Promise.all([
        getRepository(repoId),
        listRepositorySnapshots(repoId, 100),
      ]);
      const selectedSnapshot = requestedSnapshotId
        ? snapshotResponse.snapshots.find((item) => item.snapshot_id === requestedSnapshotId && item.status === "succeeded")
        : snapshotResponse.snapshots.find((item) => item.snapshot_id === snapshotResponse.active_snapshot_id && item.status === "succeeded");
      if (requestId !== knowledgeRequestRef.current) {
        return;
      }
      setRepo(repoResponse);
      setSnapshots(snapshotResponse.snapshots);
      setSelectedSnapshotId(selectedSnapshot?.snapshot_id ?? null);
      if (!selectedSnapshot) {
        setFiles([]);
        setRepoMap(null);
        setRepoSummary(null);
        addLog(`[WARN] 仓库 ${repoResponse.alias} 暂无可用的 succeeded 快照`);
        return;
      }
      const [fileResponse, mapResponse, summaryResponse, catalogResponse] = await Promise.all([
        getRepositoryFiles(repoId, 120, selectedSnapshot.snapshot_id),
        getRepositoryMap(repoId, selectedSnapshot.snapshot_id),
        getRepositorySummary(repoId, selectedSnapshot.snapshot_id),
        getRepositoryCatalogTree(repoId, selectedSnapshot.snapshot_id),
      ]);
      if (requestId !== knowledgeRequestRef.current) {
        return;
      }
      setFiles(fileResponse);
      setRepoMap(mapResponse);
      setRepoSummary(summaryResponse);
      setCatalogRoots(catalogResponse.roots);
      setActiveTab("catalog");
      addLog(`[INFO] 已切换知识快照：${selectedSnapshot.commit.slice(0, 12)}`);
    } catch (err) {
      if (requestId !== knowledgeRequestRef.current) {
        return;
      }
      const message = extractErrorMessage(err);
      setError(message);
      addLog(`[ERROR] 仓库知识载入失败：${message}`);
    } finally {
      if (requestId === knowledgeRequestRef.current) {
        setIsKnowledgeLoading(false);
      }
    }
  }

  async function handleCatalogItemSelect(item: CatalogTreeNode) {
    if (!repo || !selectedSnapshotId) {
      return;
    }
    const repoId = repo.repo_id;
    const snapshotId = selectedSnapshotId;
    const requestId = catalogRequestRef.current + 1;
    catalogRequestRef.current = requestId;
    setIsKnowledgeLoading(true);
    try {
      const detail = await getRepositoryCatalogItem(repoId, item.id, snapshotId);
      if (requestId === catalogRequestRef.current && repo.repo_id === repoId && selectedSnapshotId === snapshotId) {
        setSelectedCatalogItem(detail);
      }
    } catch (err) {
      if (requestId === catalogRequestRef.current) {
        setError(extractErrorMessage(err));
      }
    } finally {
      if (requestId === catalogRequestRef.current) {
        setIsKnowledgeLoading(false);
      }
    }
  }

  async function refreshRepoInsights(repoId: string, snapshotId?: string) {
    const [mapResponse, summaryResponse] = await Promise.all([
      getRepositoryMap(repoId, snapshotId),
      getRepositorySummary(repoId, snapshotId),
    ]);
    setRepoMap(mapResponse);
    setRepoSummary(summaryResponse);
    addLog(`[INFO] 仓库地图已生成：${mapResponse.chunk_count} 个知识片段`);
  }

  async function pollIngestJob(jobId: string, repoId: string) {
    setRegisterProgress("索引任务已启动，正在解析文件、生成知识片段并构建代码图谱");
    for (let index = 0; index < 900; index += 1) {
      const job = await getJob(jobId);
      setActiveJob(job);
      setRegisterProgress(job.message || `索引进度 ${jobProgressPercent(job.progress)}%`);
      const terminal = ["succeeded", "failed", "cancelled", "interrupted"].includes(job.status);
      if (index === 0 || index % 5 === 0 || terminal) {
        addLog(`[INFO] 索引进度 ${jobProgressPercent(job.progress)}%：${job.message || job.status}`);
      }
      if (job.status === "succeeded") {
        setRegisterProgress("索引完成，正在载入仓库内容");
        return;
      }
      if (["failed", "cancelled", "interrupted"].includes(job.status)) {
        const fallback = job.status === "cancelled" ? "索引任务已取消" : job.status === "interrupted" ? "索引任务因应用重启而中断，请重试" : "索引任务失败";
        throw new Error(job.error || job.message || fallback);
      }
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
    throw new Error("索引等待超时，请在系统日志中查看后端状态。");
  }

  async function handleRegisterRepository() {
    const trimmedGithubUrl = githubUrl.trim();
    const trimmedRepoPath = repoPath.trim();
    const trimmedAlias = alias.trim() || undefined;

    if (trimmedGithubUrl && trimmedRepoPath) {
      setError("GitHub URL 和本地仓库路径只能填写一个，请清空其中一项。");
      return;
    }
    if (!trimmedGithubUrl && !trimmedRepoPath) {
      setError("请先输入 GitHub URL 或本地 Git 仓库路径。");
      return;
    }

    setError(null);
    setIsRegistering(true);
    setRepo(null);
    setSnapshots([]);
    setSelectedSnapshotId(null);
    setCatalogRoots([]);
    setSelectedCatalogItem(null);
    setSelectedChunk(null);
    setSelectedTrace(null);
    setEvidenceSnapshotId(null);
    setIsEvidenceDrawerOpen(false);
    setFiles([]);
    setRepoMap(null);
    setRepoSummary(null);
    setWorkflowReport(null);
    setActiveWorkflowSection("");
    setAnswer(null);
    setEvidence([]);
    setCodeGraphStats(null);
    setImportantFunctions([]);
    setFunctionResults([]);
    setCallChain(null);
    setClassHierarchy(null);
    setCollaborateResult(null);
    setDebateMessages([]);
    setActiveJob(null);

    try {
      let repoId: string;
      if (trimmedGithubUrl) {
        setRegisterProgress("正在克隆 GitHub 仓库并生成首次工作流报告");
        addLog(`[INFO] 开始分析 GitHub 仓库：${trimmedGithubUrl}`);
        const report = await analyzeGithubRepository(trimmedGithubUrl, trimmedAlias, false);
        setWorkflowReport(report);
        setActiveWorkflowSection(report.sections[0]?.key || "");
        repoId = report.repo.repo_id;
      } else {
        setRegisterProgress("正在注册本地仓库并扫描文件");
        addLog(`[INFO] 注册本地仓库：${trimmedRepoPath}`);
        const created = await registerRepository(trimmedRepoPath, undefined, undefined, trimmedAlias);
        repoId = created.repo_id;
      }

      // 新仓库还没有 succeeded 快照；必须先建立索引，随后才能读取 files。
      setRegisterProgress("仓库已注册，正在启动索引任务");
      await ingestThenLoadRepository(repoId, {
        ingestRepository,
        pollIngestJob,
        loadRepository,
        refreshRepositoryInsights: async (targetRepoId) => {
          await refreshRepoInsights(targetRepoId);
          await refreshCodeGraph(targetRepoId);
          await loadRepositoryKnowledge(targetRepoId);
          setRegisterProgress("索引完成，可以开始浏览 Catalog、问答和代码图谱查询");
        },
      });
    } catch (err) {
      const message = extractErrorMessage(err);
      setError(message);
      setRegisterProgress("处理失败，请查看错误信息");
      addLog(`[ERROR] 仓库处理失败：${message}`);
    } finally {
      setIsRegistering(false);
    }
  }

  async function handleAsk() {
    if (!repo || !question.trim()) {
      return;
    }
    setIsAsking(true);
    setError(null);
    addLog(`[INFO] 提问：${question.trim()}`);
    try {
      const response = await askRepository(repo.repo_id, question.trim(), selectedSnapshotId ?? undefined);
      setAnswer(response);
      setEvidence(response.evidence || []);
      setEvidenceSnapshotId(response.snapshot_id ?? selectedSnapshotId);
      const tokens = response.token_count || 0;
      setTotalTokens((previous) => previous + tokens);
      setTotalCost((previous) => previous + estimateCost(tokens, settings));
      addLog(`[INFO] 回答完成，使用 ${tokens || "未知"} tokens`);
    } catch (err) {
      const message = extractErrorMessage(err);
      setError(message);
      addLog(`[ERROR] 问答失败：${message}`);
    } finally {
      setIsAsking(false);
    }
  }

  async function handleSearch() {
    if (!repo || !searchQuery.trim()) {
      return;
    }
    setError(null);
    try {
      const response = await searchRepository(repo.repo_id, searchQuery.trim(), selectedSnapshotId ?? undefined);
      setEvidence(response.evidence || []);
      setEvidenceSnapshotId(response.snapshot_id ?? selectedSnapshotId);
      addLog(`[INFO] 找到 ${response.evidence.length} 条证据`);
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  }

  async function handleEvidenceSelect(item: EvidenceItem) {
    if (!repo || !evidenceSnapshotId || !item.chunk_id) {
      return;
    }
    const repoId = repo.repo_id;
    const snapshotId = evidenceSnapshotId;
    setError(null);
    try {
      setSelectedChunk(await getRepositoryChunkDetail(repoId, item.chunk_id, snapshotId));
      setIsEvidenceDrawerOpen(true);
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  }

  async function handleTraceOpen() {
    if (!repo || !answer?.trace_id) {
      return;
    }
    setError(null);
    try {
      setSelectedTrace(await getRepositoryTrace(repo.repo_id, answer.trace_id));
      setIsEvidenceDrawerOpen(true);
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  }

  async function handleWorkflowAnalysis() {
    if (!repo) {
      return;
    }
    setError(null);
    try {
      const report = await analyzeRepositoryWorkflow(repo.repo_id);
      setWorkflowReport(report);
      setActiveWorkflowSection(report.sections[0]?.key || "");
      addLog(`[INFO] 工作流分析完成：${report.analysis_id}`);
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  }

  async function handleCollaborate() {
    if (!repo || !debateTopic.trim()) {
      return;
    }
    setIsDebating(true);
    setCollaborateResult(null);
    setDebateMessages([]);
    setAgents((previous) => previous.map((agent) => ({ ...agent, status: "thinking" })));
    setError(null);
    try {
      const response = await runCollaboration(
        repo.repo_id,
        debateTopic.trim(),
        agents.map((agent) => {
          const model = agent.model.trim();
          const baseUrl = agent.baseUrl.trim();
          const apiKey = agent.apiKey.trim();
          const llmOverride = {
            ...(model ? { model } : {}),
            ...(baseUrl ? { base_url: baseUrl } : {}),
            ...(apiKey ? { api_key: apiKey } : {}),
          };
          return {
            name: agent.name,
            role: agent.role,
            ...(Object.keys(llmOverride).length ? { llm_override: llmOverride } : {}),
          };
        }),
        selectedSnapshotId ?? undefined,
      );
      setCollaborateResult(response);
      const tokens = response.total_tokens_used || 0;
      setTotalTokens((previous) => previous + tokens);
      setTotalCost((previous) => previous + estimateCost(tokens, settings));
      setDebateMessages(response.contributions.map((item, index) => ({
        id: `${Date.now()}-${index}`,
        sender: item.agent_name,
        role: item.role,
        content: item.content,
        isUser: false,
        timestamp: nowTime(),
      })));
      setAgents((previous) => previous.map((agent) => ({ ...agent, status: "done" })));
      addLog(`[INFO] 协作完成，${response.agents_used_llm} 个智能体成功调用模型，使用 ${tokens || "未知"} tokens`);
    } catch (err) {
      setError(extractErrorMessage(err));
      setAgents((previous) => previous.map((agent) => ({ ...agent, status: "idle" })));
    } finally {
      // 专属 Key 只用于本次请求，完成后立即从前端内存状态中清除。
      setAgents((previous) => previous.map((agent) => ({ ...agent, apiKey: "" })));
      setIsDebating(false);
    }
  }

  function addAgent() {
    const name = newAgentName.trim();
    if (!name) {
      return;
    }
    setAgents((previous) => [
      ...previous,
      {
        id: `agent-${Date.now()}`,
        name,
        role: newAgentRole,
        status: "idle",
        avatar: name.slice(0, 1),
        apiKey: "",
        baseUrl: "",
        model: "",
      },
    ]);
    setNewAgentName("");
  }

  function updateAgent(id: string, patch: Partial<AgentConfig>) {
    setAgents((previous) => previous.map((agent) => (agent.id === id ? { ...agent, ...patch } : agent)));
  }

  async function handleSettingsSaved(nextSettings: SettingsResponse) {
    setSettings(nextSettings);
    setApiBaseUrl(nextSettings.api_base_url);
    setError(null);
    addLog(`[INFO] 设置已保存，模型：${nextSettings.llm_model}`);
  }

  async function refreshCodeGraph(repoId = repo?.repo_id) {
    if (!repoId) {
      return;
    }
    try {
      const [stats, important] = await Promise.all([
        getCodeGraphStats(repoId),
        getImportantFunctions(repoId, 20),
      ]);
      setCodeGraphStats(stats as Record<string, unknown>);
      setImportantFunctions(normalizeResultList(important));
      addLog("[INFO] 代码图谱已刷新");
    } catch (err) {
      addLog(`[WARN] 代码图谱暂不可用：${extractErrorMessage(err)}`);
    }
  }

  async function handleFunctionSearch() {
    if (!repo || !functionQuery.trim()) {
      return;
    }
    const response = await searchCodeFunctions(repo.repo_id, functionQuery.trim(), 20);
    setFunctionResults(normalizeResultList(response));
  }

  async function handleCallChain() {
    if (!repo || !callFunctionName.trim()) {
      return;
    }
    setCallChain(await getCallChain(repo.repo_id, callFunctionName.trim(), "both", 3));
  }

  async function handleClassHierarchy() {
    if (!repo || !className.trim()) {
      return;
    }
    setClassHierarchy(await getClassHierarchy(repo.repo_id, className.trim()));
  }

  return (
    <div className="af-app">
      <AppHeader
        isHealthy={!!health}
        onOpenGuide={() => setIsGuideOpen(true)}
        onOpenPricing={() => setIsPricingOpen(true)}
        onOpenSettings={() => setIsSettingsOpen(true)}
      />

      <AppShell
        leftPanelWidth={leftPanelWidth}
        onResizeStart={(event) => {
          event.preventDefault();
          setIsResizingLeftPanel(true);
        }}
        onResizeReset={() => setLeftPanelWidth(280)}
        onResizeKeyDown={(event) => {
          if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
            event.preventDefault();
            const direction = event.key === "ArrowLeft" ? -1 : 1;
            setLeftPanelWidth((current) => Math.max(240, Math.min(520, current + direction * (event.shiftKey ? 40 : 10))));
          } else if (event.key === "Home") {
            event.preventDefault();
            setLeftPanelWidth(240);
          } else if (event.key === "End") {
            event.preventDefault();
            setLeftPanelWidth(520);
          }
        }}
        leftPanel={
          <>
            <RepositoryAccessPanel
              alias={alias}
              githubUrl={githubUrl}
              indexedPercent={indexedPercent}
              isRegistering={isRegistering}
              repo={repo}
              repoPath={repoPath}
              registerProgress={registerProgress}
              onAliasChange={setAlias}
              onGithubUrlChange={setGithubUrl}
              onRegister={handleRegisterRepository}
              onRepoPathChange={setRepoPath}
            />
            <RepositoryKnowledgeNavigator
              catalogRoots={catalogRoots}
              isLoading={isKnowledgeLoading}
              repositories={repositories}
              selectedCatalogItemId={selectedCatalogItem?.id ?? null}
              selectedRepoId={repo?.repo_id ?? null}
              selectedSnapshotId={selectedSnapshotId}
              snapshots={snapshots}
              onCatalogItemSelect={handleCatalogItemSelect}
              onRefreshRepositories={refreshRepositoryList}
              onRepositorySelect={(repoId) => void loadRepositoryKnowledge(repoId)}
              onSnapshotSelect={(snapshotId) => repo && void loadRepositoryKnowledge(repo.repo_id, snapshotId)}
            />
            <LegacyAgentPanel
              agents={agents}
              editingAgentId={editingAgentId}
              newAgentName={newAgentName}
              newAgentRole={newAgentRole}
              roleOptions={ROLE_OPTIONS}
              onAddAgent={addAgent}
              onEditingAgentChange={setEditingAgentId}
              onNewAgentNameChange={setNewAgentName}
              onNewAgentRoleChange={setNewAgentRole}
              onRemoveAgent={(id) => setAgents((previous) => previous.filter((item) => item.id !== id))}
              onUpdateAgent={updateAgent}
            />
          </>
        }
        centerPanel={
          <>
          {error && <div className="af-error-box"><AlertCircle size={16} /> <span>{error}</span><button onClick={() => setError(null)}><X size={14} /></button></div>}
          <div className="af-tabs">
            <button className={`af-tab ${activeTab === "catalog" ? "active" : ""}`} onClick={() => setActiveTab("catalog")}><Database size={14} /> 知识目录</button>
            <button className={`af-tab ${activeTab === "qa" ? "active" : ""}`} onClick={() => setActiveTab("qa")}><Search size={14} /> 智能问答</button>
            <button className={`af-tab ${activeTab === "legacy" ? "active" : ""}`} onClick={() => setActiveTab("legacy")}><MessageSquareText size={14} /> Legacy 多角色</button>
            <button className={`af-tab ${activeTab === "workflow" ? "active" : ""}`} onClick={() => setActiveTab("workflow")}><Workflow size={14} /> 工作流分析</button>
            <button className={`af-tab ${activeTab === "codegraph" ? "active" : ""}`} onClick={() => setActiveTab("codegraph")}><Code2 size={14} /> 代码图谱</button>
          </div>

          {activeTab === "catalog" && (
            <CatalogWorkspace
              item={selectedCatalogItem}
              snapshot={snapshots.find((item) => item.snapshot_id === selectedSnapshotId) ?? null}
            />
          )}
          {activeTab === "qa" && (
            <QaPanel
              answer={answer}
              canUseRepo={canUseRepo}
              isAsking={isAsking}
              question={question}
              searchQuery={searchQuery}
              onAsk={handleAsk}
              onQuestionChange={setQuestion}
              onSearch={handleSearch}
              onSearchQueryChange={setSearchQuery}
              onOpenTrace={handleTraceOpen}
              onRefresh={() => repo && refreshRepoInsights(repo.repo_id, selectedSnapshotId ?? undefined)}
            />
          )}
          {activeTab === "legacy" && (
            <DebatePanel
              canUseRepo={canUseRepo}
              collaborateResult={collaborateResult}
              debateMessages={debateMessages}
              debateTopic={debateTopic}
              isDebating={isDebating}
              streamRef={streamRef}
              userIntervention={userIntervention}
              onDebateTopicChange={setDebateTopic}
              onRun={handleCollaborate}
              onUserInterventionChange={setUserIntervention}
              onUserInterventionSend={() => {
                if (!userIntervention.trim()) {
                  return;
                }
                setDebateMessages((previous) => [...previous, {
                  id: `${Date.now()}-user`,
                  sender: "你",
                  role: "user",
                  content: userIntervention.trim(),
                  isUser: true,
                  timestamp: nowTime(),
                }]);
                setUserIntervention("");
              }}
            />
          )}
          {activeTab === "workflow" && (
            <WorkflowPanel
              canUseRepo={canUseRepo}
              currentSection={currentWorkflowSection}
              report={workflowReport}
              onRun={handleWorkflowAnalysis}
              onSectionChange={setActiveWorkflowSection}
            />
          )}
          {activeTab === "codegraph" && (
            <CodeGraphPanel
              canUseRepo={canUseRepo}
              classHierarchy={classHierarchy}
              className={className}
              codeGraphMode={codeGraphMode}
              functionQuery={functionQuery}
              functionResults={functionResults}
              importantFunctions={importantFunctions}
              callChain={callChain}
              callFunctionName={callFunctionName}
              stats={codeGraphStats}
              onCallFunctionNameChange={setCallFunctionName}
              onClassNameChange={setClassName}
              onFunctionQueryChange={setFunctionQuery}
              onModeChange={setCodeGraphMode}
              onRefresh={() => refreshCodeGraph()}
              onSearchCalls={handleCallChain}
              onSearchClass={handleClassHierarchy}
              onSearchFunctions={handleFunctionSearch}
            />
          )}
          </>
        }
        rightPanel={
          <>
            <section className="af-section">
            <div className="af-section-title"><BarChart3 size={15} /> 会话指标</div>
            <MetricCard title="Token Usage" value={totalTokens.toLocaleString()} note="只统计本应用真实问答返回或估算的 token。" />
            <MetricCard title="Cost Estimate" value={`$${totalCost.toFixed(totalCost >= 1 ? 2 : 5)}`} note="按设置页单价估算，不代表官方账单。" onNoteClick={() => setIsPricingOpen(true)} />
          </section>
          <section className="af-section">
            <div className="af-section-title"><Database size={15} /> 仓库概览</div>
            {repoSummary ? (
              <div className="af-summary-card">
                <p>{repoSummary.summary}</p>
                <strong>推荐阅读顺序</strong>
                {repoSummary.recommended_reading_order.slice(0, 6).map((item) => <span key={item}>{item}</span>)}
              </div>
            ) : <div className="af-empty small">暂无仓库摘要</div>}
          </section>
          <EvidencePanel evidence={evidence} files={files} onEvidenceSelect={handleEvidenceSelect} />
          <section className="af-section">
            <div className="af-section-title"><Terminal size={15} /> System Logs</div>
            <div className="af-logs" ref={logRef}>{logs.map((line, index) => <div key={`${line}-${index}`} className="af-log-line">{line}</div>)}</div>
          </section>
          </>
        }
      />

      {isSettingsOpen && <SettingsModal initialSettings={settings} onClose={() => setIsSettingsOpen(false)} onSaved={handleSettingsSaved} />}
      {isPricingOpen && <PricingModal settings={settings} onClose={() => setIsPricingOpen(false)} onSaved={handleSettingsSaved} />}
      {isEvidenceDrawerOpen && (
        <EvidenceDrawer
          chunk={selectedChunk}
          commit={snapshots.find((item) => item.snapshot_id === selectedChunk?.snapshot_id)?.commit ?? repo?.commit ?? null}
          trace={selectedTrace}
          onClose={() => setIsEvidenceDrawerOpen(false)}
        />
      )}
      <UserGuide isOpen={isGuideOpen} onClose={() => setIsGuideOpen(false)} />
    </div>
  );
}

function QaPanel(props: {
  answer: QAResponse | null;
  canUseRepo: boolean;
  isAsking: boolean;
  question: string;
  searchQuery: string;
  onAsk: () => void;
  onQuestionChange: (value: string) => void;
  onSearch: () => void;
  onSearchQueryChange: (value: string) => void;
  onOpenTrace: () => void;
  onRefresh: () => void;
}) {
  return (
    <div className="af-qa">
      <div className="af-qbox">
        <input value={props.question} onChange={(event) => props.onQuestionChange(event.target.value)} onKeyDown={(event) => event.key === "Enter" && props.onAsk()} placeholder="问这个仓库任何问题，例如：启动流程是什么？" />
        <button onClick={props.onAsk} disabled={!props.canUseRepo || props.isAsking}>{props.isAsking ? <Loader2 size={16} className="spin" /> : <Send size={16} />} 提问</button>
      </div>
      <div className="af-actions">
        <input className="af-inline-input" value={props.searchQuery} onChange={(event) => props.onSearchQueryChange(event.target.value)} placeholder="只搜索证据，不调用模型" />
        <button className="af-btn secondary" onClick={props.onSearch} disabled={!props.canUseRepo}><Search size={16} /> 搜索证据</button>
        <button className="af-btn secondary" onClick={props.onRefresh} disabled={!props.canUseRepo}><RefreshCcw size={16} /> 刷新地图</button>
      </div>
      {props.answer ? (
        <div className="af-answer">
          <div className="af-answer-meta">
            <span>置信度：{props.answer.confidence}</span>
            <span>证据：{props.answer.used_context}</span>
            <span>Token：{props.answer.token_count || "未返回"}</span>
            <button className="af-link-btn" onClick={props.onOpenTrace}>查看工具轨迹</button>
          </div>
          <p>{props.answer.answer}</p>
        </div>
      ) : (
        <div className="af-empty"><Bot size={42} /><p>完成仓库索引后，在这里直接向代码库提问。</p></div>
      )}
    </div>
  );
}

function DebatePanel(props: {
  canUseRepo: boolean;
  collaborateResult: CollaborateResponse | null;
  debateMessages: DebateMessage[];
  debateTopic: string;
  isDebating: boolean;
  streamRef: React.RefObject<HTMLDivElement | null>;
  userIntervention: string;
  onDebateTopicChange: (value: string) => void;
  onRun: () => void;
  onUserInterventionChange: (value: string) => void;
  onUserInterventionSend: () => void;
}) {
  return (
    <div className="af-debate">
      <div className="af-stream" ref={props.streamRef}>
        {props.debateMessages.length === 0 ? (
          <div className="af-empty"><MessageSquareText size={42} /><p>Waiting for agents to start discussion...</p></div>
        ) : props.debateMessages.map((message) => (
          <div key={message.id} className={`af-msg ${message.isUser ? "user" : "agent"}`}>
            <div className={`af-msg-avatar ${message.isUser ? "user" : ""}`}>{message.sender.slice(0, 1)}</div>
            <div className="af-msg-content">
              <div className="af-msg-header"><span>{message.sender}</span><span>{roleLabel(message.role)}</span><span>{message.timestamp}</span></div>
              <p>{message.content}</p>
            </div>
          </div>
        ))}
      </div>
      {props.collaborateResult && <div className="af-debate-summary"><strong>综合摘要</strong><p>{props.collaborateResult.summary}</p></div>}
      <div className="af-controls">
        <div className="af-topic-input"><input value={props.debateTopic} onChange={(event) => props.onDebateTopicChange(event.target.value)} placeholder="输入协作讨论主题" /></div>
        <div className="af-control-btns">
          <button className="af-btn primary" onClick={props.onRun} disabled={!props.canUseRepo || props.isDebating}>{props.isDebating ? <Loader2 size={16} className="spin" /> : <Play size={16} />} Start Simulation</button>
          <button className="af-btn secondary" disabled={!props.isDebating}><Pause size={16} /> Pause</button>
        </div>
        <div className="af-intervention">
          <input value={props.userIntervention} onChange={(event) => props.onUserInterventionChange(event.target.value)} onKeyDown={(event) => event.key === "Enter" && props.onUserInterventionSend()} placeholder="输入指令打断或引导讨论..." />
          <button className="af-btn secondary" onClick={props.onUserInterventionSend}>Send Command</button>
        </div>
      </div>
    </div>
  );
}

function WorkflowPanel(props: {
  canUseRepo: boolean;
  currentSection: WorkflowReportResponse["sections"][number] | null;
  report: WorkflowReportResponse | null;
  onRun: () => void;
  onSectionChange: (key: string) => void;
}) {
  return (
    <div className="af-workflow">
      <div className="af-actions">
        <button className="af-btn primary" onClick={props.onRun} disabled={!props.canUseRepo}><Workflow size={16} /> 运行工作流分析</button>
      </div>
      {props.report ? (
        <div className="af-report">
          <h2>{props.report.summary}</h2>
          <div className="af-report-tabs">
            {props.report.sections.map((section) => <button key={section.key} className={`af-rtab ${props.currentSection?.key === section.key ? "active" : ""}`} onClick={() => props.onSectionChange(section.key)}>{section.title}</button>)}
          </div>
          {props.currentSection?.findings.map((finding, index) => (
            <div key={`${finding.title}-${index}`} className="af-finding">
              <div><strong>{finding.title}</strong><span className={`af-sev sev-${finding.severity}`}>{finding.severity}</span></div>
              <p>{finding.detail}</p>
            </div>
          ))}
        </div>
      ) : (
        <div className="af-empty"><Workflow size={42} /><p>首次分析会把代码、文档、配置等部分分给不同视角处理。</p></div>
      )}
    </div>
  );
}

function CodeGraphPanel(props: {
  canUseRepo: boolean;
  classHierarchy: unknown;
  className: string;
  codeGraphMode: CodeGraphMode;
  functionQuery: string;
  functionResults: any[];
  importantFunctions: any[];
  callChain: unknown;
  callFunctionName: string;
  stats: Record<string, unknown> | null;
  onCallFunctionNameChange: (value: string) => void;
  onClassNameChange: (value: string) => void;
  onFunctionQueryChange: (value: string) => void;
  onModeChange: (mode: CodeGraphMode) => void;
  onRefresh: () => void;
  onSearchCalls: () => void;
  onSearchClass: () => void;
  onSearchFunctions: () => void;
}) {
  return (
    <div className="af-workflow">
      <div className="af-cg-toolbar">
        <div className="af-cg-tabs">
          {(["overview", "search", "calls", "class"] as const).map((mode) => (
            <button key={mode} className={`af-cg-tab ${props.codeGraphMode === mode ? "active" : ""}`} onClick={() => props.onModeChange(mode)}>
              {mode === "overview" ? "概览" : mode === "search" ? "函数搜索" : mode === "calls" ? "调用链" : "类关系"}
            </button>
          ))}
        </div>
        <button className="af-btn secondary" onClick={props.onRefresh} disabled={!props.canUseRepo}><RefreshCcw size={16} /> 刷新</button>
      </div>
      {props.codeGraphMode === "overview" && <CodeGraphOverview stats={props.stats} importantFunctions={props.importantFunctions} />}
      {props.codeGraphMode === "search" && <CodeGraphSearch query={props.functionQuery} setQuery={props.onFunctionQueryChange} onSearch={props.onSearchFunctions} results={props.functionResults} />}
      {props.codeGraphMode === "calls" && <JsonLookup value={props.callFunctionName} setValue={props.onCallFunctionNameChange} onSearch={props.onSearchCalls} placeholder="输入函数名查看调用链" buttonLabel="查询调用链" result={props.callChain} />}
      {props.codeGraphMode === "class" && <JsonLookup value={props.className} setValue={props.onClassNameChange} onSearch={props.onSearchClass} placeholder="输入类名查看继承/方法关系" buttonLabel="查询类关系" result={props.classHierarchy} />}
    </div>
  );
}

function CodeGraphOverview({ stats, importantFunctions }: { stats: Record<string, unknown> | null; importantFunctions: any[] }) {
  const diagnostics = stats?.diagnostics && typeof stats.diagnostics === "object"
    ? stats.diagnostics as Record<string, unknown>
    : null;
  const diagnosticMessage = typeof diagnostics?.message === "string" ? diagnostics.message : "";
  return (
    <div className="af-cg-content">
      <div className="af-cg-stat-grid">
        <div className="af-cg-stat-card"><span className="af-cg-stat-num">{String(stats?.total_nodes ?? stats?.nodes ?? stats?.node_count ?? 0)}</span><span>节点</span></div>
        <div className="af-cg-stat-card"><span className="af-cg-stat-num">{String(stats?.total_edges ?? stats?.edges ?? stats?.edge_count ?? 0)}</span><span>关系</span></div>
        <div className="af-cg-stat-card"><span className="af-cg-stat-num">{importantFunctions.length}</span><span>重点函数</span></div>
      </div>
      {diagnosticMessage && diagnostics?.status !== "success" && (
        <div className="af-error-box">
          <AlertCircle size={16} />
          <span>{diagnosticMessage} 已发现 {String(diagnostics?.discovered_source_count ?? 0)} 个源码文件，成功解析 {String(diagnostics?.parsed_count ?? 0)} 个 Python 文件。</span>
        </div>
      )}
      <div className="af-cg-func-list">
        {importantFunctions.map((item, index) => <CodeGraphItem key={index} item={item} />)}
        {importantFunctions.length === 0 && <div className="af-empty small"><FileCode2 size={28} /><p>索引完成后会在这里显示重要函数。</p></div>}
      </div>
    </div>
  );
}

function CodeGraphItem({ item }: { item: any }) {
  return (
    <div className="af-cg-func-item">
      <Code2 size={14} />
      <span className="af-cg-func-name">{item.name || item.function_name || item.function || item.symbol || "未知函数"}</span>
      <span className="af-cg-file">{item.file_path || item.file || "未知文件"}</span>
      {item.call_count !== undefined && <span className="af-cg-badge">调用 {item.call_count}</span>}
    </div>
  );
}

function CodeGraphSearch({ query, setQuery, onSearch, results }: { query: string; setQuery: (value: string) => void; onSearch: () => void; results: any[] }) {
  return (
    <div className="af-cg-content">
      <div className="af-qbox">
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入函数名、方法名或符号名" />
        <button onClick={onSearch}><Search size={16} /> 搜索</button>
      </div>
      <div className="af-cg-results">{results.map((item, index) => <CodeGraphItem key={index} item={item} />)}</div>
    </div>
  );
}

function JsonLookup({ value, setValue, onSearch, placeholder, buttonLabel, result }: { value: string; setValue: (value: string) => void; onSearch: () => void; placeholder: string; buttonLabel: string; result: unknown }) {
  return (
    <div className="af-cg-content">
      <div className="af-qbox">
        <input value={value} onChange={(event) => setValue(event.target.value)} placeholder={placeholder} />
        <button onClick={onSearch}><Search size={16} /> {buttonLabel}</button>
      </div>
      <pre className="af-json-box">{result ? JSON.stringify(result, null, 2) : "暂无查询结果"}</pre>
    </div>
  );
}

function EvidencePanel({ evidence, files, onEvidenceSelect }: { evidence: EvidenceItem[]; files: FileRecordResponse[]; onEvidenceSelect: (item: EvidenceItem) => void }) {
  return (
    <>
      <section className="af-section">
        <div className="af-section-title"><FileCode2 size={15} /> 文件样例</div>
        <div className="af-evidence">
          {files.slice(0, 8).map((file) => (
            <div key={file.id} className="af-ev-item">
              <strong>{file.relative_path}</strong>
              <span>{file.language || file.file_type} · {file.line_count || 0} 行</span>
            </div>
          ))}
          {files.length === 0 && <div className="af-empty small">暂无文件</div>}
        </div>
      </section>
      <section className="af-section">
        <div className="af-section-title"><FileCode2 size={15} /> 证据流</div>
        <div className="af-evidence">
          {evidence.map((item, index) => (
            <button key={`${item.chunk_id}-${index}`} className="af-ev-item af-ev-button" onClick={() => onEvidenceSelect(item)}>
              <strong>{item.file_path}</strong>
              <span>{item.start_line ?? "?"}-{item.end_line ?? "?"} · {item.reason}</span>
              <p>{item.snippet}</p>
            </button>
          ))}
          {evidence.length === 0 && <div className="af-empty small">暂无证据</div>}
        </div>
      </section>
    </>
  );
}

function MetricCard({ title, value, note, onNoteClick }: { title: string; value: string; note: string; onNoteClick?: () => void }) {
  return (
    <div className="af-metric">
      <div className="af-metric-h"><Activity size={14} /> {title}</div>
      <div className="af-metric-v">{value}</div>
      <div className="af-progress"><span style={{ width: "18%" }} /></div>
      <div className="af-metric-footer">
        <span>{note}</span>
        {onNoteClick && <button className="af-link-btn" onClick={onNoteClick}>配置单价</button>}
      </div>
    </div>
  );
}

function SettingsModal({ initialSettings, onClose, onSaved }: { initialSettings: SettingsResponse; onClose: () => void; onSaved: (settings: SettingsResponse) => Promise<void> }) {
  const [form, setForm] = useState<SettingsResponse>(initialSettings);
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [embeddingApiKey, setEmbeddingApiKey] = useState("");
  const [clearEmbeddingApiKey, setClearEmbeddingApiKey] = useState(false);
  const [showEmbeddingKey, setShowEmbeddingKey] = useState(false);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);

  function setField<K extends keyof SettingsResponse>(key: K, value: SettingsResponse[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
  }

  function useLongCatPreset() {
    setForm((previous) => ({
      ...previous,
      llm_base_url: "https://api.longcat.chat/openai/v1",
      llm_model: "LongCat-2.0",
      input_cost_per_1k_tokens: 0,
      output_cost_per_1k_tokens: 0,
    }));
  }

  async function save() {
    setSaving(true);
    setStatus("");
    try {
      // 密钥框留空代表保持原值；只有明确输入或勾选清除时才改变 DPAPI 中的密钥。
      const llmApiKeyUpdate = clearApiKey
        ? { action: "clear" as const }
        : apiKey.trim()
          ? { action: "set" as const, value: apiKey.trim() }
          : { action: "unchanged" as const };
      const embeddingApiKeyUpdate = clearEmbeddingApiKey
        ? { action: "clear" as const }
        : embeddingApiKey.trim()
          ? { action: "set" as const, value: embeddingApiKey.trim() }
          : { action: "unchanged" as const };
      const {
        llm_api_key_configured: _llmConfigured,
        llm_api_key_hint: _llmHint,
        embedding_api_key_configured: _embeddingConfigured,
        embedding_api_key_hint: _embeddingHint,
        ...publicSettings
      } = form;
      const response = await updateSettings({
        ...publicSettings,
        llm_api_key_update: llmApiKeyUpdate,
        embedding_api_key_update: embeddingApiKeyUpdate,
      });
      await onSaved(response);
      setApiKey("");
      setClearApiKey(false);
      setEmbeddingApiKey("");
      setClearEmbeddingApiKey(false);
      setForm(response);
      setStatus("设置已保存。现在可以回到左侧注册仓库，再进行问答或协作分析。");
    } catch (err) {
      setStatus(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function testBackend() {
    setStatus("正在测试后端连接...");
    try {
      setApiBaseUrl(form.api_base_url);
      const response = await getHealth();
      setStatus(`后端连接成功：${response.status}`);
    } catch (err) {
      setStatus(`后端连接失败：${extractErrorMessage(err)}`);
    }
  }

  return (
    <div className="af-modal-overlay" onClick={onClose}>
      <div className="af-modal" onClick={(event) => event.stopPropagation()}>
        <div className="af-modal-header"><h2><Settings size={18} /> 系统设置</h2><button className="af-icon-btn" onClick={onClose}><X size={18} /></button></div>
        <div className="af-settings">
          <div className="af-actions"><button className="af-btn secondary" onClick={useLongCatPreset}>使用 LongCat-2.0 预设</button></div>
          <div className="af-settings-form">
            <label className="af-field"><span>后端 API 地址</span><input value={form.api_base_url} onChange={(event) => setField("api_base_url", event.target.value)} /></label>
            <label className="af-field"><span>LLM Base URL</span><input value={form.llm_base_url} onChange={(event) => setField("llm_base_url", event.target.value)} placeholder="https://api.longcat.chat/openai/v1" /></label>
            <label className="af-field"><span>模型名</span><input value={form.llm_model} onChange={(event) => setField("llm_model", event.target.value)} placeholder="LongCat-2.0" /></label>
            <label className="af-field"><span>API Key {form.llm_api_key_configured ? `(已配置 ${form.llm_api_key_hint ?? ""})` : "(未配置)"}</span><div className="af-password-wrapper"><input disabled={clearApiKey} type={showKey ? "text" : "password"} value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="留空保持不变；输入新值会覆盖" /><button type="button" className="af-toggle-pwd" onClick={() => setShowKey((previous) => !previous)}>{showKey ? <EyeOff size={14} /> : <Eye size={14} />}</button></div></label>
            <label className="af-field"><span><input type="checkbox" checked={clearApiKey} onChange={(event) => setClearApiKey(event.target.checked)} /> 清除已保存的 API Key</span></label>
            <label className="af-field"><span>Temperature</span><input type="number" min="0" max="2" step="0.1" value={form.llm_temperature} onChange={(event) => setField("llm_temperature", Number(event.target.value))} /></label>
            <label className="af-field"><span>最大输出 Token</span><input type="number" min="256" step="256" value={form.llm_max_tokens} onChange={(event) => setField("llm_max_tokens", Number(event.target.value))} /></label>
            <label className="af-field"><span>Embedding 模式</span><select value={form.embedding_provider} onChange={(event) => setField("embedding_provider", event.target.value as SettingsResponse["embedding_provider"])}><option value="disabled">关闭（lexical-only）</option><option value="openai_compatible">OpenAI 兼容接口</option></select></label>
            <label className="af-field"><span>Embedding Base URL</span><input disabled={form.embedding_provider === "disabled"} value={form.embedding_base_url} onChange={(event) => setField("embedding_base_url", event.target.value)} placeholder="https://api.openai.com/v1" /></label>
            <label className="af-field"><span>Embedding 模型</span><input disabled={form.embedding_provider === "disabled"} value={form.embedding_model} onChange={(event) => setField("embedding_model", event.target.value)} placeholder="text-embedding-3-small" /></label>
            <label className="af-field"><span>Embedding API Key {form.embedding_api_key_configured ? `(已配置 ${form.embedding_api_key_hint ?? ""})` : "(未配置)"}</span><div className="af-password-wrapper"><input disabled={clearEmbeddingApiKey || form.embedding_provider === "disabled"} type={showEmbeddingKey ? "text" : "password"} value={embeddingApiKey} onChange={(event) => setEmbeddingApiKey(event.target.value)} placeholder="独立于 Chat Key；留空保持不变" /><button type="button" className="af-toggle-pwd" onClick={() => setShowEmbeddingKey((previous) => !previous)}>{showEmbeddingKey ? <EyeOff size={14} /> : <Eye size={14} />}</button></div></label>
            <label className="af-field"><span><input type="checkbox" checked={clearEmbeddingApiKey} onChange={(event) => setClearEmbeddingApiKey(event.target.checked)} /> 清除已保存的 Embedding Key</span></label>
            <label className="af-field"><span>检索结果上限</span><input type="number" min="1" max="50" value={form.retrieval_limit} onChange={(event) => setField("retrieval_limit", Number(event.target.value))} /></label>
            <label className="af-field"><span>输入价格（美元/1K token）</span><input type="number" min="0" step="0.00001" value={form.input_cost_per_1k_tokens} onChange={(event) => setField("input_cost_per_1k_tokens", Number(event.target.value))} /></label>
            <label className="af-field"><span>输出价格（美元/1K token）</span><input type="number" min="0" step="0.00001" value={form.output_cost_per_1k_tokens} onChange={(event) => setField("output_cost_per_1k_tokens", Number(event.target.value))} /></label>
          </div>
          <div className="af-settings-actions"><button className="af-btn secondary" onClick={testBackend}>测试后端</button><button className="af-btn primary" onClick={save} disabled={saving}>{saving ? <Loader2 size={16} className="spin" /> : <Save size={16} />} 保存配置</button></div>
          {status && <div className="af-settings-status">{status}</div>}
          <div className="af-settings-tip"><strong>说明：</strong>Chat 与 Embedding 凭据彼此独立，并使用 Windows DPAPI 保存；Embedding 关闭或调用失败时，仓库仍会以 lexical-only 模式完成索引和检索。</div>
        </div>
      </div>
    </div>
  );
}

function PricingModal({ settings, onClose, onSaved }: { settings: SettingsResponse; onClose: () => void; onSaved: (settings: SettingsResponse) => Promise<void> }) {
  const [inputRate, setInputRate] = useState(settings.input_cost_per_1k_tokens);
  const [outputRate, setOutputRate] = useState(settings.output_cost_per_1k_tokens);
  const [status, setStatus] = useState("");

  async function saveRates() {
    try {
      const response = await updateSettings({ input_cost_per_1k_tokens: inputRate, output_cost_per_1k_tokens: outputRate });
      await onSaved(response);
      setStatus("费用单价已保存。");
    } catch (err) {
      setStatus(extractErrorMessage(err));
    }
  }

  return (
    <div className="af-modal-overlay" onClick={onClose}>
      <div className="af-modal pricing-modal" onClick={(event) => event.stopPropagation()}>
        <div className="af-modal-header"><h2><CircleDollarSign size={18} /> 费用估算设置</h2><button className="af-icon-btn" onClick={onClose}><X size={18} /></button></div>
        <div className="af-pricing">
          <p className="af-pricing-intro">不同模型价格会变化，本页只提供本地估算。真实扣费请以对应平台控制台为准。</p>
          <table className="af-pricing-table">
            <thead><tr><th>平台</th><th>模型</th><th>输入 $/1K</th><th>输出 $/1K</th><th>备注</th></tr></thead>
            <tbody>{PRICING_PRESETS.map((item) => <tr key={`${item.provider}-${item.model}`}><td>{item.provider}</td><td>{item.model}</td><td>{item.input.toFixed(5)}</td><td>{item.output.toFixed(5)}</td><td>{item.note}</td></tr>)}</tbody>
          </table>
          <div className="af-settings-form">
            <label className="af-field"><span>当前输入单价</span><input type="number" min="0" step="0.00001" value={inputRate} onChange={(event) => setInputRate(Number(event.target.value))} /></label>
            <label className="af-field"><span>当前输出单价</span><input type="number" min="0" step="0.00001" value={outputRate} onChange={(event) => setOutputRate(Number(event.target.value))} /></label>
          </div>
          <div className="af-settings-actions"><button className="af-btn primary" onClick={saveRates}><Save size={16} /> 保存单价</button></div>
          {status && <div className="af-settings-status">{status}</div>}
        </div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
