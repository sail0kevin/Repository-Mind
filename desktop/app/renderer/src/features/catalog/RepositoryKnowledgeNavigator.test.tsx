import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CatalogTreeNode } from "../../../services/apiClient";
import { RepositoryKnowledgeNavigator } from "./RepositoryKnowledgeNavigator";

const tree: CatalogTreeNode[] = [{
  id: "root",
  kind: "repository_overview",
  title: "仓库总览",
  path: "",
  children: [{ id: "file", kind: "file", title: "main.py", path: "main.py", children: [] }],
}];

afterEach(cleanup);

describe("RepositoryKnowledgeNavigator", () => {
  it("renders an operable ARIA tree without owning data loading", () => {
    const onSelect = vi.fn();
    render(
      <RepositoryKnowledgeNavigator
        catalogRoots={tree}
        isLoading={false}
        repositories={[]}
        selectedCatalogItemId={null}
        selectedRepoId="repo"
        selectedSnapshotId="snapshot"
        snapshots={[]}
        onCatalogItemSelect={onSelect}
        onRefreshRepositories={vi.fn()}
        onRepositorySelect={vi.fn()}
        onSnapshotSelect={vi.fn()}
      />,
    );

    const root = screen.getByRole("treeitem", { name: /仓库总览/ });
    const file = screen.getByRole("treeitem", { name: /main.py/ });
    expect(screen.getByRole("tree", { name: "当前 Snapshot 的知识目录" })).toBeVisible();
    expect(root).toHaveAttribute("aria-expanded", "true");
    expect(root).toHaveAttribute("tabindex", "0");
    expect(file).toHaveAttribute("tabindex", "-1");
    fireEvent.click(root);
    expect(onSelect).toHaveBeenCalledWith(tree[0]);
    expect(root).toHaveAttribute("aria-expanded", "true");
    fireEvent.keyDown(root, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith(tree[0]);
    fireEvent.keyDown(root, { key: "ArrowRight" });
    expect(file).toHaveFocus();
    expect(file).toHaveAttribute("tabindex", "0");
    expect(root).toHaveAttribute("tabindex", "-1");
  });
});
