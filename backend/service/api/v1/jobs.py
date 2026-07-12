"""
这个文件负责后台任务状态的查询接口。
它在整个框架里扮演"任务轮询 API"的角色：让前端能查询 ingest / workflow_analysis 等异步任务的进度。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from service.storage.job_store import get_job_record

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    """查询单个后台任务的状态。"""
    record = get_job_record(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="没有找到指定任务。")
    return {
        "id": record["id"],
        "repo_id": record["repo_id"],
        "job_type": record["job_type"],
        "status": record["status"],
        "progress": record["progress"],
        "message": record["message"],
        "error": record["error"],
        "started_at": record["started_at"],
        "finished_at": record["finished_at"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }
