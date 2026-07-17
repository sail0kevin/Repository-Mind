import { FileCode2, GitCommitHorizontal, X } from "lucide-react";

import type { AgentTraceResponse, ChunkDetailResponse } from "../../../services/apiClient";

/**
 * 证据抽屉始终展示快照中持久化的 chunk 内容。
 * 这样即使用户切换到历史 Snapshot，也不会把当前工作树文件误当作旧版本证据。
 */
export function EvidenceDrawer(props: {
  chunk: ChunkDetailResponse | null;
  commit: string | null;
  trace: AgentTraceResponse | null;
  onClose: () => void;
}) {
  if (!props.chunk && !props.trace) {
    return null;
  }

  return (
    <div className="af-evidence-drawer" data-testid={props.trace ? "trace-drawer" : "evidence-drawer"}>
      <div className="af-modal-header">
        <h2><FileCode2 size={18} /> 证据与工具轨迹</h2>
        <button className="af-icon-btn" onClick={props.onClose} title="关闭证据抽屉"><X size={18} /></button>
      </div>
      <div className="af-evidence-drawer-body">
        {props.chunk && (
          <section className="af-section">
            <div className="af-section-title">源码证据</div>
            <div className="af-source-meta">
              <strong>{props.chunk.file_path}</strong>
              <span><GitCommitHorizontal size={13} /> {props.commit?.slice(0, 12) || "未知 commit"}</span>
              <span>行 {props.chunk.start_line ?? "?"} - {props.chunk.end_line ?? "?"}</span>
              <span>{props.chunk.symbol_name || props.chunk.title || props.chunk.chunk_type}</span>
            </div>
            <pre className="af-source-viewer">{withLineNumbers(props.chunk.content, props.chunk.start_line)}</pre>
          </section>
        )}
        {props.trace && (
          <section className="af-section">
            <div className="af-section-title">Main Agent Trace</div>
            <div className="af-answer-meta">
              <span>模式：{props.trace.mode}</span>
              <span>状态：{props.trace.status}</span>
              <span>Token：{props.trace.token_count}</span>
            </div>
            <div className="af-trace-list">
              {props.trace.steps.map((step) => (
                <div className="af-trace-step" data-testid="trace-step" data-step-type={step.step_type} key={step.id}>
                  <strong>{step.step_no}. {step.step_type}{step.tool_name ? ` · ${step.tool_name}` : ""}</strong>
                  <span>{step.status}{step.duration_ms !== null ? ` · ${Math.round(step.duration_ms)}ms` : ""}</span>
                  {step.error && <p>{step.error}</p>}
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function withLineNumbers(content: string, startLine: number | null) {
  const firstLine = startLine ?? 1;
  return content.split("\n").map((line, index) => `${String(firstLine + index).padStart(4, " ")} │ ${line}`).join("\n");
}
