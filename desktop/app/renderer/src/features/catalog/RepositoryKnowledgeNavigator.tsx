import { ChevronRight, GitBranch, Library, RefreshCcw } from "lucide-react";

import type { CatalogTreeNode, RepoResponse, SnapshotResponse } from "../../../services/apiClient";

const KIND_LABELS: Record<string, string> = {
  repository_overview: "仓库总览",
  reading_guide: "阅读指南",
  subsystem: "子系统",
  directory: "目录",
  file: "文件",
  symbol: "符号",
};

/**
 * 仓库知识导航把仓库、Snapshot 和 Catalog 放在同一个入口。
 * 历史 Snapshot 只切换后端保存的知识事实，不直接读取已经变化的工作树源码。
 */
export function RepositoryKnowledgeNavigator(props: {
  catalogRoots: CatalogTreeNode[];
  isLoading: boolean;
  repositories: RepoResponse[];
  selectedCatalogItemId: string | null;
  selectedRepoId: string | null;
  selectedSnapshotId: string | null;
  snapshots: SnapshotResponse[];
  onCatalogItemSelect: (item: CatalogTreeNode) => void;
  onRefreshRepositories: () => void;
  onRepositorySelect: (repoId: string) => void;
  onSnapshotSelect: (snapshotId: string) => void;
}) {
  return (
    <section className="af-section">
      <div className="af-section-title"><Library size={15} /> 仓库知识库</div>
      <div className="af-form">
        <label className="af-field-inline">
          <span>已注册仓库</span>
          <select value={props.selectedRepoId ?? ""} onChange={(event) => props.onRepositorySelect(event.target.value)} disabled={props.isLoading || props.repositories.length === 0}>
            <option value="">选择仓库</option>
            {props.repositories.map((repo) => <option key={repo.repo_id} value={repo.repo_id}>{repo.alias}</option>)}
          </select>
        </label>
        <label className="af-field-inline">
          <span>知识快照</span>
          <select value={props.selectedSnapshotId ?? ""} onChange={(event) => props.onSnapshotSelect(event.target.value)} disabled={props.isLoading || props.snapshots.length === 0}>
            <option value="">选择 succeeded 快照</option>
            {props.snapshots.filter((snapshot) => snapshot.status === "succeeded").map((snapshot) => (
              <option key={snapshot.snapshot_id} value={snapshot.snapshot_id}>
                {snapshot.is_active ? "当前 · " : "历史 · "}{snapshot.commit.slice(0, 12)}{snapshot.branch ? ` · ${snapshot.branch}` : ""}
              </option>
            ))}
          </select>
        </label>
        <button className="af-btn secondary" onClick={props.onRefreshRepositories} disabled={props.isLoading}>
          <RefreshCcw size={15} className={props.isLoading ? "spin" : ""} /> 刷新仓库列表
        </button>
      </div>
      <div className="af-catalog-tree">
        {props.catalogRoots.map((root) => (
          <CatalogTreeBranch
            key={root.id}
            item={root}
            level={0}
            selectedId={props.selectedCatalogItemId}
            onSelect={props.onCatalogItemSelect}
          />
        ))}
        {!props.isLoading && props.selectedSnapshotId && props.catalogRoots.length === 0 && <div className="af-empty small">当前快照暂无 Catalog</div>}
        {!props.selectedRepoId && <div className="af-empty small"><GitBranch size={24} />选择仓库后查看快照知识树</div>}
      </div>
    </section>
  );
}

function CatalogTreeBranch(props: {
  item: CatalogTreeNode;
  level: number;
  selectedId: string | null;
  onSelect: (item: CatalogTreeNode) => void;
}) {
  return (
    <>
      <button
        className={`af-catalog-node ${props.selectedId === props.item.id ? "active" : ""}`}
        style={{ paddingLeft: `${8 + props.level * 14}px` }}
        onClick={() => props.onSelect(props.item)}
        title={props.item.path || props.item.title}
      >
        <ChevronRight size={13} />
        <span>{props.item.title}</span>
        <small>{KIND_LABELS[props.item.kind] || props.item.kind}</small>
      </button>
      {props.item.children.map((child) => (
        <CatalogTreeBranch key={child.id} item={child} level={props.level + 1} selectedId={props.selectedId} onSelect={props.onSelect} />
      ))}
    </>
  );
}
