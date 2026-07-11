"""
这个文件负责问答会话记录的持久化。
它在整个框架里扮演"会话存储层"的角色：保存每次问答的问题、回答和 trace_id，方便右侧证据流和历史回看。
"""
from __future__ import annotations

import uuid

from service.storage.sqlite_db import get_connection


def create_session_record(repo_id: str, question: str, answer: str, trace_id: str | None = None) -> str:
    """保存一条问答会话记录。"""
    session_id = f"session_{uuid.uuid4().hex}"
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO sessions (id, repo_id, question, answer, trace_id)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, repo_id, question, answer, trace_id),
        )
    return session_id
