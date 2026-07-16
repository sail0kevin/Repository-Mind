import { BookOpen, GitCommitHorizontal, Sparkles } from "lucide-react";

import type { CatalogItemResponse, SnapshotResponse } from "../../../services/apiClient";

/** Catalog 卡片详情使用后端保存的摘要和 Evidence 引用，不重新读取目标仓库。 */
export function CatalogWorkspace(props: {
  item: CatalogItemResponse | null;
  snapshot: SnapshotResponse | null;
}) {
  if (!props.item) {
    return (
      <div className="af-empty">
        <BookOpen size={42} />
        <p>从左侧知识树选择仓库总览、阅读指南、文件或符号卡片。</p>
      </div>
    );
  }

  return (
    <div className="af-catalog-workspace">
      <div className="af-catalog-heading">
        <div>
          <span className="af-catalog-kind">{props.item.kind}</span>
          <h2>{props.item.title}</h2>
          {props.item.path && <code>{props.item.path}</code>}
        </div>
        <div className="af-catalog-meta">
          <span><GitCommitHorizontal size={13} /> {props.snapshot?.commit.slice(0, 12) || "未知 commit"}</span>
          <span><Sparkles size={13} /> {props.item.generation_method === "rule" ? "规则生成" : "LLM 增强"}</span>
        </div>
      </div>
      <div className="af-answer">
        <p>{props.item.summary}</p>
      </div>
      <section className="af-section">
        <div className="af-section-title">结构化详情</div>
        <pre className="af-json-box">{JSON.stringify(props.item.details, null, 2)}</pre>
      </section>
      <section className="af-section">
        <div className="af-section-title">可追溯来源</div>
        <div className="af-catalog-evidence-list">
          {props.item.source_evidence_ids.map((evidenceId) => <code key={evidenceId}>{evidenceId}</code>)}
          {props.item.source_evidence_ids.length === 0 && <span className="af-hint">该卡片暂未记录 Evidence ID。</span>}
        </div>
        {props.item.known_unknowns.length > 0 && (
          <div className="af-settings-tip"><strong>已知限制：</strong>{props.item.known_unknowns.join("；")}</div>
        )}
      </section>
    </div>
  );
}
