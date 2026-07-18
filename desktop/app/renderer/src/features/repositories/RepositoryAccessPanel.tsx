import { Activity, Database, FolderPlus, GitBranch, Loader2, PlayCircle } from "lucide-react";

import type { RepoResponse } from "../../../services/apiClient";

/**
 * 仓库接入面板只渲染输入项、索引进度和当前仓库身份。
 * 注册、克隆、轮询任务的顺序仍由 App 中原有处理函数负责。
 */
export function RepositoryAccessPanel(props: {
  alias: string;
  githubUrl: string;
  indexedPercent: number;
  isRegistering: boolean;
  repo: RepoResponse | null;
  repoPath: string;
  registerProgress: string;
  onAliasChange: (value: string) => void;
  onGithubUrlChange: (value: string) => void;
  onOpenDemo: () => void;
  onRegister: () => void;
  onRepoPathChange: (value: string) => void;
}) {
  return (
    <section className="af-section">
      <div className="af-section-title"><Database size={15} /> 仓库接入</div>
      <div className="af-onboarding">
        <div className="af-onboarding-title"><GitBranch size={14} /> 使用顺序</div>
        <ol className="af-onboarding-steps">
          <li>可选：在设置中配置 Chat API Key 和独立的 Embedding</li>
          <li>输入 GitHub URL 或本地仓库路径</li>
          <li>点击注册并索引，等进度到 100%</li>
          <li>开始问答、工作流分析或代码图谱查询</li>
        </ol>
      </div>
      <div className="af-form">
        <label className="af-field-inline">
          <span>公开 GitHub 仓库 URL</span>
          <input aria-label="公开 GitHub 仓库 URL" value={props.githubUrl} onChange={(event) => props.onGithubUrlChange(event.target.value)} placeholder="https://github.com/user/repo" />
        </label>
        <label className="af-field-inline">
          <span>本地 Git 仓库路径</span>
          <input aria-label="本地 Git 仓库路径" value={props.repoPath} onChange={(event) => props.onRepoPathChange(event.target.value)} placeholder={"G:\\projects\\demo"} />
        </label>
        <label className="af-field-inline">
          <span>仓库别名（可选）</span>
          <input aria-label="仓库别名" value={props.alias} onChange={(event) => props.onAliasChange(event.target.value)} placeholder="例如：支付服务" />
        </label>
        <button className="af-btn primary" onClick={props.onRegister} disabled={props.isRegistering}>
          {props.isRegistering ? <Loader2 size={16} className="spin" /> : <FolderPlus size={16} />}
          {props.isRegistering ? "处理中" : "注册并索引"}
        </button>
        <button data-testid="open-demo" className="af-btn secondary" onClick={props.onOpenDemo} disabled={props.isRegistering}>
          <PlayCircle size={16} />
          打开内置 Demo
        </button>
        <span className="af-help">无需网络、无需 API Key；使用本地合成仓库演示 Snapshot、Evidence、Trace 与导出。</span>
      </div>
      <div
        className="af-progress-box"
        data-testid="ingest-progress"
        role="status"
        aria-live="polite"
        aria-busy={props.isRegistering}
      >
        {props.isRegistering ? <Loader2 size={16} className="spin" /> : <Activity size={16} />}
        <div>
          <strong>{props.registerProgress}</strong>
          <div className="af-progress compact"><span style={{ width: `${props.indexedPercent}%` }} /></div>
        </div>
      </div>
      {props.repo && (
        <div className="af-repo-card" data-testid="current-repository">
          <div className="af-repo-title"><GitBranch size={15} /> {props.repo.alias}</div>
          <span>{props.repo.file_count} 个文件 · {props.repo.branch || "未知分支"}</span>
          <span>当前快照：{props.repo.snapshot_id ? props.repo.snapshot_id.slice(0, 18) : "尚未生成"}</span>
          <span className="af-mono">Commit：{(props.repo.commit || props.repo.current_commit || "未知").slice(0, 12)}</span>
          <span className="af-mono">{props.repo.repo_id}</span>
        </div>
      )}
    </section>
  );
}
