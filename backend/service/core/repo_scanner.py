"""
这个文件负责本地 Git 仓库的校验、扫描和基础信息采集。
它在整个框架里扮演"仓库扫描层"的角色：判断路径是否合法、识别提取文件清单、获取分支/commit 等信息。
"""
from __future__ import annotations

import asyncio
import hashlib
import subprocess
from pathlib import Path

# 默认忽略的目录后缀
IGNORED_NAMES = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".next",
    ".venv",
    "venv",
}


class RepositoryScanError(Exception):
    """仓库扫描异常。"""


def resolve_repository_path(repo_path: str) -> Path:
    """解析并校验仓库路径。"""
    path = Path(repo_path).expanduser().resolve()
    if not path.exists():
        raise RepositoryScanError(f"路径不存在：{path}")
    if not path.is_dir():
        raise RepositoryScanError(f"路径不是目录：{path}")
    return path


def validate_git_repository(repo_path: Path) -> None:
    """校验路径是否为一个 Git 仓库。"""
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        raise RepositoryScanError(f"指定路径不是 Git 仓库：{repo_path}")


def get_current_branch(repo_path: Path) -> str | None:
    """读取当前分支名。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_current_commit(repo_path: Path) -> str | None:
    """读取当前 HEAD 的 commit hash。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def _detect_language(extension: str) -> tuple[str | None, str, bool]:
    """根据扩展名识别语言、文件类型和是否测试文件。"""
    mapping = {
        ".py": ("python", "code"),
        ".ts": ("typescript", "code"),
        ".tsx": ("typescript", "code"),
        ".js": ("javascript", "code"),
        ".jsx": ("javascript", "code"),
        ".json": ("json", "config"),
        ".md": ("markdown", "docs"),
        ".toml": ("toml", "config"),
        ".yml": ("yaml", "config"),
        ".yaml": ("yaml", "config"),
        ".txt": ("text", "docs"),
    }
    language, file_type = mapping.get(extension.lower(), (None, "other"))
    return language, file_type, False


def scan_repository_files(repo_path: Path) -> list[dict]:
    """扫描仓库目录，生成文件记录列表。"""
    files: list[dict] = []
    for candidate in repo_path.rglob("*"):
        if not candidate.is_file():
            continue
        if any(part in IGNORED_NAMES for part in candidate.parts):
            continue
        relative = candidate.relative_to(repo_path)
        extension = candidate.suffix
        language, file_type, is_test = _detect_language(extension)
        try:
            content = candidate.read_bytes()
        except OSError:
            continue
        size = len(content)
        is_binary = b"\x00" in content[:4096]
        files.append(
            {
                "relative_path": relative.as_posix(),
                "absolute_path": str(candidate),
                "language": language,
                "file_type": file_type,
                "extension": extension or None,
                "size_bytes": size,
                "line_count": None,
                "is_binary": is_binary,
                "is_test_file": is_test,
                "ignored_reason": None,
                "hash": hashlib.sha1(content).hexdigest(),
                "parse_status": "pending",
            }
        )
    return files
