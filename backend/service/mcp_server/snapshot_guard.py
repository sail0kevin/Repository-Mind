"""
这个文件负责把仓库/快照的归属和状态校验结果，转换成 MCP 能直接使用的结构（不依赖 FastAPI 的 HTTPException）。
校验规则与 service/api/v1/repos.py 的 resolve_product_snapshot 保持一致：
只有 succeeded 快照可用于查询；显式传入的 snapshot_id 必须真的属于 repo_id。
"""
from __future__ import annotations

from dataclasses import dataclass

from service.storage.repository_store import get_repo_record
from service.storage.snapshot_store import get_active_snapshot, get_snapshot


@dataclass(frozen=True)
class SnapshotGuardError:
    status: str  # "not_found" | "error"
    message: str


@dataclass(frozen=True)
class SnapshotGuardResult:
    repo: dict
    snapshot: dict


def resolve_repo_and_snapshot(
    repo_id: str, snapshot_id: str | None = None
) -> SnapshotGuardResult | SnapshotGuardError:
    """校验 repo_id 存在、snapshot 归属 repo_id 且状态为 succeeded；未显式指定时取 active succeeded 快照。"""
    repo_id = (repo_id or "").strip()
    if not repo_id:
        return SnapshotGuardError(status="error", message="repo_id 不能为空。")

    repo = get_repo_record(repo_id)
    if repo is None:
        return SnapshotGuardError(status="not_found", message=f"没有找到 repo_id={repo_id} 对应的仓库。")

    if snapshot_id:
        snapshot_id = snapshot_id.strip()
        snapshot = get_snapshot(snapshot_id)
        if snapshot is None or snapshot["repo_id"] != repo_id:
            return SnapshotGuardError(
                status="not_found",
                message=f"snapshot_id={snapshot_id} 不属于 repo_id={repo_id}，或不存在。",
            )
        if snapshot["status"] != "succeeded":
            return SnapshotGuardError(
                status="not_found",
                message=f"snapshot_id={snapshot_id} 当前状态为 {snapshot['status']}，只有 succeeded 快照可用于查询。",
            )
        return SnapshotGuardResult(repo=repo, snapshot=snapshot)

    snapshot = get_active_snapshot(repo_id)
    if snapshot is None:
        return SnapshotGuardError(
            status="not_found",
            message=f"repo_id={repo_id} 还没有可用的 succeeded 活跃快照，请先完成索引构建。",
        )
    return SnapshotGuardResult(repo=repo, snapshot=snapshot)
