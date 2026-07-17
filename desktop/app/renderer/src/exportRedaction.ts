import type { SaveTextRequest, SaveTextResult } from "../../electron/bridgeContract";
import type { AgentTraceResponse } from "../services/apiClient";

/**
 * 导出文件会离开本机，因此这里统一移除本地路径和认证信息。
 * 相对源码引用（例如 src/main.ts）不含机器身份，应该原样保留以便读者定位证据。
 */
const SENSITIVE_KEY = /(?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth(?:orization)?|password|passwd|secret|credential|cookie|database(?:[_-]?path)?|user[_-]?data(?:[_-]?path)?)/i;
const SENSITIVE_QUERY_KEY = /(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|auth(?:orization)?|password|passwd|secret|credential|signature|sig)/i;
const QUOTED_ABSOLUTE_PATH = /(["'`])(?:[A-Za-z]:[\\/]|\\\\|\/(?!\/))[^\r\n"'`<>]*\1/g;
const ABSOLUTE_PATH = /(^|[\s("'`=:])(?:[A-Za-z]:[\\/][^\r\n,;"'`<>]*|\\\\[^\r\n,;"'`<>]+|\/(?!\/)[^\r\n,;"'`<>]+)/gim;
const MAX_EXPORT_BYTES = 10 * 1024 * 1024;

function redactCredentialUrlPaths(value: string): string {
  return value
    // Slack Incoming Webhook 的三个路径段都是凭据，不能只遮挡最后一段。
    .replace(/(https?:\/\/hooks\.slack\.com\/services\/)[^\s/"'`<>]+\/[^\s/"'`<>]+\/[^\s?#"'`<>]+/gi, "$1[redacted]")
    // Discord webhook 的 ID 和 token 都是凭据；保留主机与 API 路由便于识别服务类型。
    .replace(/(https?:\/\/(?:canary\.|ptb\.)?discord(?:app)?\.com\/api(?:\/v\d+)?\/webhooks\/)[^\s/"'`<>]+\/[^\s?#"'`<>]+/gi, "$1[redacted]");
}

function redactText(value: string): string {
  // URL 中只删认证查询参数，普通查询参数仍可帮助读者理解调用上下文。
  return redactCredentialUrlPaths(value)
    // Authorization 的 Bearer/Basic 值可能含 base64 标点，必须整段遮挡到行或分隔符结束。
    .replace(/(authorization\s*[:=]\s*(?:bearer|basic)\s+)[^\r\n,;"'`<>]+/gi, "$1[redacted]")
    // URL userinfo 本身就是凭据，整段替换，避免用户名或密码进入导出文件。
    .replace(/https?:\/\/[^\s\/"'`<>@]+@/gi, (prefix) => prefix.replace(/\/\/.*@/, "//[redacted]@"))
    .replace(/(https?:\/\/[^\s/"'`<>?#]+(?:\/[^\s"'`<>?#]*)?)(\?[^\s"'`<>#]*)/g, (_whole, base: string, query: string) => {
      const kept = new URLSearchParams(query.slice(1));
      for (const key of Array.from(kept.keys())) {
        if (SENSITIVE_QUERY_KEY.test(key)) kept.delete(key);
      }
      const suffix = kept.toString();
      return suffix ? `${base}?${suffix}` : base;
    })
    // Fragment 不会发送给服务器，却可能包含前端路由 token 或其他本地状态；导出时全部移除。
    .replace(/(https?:\/\/[^\s"'`<>#]+)#[^\s"'`<>]*/gi, "$1")
    // 非标准 Authorization 值也遮挡，但不要再次改写已经保留的 Bearer/Basic 方案名。
    .replace(/(authorization\s*[:=]\s*)(?!(?:bearer|basic)\s+)[^\s,;"'`<>]+/gi, "$1[redacted]")
    // 普通文本里的 key=value 也需要遮挡；URL 已先处理，因此不会误删安全查询参数。
    .replace(/((?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|credential)\s*[:=]\s*)[^\s,;"'`<>]+/gi, "$1[redacted]")
    // 引号包裹的 Windows/UNC/Unix 绝对路径可以安全跨越空格，先整体替换。
    .replace(QUOTED_ABSOLUTE_PATH, (whole: string) => `${whole[0]}[local path]${whole[0]}`)
    // 未加引号的绝对路径也遮挡到常见字段分隔符或行尾，包括路径内空格。
    .replace(ABSOLUTE_PATH, (_whole, prefix: string) => `${prefix}[local path]`);
}

/** 递归复制并脱敏 Trace 等结构化导出数据，不修改页面中正在展示的原对象。 */
export function redactExportData(value: unknown, key = ""): unknown {
  if (SENSITIVE_KEY.test(key)) return "[redacted]";
  if (typeof value === "string") return redactText(value);
  if (Array.isArray(value)) return value.map((item) => redactExportData(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>)
      .map(([childKey, childValue]) => [childKey, redactExportData(childValue, childKey)]));
  }
  return value;
}

/** Markdown 也是纯文本导出，复用相同路径和 URL 规则。 */
export function redactExportText(value: string): string {
  return redactText(value);
}

function boundedString(value: unknown, maxLength: number): string | null {
  if (value === null || value === undefined) return null;
  const text = redactExportText(String(value));
  return text.length <= maxLength ? text : `${text.slice(0, maxLength)}…[truncated]`;
}

function boundedRecord(value: unknown, maxEntries = 24, maxString = 2000): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).slice(0, maxEntries).map(([key, item]) => {
    if (SENSITIVE_KEY.test(key)) return [key, "[redacted]"];
    if (typeof item === "string") return [key, boundedString(item, maxString)];
    if (typeof item === "number" || typeof item === "boolean" || item === null) return [key, item];
    if (Array.isArray(item)) return [key, item.slice(0, 20).map((entry) => boundedString(entry, 500))];
    return [key, "[nested data omitted]"];
  }));
}

/** 构建有界、显式的 Trace 导出结构，避免递归复制和 stringify 任意深度的原始响应。 */
export function buildBoundedTraceExport(
  trace: AgentTraceResponse,
  repository: { alias: string; commit: string | null | undefined; snapshot_id: string | null | undefined },
): Record<string, unknown> {
  const maxSteps = 200;
  const maxEvidencePerStep = 50;
  const maxEvidence = 500;
  const originalSteps = trace.steps.length;
  const originalEvidence = trace.steps.reduce((total, step) => total + (step.evidence_refs || []).length, 0);
  const steps = trace.steps.slice(0, maxSteps).map((step) => {
    const originalEvidence = (step.evidence_refs || []).length;
    return {
      step_no: step.step_no,
      step_type: boundedString(step.step_type, 100),
      tool_name: boundedString(step.tool_name, 200),
      status: step.status,
      token_count: step.token_count,
      duration_ms: step.duration_ms,
      input: boundedRecord(step.input),
      output_summary: boundedRecord(step.output_summary),
      error: boundedString(step.error, 4000),
      evidence_refs: (step.evidence_refs || []).slice(0, maxEvidencePerStep).map((item) => boundedRecord(item, 16, 1000)),
      _evidence_original_count: originalEvidence,
    };
  });
  const slicedEvidence = steps.flatMap((step) => step.evidence_refs as unknown[]);
  const evidence = slicedEvidence.slice(0, maxEvidence);
  const perStepEvidenceTruncated = steps.some((step) => (step._evidence_original_count as number) > maxEvidencePerStep);
  const evidenceTruncated = perStepEvidenceTruncated || slicedEvidence.length > maxEvidence;
  for (const step of steps) delete (step as Record<string, unknown>)._evidence_original_count;
  const payload: Record<string, unknown> = {
    format: "repomind-trace-export-v2",
    generated_at: new Date().toISOString(),
    repository: { alias: boundedString(repository.alias, 300), commit: repository.commit, snapshot_id: repository.snapshot_id },
    trace: {
      id: trace.id, repo_id: trace.repo_id, snapshot_id: trace.snapshot_id,
      entrypoint: boundedString(trace.entrypoint, 200), question: boundedString(trace.question, 8000),
      mode: boundedString(trace.mode, 100), status: trace.status, planner_version: boundedString(trace.planner_version, 100),
      final_answer: boundedString(trace.final_answer, 50000), confidence: boundedString(trace.confidence, 100),
      token_count: trace.token_count, error: boundedString(trace.error, 4000), created_at: trace.created_at,
      completed_at: trace.completed_at, steps,
    },
    evidence,
    truncation: {
      steps_truncated: originalSteps > maxSteps,
      omitted_steps: Math.max(0, originalSteps - maxSteps),
      evidence_truncated: evidenceTruncated,
      evidence_per_step_truncated: perStepEvidenceTruncated,
      omitted_evidence: Math.max(0, slicedEvidence.length - evidence.length),
    },
  };
  const byteLength = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).byteLength;
  const traceBlock = payload.trace as Record<string, unknown>;
  const truncation = payload.truncation as Record<string, unknown>;
  const serialize = () => byteLength(payload);
  if (serialize() >= MAX_EXPORT_BYTES) {
    traceBlock.steps = (traceBlock.steps as unknown[]).slice(0, 40);
    payload.evidence = evidence.slice(0, 100);
    traceBlock.question = boundedString(trace.question, 2000);
    traceBlock.final_answer = boundedString(trace.final_answer, 12000);
    truncation.size_limited = true;
  }
  if (serialize() >= MAX_EXPORT_BYTES) {
    traceBlock.steps = (traceBlock.steps as Array<Record<string, unknown>>).slice(0, 10).map((step) => ({
      step_no: step.step_no, step_type: step.step_type, tool_name: step.tool_name, status: step.status,
      token_count: step.token_count, duration_ms: step.duration_ms, error: boundedString(step.error, 500),
      evidence_refs: (step.evidence_refs as unknown[]).slice(0, 5),
    }));
    payload.evidence = (payload.evidence as unknown[]).slice(0, 20);
    traceBlock.question = boundedString(trace.question, 500);
    traceBlock.final_answer = boundedString(trace.final_answer, 2000);
  }
  if (serialize() >= MAX_EXPORT_BYTES) {
    payload.repository = { alias: boundedString(repository.alias, 100), commit: repository.commit, snapshot_id: repository.snapshot_id };
    payload.evidence = [];
    traceBlock.steps = [];
    traceBlock.question = boundedString(trace.question, 200);
    traceBlock.final_answer = boundedString(trace.final_answer, 500);
  }
  if (serialize() >= MAX_EXPORT_BYTES) {
    payload.trace = { id: trace.id, repo_id: trace.repo_id, snapshot_id: trace.snapshot_id, status: trace.status };
    payload.evidence = [];
    payload.truncation = { size_limited: true, steps_truncated: originalSteps > 0, evidence_truncated: evidenceTruncated };
  }
  const finalSteps = (payload.trace as Record<string, unknown>).steps;
  const finalEvidence = payload.evidence;
  const retainedStepCount = Array.isArray(finalSteps) ? finalSteps.length : 0;
  const retainedEvidenceCount = Array.isArray(finalEvidence) ? finalEvidence.length : 0;
  const finalTruncation = payload.truncation as Record<string, unknown>;
  finalTruncation.steps_truncated = originalSteps > retainedStepCount;
  finalTruncation.omitted_steps = Math.max(0, originalSteps - retainedStepCount);
  finalTruncation.evidence_truncated = originalEvidence > retainedEvidenceCount;
  finalTruncation.evidence_per_step_truncated = trace.steps.some((step, index) => {
    const retainedStep = Array.isArray(finalSteps) ? finalSteps[index] as Record<string, unknown> | undefined : undefined;
    const retainedRefs = retainedStep && Array.isArray(retainedStep.evidence_refs) ? retainedStep.evidence_refs.length : 0;
    return (step.evidence_refs || []).length > retainedRefs;
  });
  finalTruncation.omitted_evidence = Math.max(0, originalEvidence - retainedEvidenceCount);
  return payload;
}

/** Electron 保存桥的共享契约别名，保持现有 renderer 调用点兼容。 */
export type TextExportRequest = SaveTextRequest;

type TextExportSave = (request: SaveTextRequest) => Promise<SaveTextResult>;

export type TextExportOutcome =
  | { status: "saved"; fileName?: string }
  | { status: "cancelled" }
  | { status: "failed"; error: string };

/** 执行注入的桌面保存桥，并把取消和异常转换为 UI 可直接使用的结果。 */
export async function saveTextExport(
  saveText: TextExportSave | undefined,
  request: TextExportRequest,
): Promise<TextExportOutcome> {
  if (!saveText) {
    return { status: "failed", error: "当前环境不支持文件导出，请从 RepoMind 桌面端操作。" };
  }
  try {
    const result = await saveText(request);
    return result.saved
      ? { status: "saved", fileName: result.fileName }
      : { status: "cancelled" };
  } catch (error) {
    return { status: "failed", error: error instanceof Error ? error.message : "未知错误" };
  }
}
