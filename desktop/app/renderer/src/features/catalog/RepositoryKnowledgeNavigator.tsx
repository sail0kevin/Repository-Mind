import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
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

function collectExpandableIds(items: CatalogTreeNode[]) {
  const ids: string[] = [];
  function visit(item: CatalogTreeNode) {
    if (item.children.length > 0) ids.push(item.id);
    item.children.forEach(visit);
  }
  items.forEach(visit);
  return ids;
}

function collectVisibleIds(items: CatalogTreeNode[], expandedIds: Set<string>) {
  const ids: string[] = [];
  function visit(item: CatalogTreeNode) {
    ids.push(item.id);
    if (expandedIds.has(item.id)) item.children.forEach(visit);
  }
  items.forEach(visit);
  return ids;
}

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
  const treeRef = useRef<HTMLDivElement | null>(null);
  const expandableIds = useMemo(() => collectExpandableIds(props.catalogRoots), [props.catalogRoots]);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set(expandableIds));
  const visibleIds = useMemo(() => collectVisibleIds(props.catalogRoots, expandedIds), [expandedIds, props.catalogRoots]);
  const [tabStopId, setTabStopId] = useState<string | null>(() => props.selectedCatalogItemId ?? props.catalogRoots[0]?.id ?? null);

  useEffect(() => {
    // 小白说明：新 Snapshot 的目录结构变化后，默认展开它的可展开节点，首次使用无需逐层点开。
    setExpandedIds(new Set(expandableIds));
  }, [expandableIds]);

  useEffect(() => {
    // 小白说明：树变化或节点折叠后，保证仍有且只有一个可见节点能通过 Tab 进入。
    setTabStopId((current) => {
      if (current && visibleIds.includes(current)) return current;
      if (props.selectedCatalogItemId && visibleIds.includes(props.selectedCatalogItemId)) return props.selectedCatalogItemId;
      return visibleIds[0] ?? null;
    });
  }, [props.selectedCatalogItemId, visibleIds]);

  function toggle(itemId: string, expanded?: boolean) {
    setExpandedIds((previous) => {
      const next = new Set(previous);
      const shouldExpand = expanded ?? !next.has(itemId);
      if (shouldExpand) next.add(itemId);
      else next.delete(itemId);
      return next;
    });
  }

  function focusTreeItem(target: HTMLButtonElement | null | undefined) {
    if (!target) return;
    const targetId = target.dataset.nodeId;
    if (targetId) setTabStopId(targetId);
    target.focus();
  }

  function focusRelative(current: HTMLButtonElement, offset: number) {
    const buttons = Array.from(treeRef.current?.querySelectorAll<HTMLButtonElement>("button[role='treeitem']") ?? []);
    const index = buttons.indexOf(current);
    focusTreeItem(buttons[Math.min(buttons.length - 1, Math.max(0, index + offset))]);
  }

  function handleTreeKeyDown(event: KeyboardEvent<HTMLButtonElement>, item: CatalogTreeNode, parentId: string | null) {
    const hasChildren = item.children.length > 0;
    const expanded = expandedIds.has(item.id);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusRelative(event.currentTarget, 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusRelative(event.currentTarget, -1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusTreeItem(treeRef.current?.querySelector<HTMLButtonElement>("button[role='treeitem']"));
    } else if (event.key === "End") {
      event.preventDefault();
      const buttons = treeRef.current?.querySelectorAll<HTMLButtonElement>("button[role='treeitem']");
      focusTreeItem(buttons?.item(buttons.length - 1));
    } else if (event.key === "ArrowRight" && hasChildren) {
      event.preventDefault();
      if (!expanded) toggle(item.id, true);
      else focusTreeItem(treeRef.current?.querySelector<HTMLButtonElement>(`button[data-parent-id="${CSS.escape(item.id)}"]`));
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      if (hasChildren && expanded) toggle(item.id, false);
      else if (parentId) focusTreeItem(treeRef.current?.querySelector<HTMLButtonElement>(`button[data-node-id="${CSS.escape(parentId)}"]`));
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      props.onCatalogItemSelect(item);
    }
  }

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
      {props.catalogRoots.length > 0 && (
        <div
          ref={treeRef}
          className="af-catalog-tree"
          data-testid="catalog-tree"
          role="tree"
          aria-label="当前 Snapshot 的知识目录"
          aria-busy={props.isLoading}
        >
          {props.catalogRoots.map((root) => (
            <CatalogTreeBranch
              key={root.id}
              item={root}
              level={1}
              parentId={null}
              expandedIds={expandedIds}
              selectedId={props.selectedCatalogItemId}
              tabStopId={tabStopId}
              onFocusItem={setTabStopId}
              onSelect={props.onCatalogItemSelect}
              onToggle={toggle}
              onKeyDown={handleTreeKeyDown}
            />
          ))}
        </div>
      )}
      {!props.isLoading && props.selectedSnapshotId && props.catalogRoots.length === 0 && <div className="af-empty small" role="status">当前快照暂无 Catalog</div>}
      {!props.selectedRepoId && <div className="af-empty small" role="status"><GitBranch size={24} />选择仓库后查看快照知识树</div>}
    </section>
  );
}

function CatalogTreeBranch(props: {
  item: CatalogTreeNode;
  level: number;
  parentId: string | null;
  expandedIds: Set<string>;
  selectedId: string | null;
  tabStopId: string | null;
  onFocusItem: (itemId: string) => void;
  onSelect: (item: CatalogTreeNode) => void;
  onToggle: (itemId: string, expanded?: boolean) => void;
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>, item: CatalogTreeNode, parentId: string | null) => void;
}) {
  const hasChildren = props.item.children.length > 0;
  const expanded = props.expandedIds.has(props.item.id);
  return (
    <div role="none">
      <button
        type="button"
        role="treeitem"
        className={`af-catalog-node ${props.selectedId === props.item.id ? "active" : ""}`}
        style={{ paddingLeft: `${8 + (props.level - 1) * 14}px` }}
        aria-level={props.level}
        aria-selected={props.selectedId === props.item.id}
        aria-expanded={hasChildren ? expanded : undefined}
        aria-owns={hasChildren && expanded ? `catalog-group-${props.item.id}` : undefined}
        tabIndex={props.tabStopId === props.item.id ? 0 : -1}
        data-node-id={props.item.id}
        data-parent-id={props.parentId ?? undefined}
        onFocus={() => props.onFocusItem(props.item.id)}
        onClick={() => props.onSelect(props.item)}
        onKeyDown={(event) => props.onKeyDown(event, props.item, props.parentId)}
        title={props.item.path || props.item.title}
      >
        <span
          className="af-catalog-toggle"
          aria-hidden="true"
          onClick={(event) => {
            if (!hasChildren) return;
            event.stopPropagation();
            props.onToggle(props.item.id);
          }}
        >
          <ChevronRight size={13} style={{ visibility: hasChildren ? "visible" : "hidden" }} />
        </span>
        <span>{props.item.title}</span>
        <small>{KIND_LABELS[props.item.kind] || props.item.kind}</small>
      </button>
      {hasChildren && expanded && (
        <div
          id={`catalog-group-${props.item.id}`}
          role="group"
          aria-label={`${props.item.title} 的子节点`}
        >
          {props.item.children.map((child) => (
            <CatalogTreeBranch
              key={child.id}
              item={child}
              level={props.level + 1}
              parentId={props.item.id}
              expandedIds={props.expandedIds}
              selectedId={props.selectedId}
              tabStopId={props.tabStopId}
              onFocusItem={props.onFocusItem}
              onSelect={props.onSelect}
              onToggle={props.onToggle}
              onKeyDown={props.onKeyDown}
            />
          ))}
        </div>
      )}
    </div>
  );
}
