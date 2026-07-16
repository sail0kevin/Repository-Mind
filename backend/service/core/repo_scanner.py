"""
这个文件负责本地 Git 仓库的校验、扫描和基础信息采集。
它在整个框架里扮演"仓库扫描层"的角色：判断路径是否合法、识别提取文件清单、获取分支/commit 等信息。
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path, PurePath

# 默认忽略的目录名称。只比较路径中的完整目录段，避免误伤名字相近的普通文件。
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

# 只有明确支持按文本读取的文件才进入索引，避免把图片、压缩包等内容交给文本解析器。
INDEXABLE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".toml",
    ".yml",
    ".yaml",
    ".txt",
}
INDEXABLE_FILENAMES = {
    "dockerfile",
    "makefile",
    "readme",
    "license",
    ".gitignore",
    ".dockerignore",
}
TEST_DIRECTORY_NAMES = {"test", "tests", "spec", "specs", "__tests__"}
TEST_FILE_SUFFIXES = ("_test", ".test", ".spec")
MAX_FULL_SCAN_BYTES = 10 * 1024 * 1024


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
    """读取当前分支名；detached HEAD 合法并明确返回 None。"""
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip() or None
    except subprocess.CalledProcessError:
        return None


def ensure_clean_worktree(repo_path: Path) -> None:
    """M1 的 commit 快照只接受干净工作树，避免把未提交内容伪装成 HEAD。"""
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.stdout.strip():
        raise RepositoryScanError("仓库工作树存在未提交或未跟踪变更，请先提交、暂存处理或清理后再刷新索引。")


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


def detect_language(path: PurePath) -> str | None:
    """根据文件名和扩展名识别语言；无法识别时返回 None。"""
    mapping = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".json": "json",
        ".md": "markdown",
        ".toml": "toml",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".txt": "text",
    }
    language = mapping.get(path.suffix.lower())
    if language is not None:
        return language
    if path.name.lower() in INDEXABLE_FILENAMES:
        return "text"
    return None


def is_test_file(path: PurePath) -> bool:
    """统一判断常见 Python、JavaScript 和 TypeScript 测试文件命名。"""
    lower_parts = tuple(part.lower() for part in path.parts)
    if any(part in TEST_DIRECTORY_NAMES for part in lower_parts[:-1]):
        return True

    # 去掉最后一个扩展名后再判断，可覆盖 test_api.py、api_test.py、api.spec.ts 等形式。
    stem = path.stem.lower()
    return stem.startswith("test_") or stem == "test" or stem.endswith(TEST_FILE_SUFFIXES)


def is_binary_content(content: bytes) -> bool:
    """用内容判断文件是否为二进制；UTF-16 文本不会因为含 NUL 字节被误判。"""
    sample = content[:8192]
    if not sample:
        return False
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    if b"\x00" in sample:
        return True
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def is_indexable_file(path: PurePath, *, is_binary: bool) -> bool:
    """统一判断文件能否进入文本索引：必须是支持的文本类型且不是二进制。"""
    if is_binary:
        return False
    return path.suffix.lower() in INDEXABLE_EXTENSIONS or path.name.lower() in INDEXABLE_FILENAMES


def decode_text_content(content: bytes) -> str:
    """把已确认的文本字节转换成字符串，兼容带 BOM 的 UTF-16 文本。"""
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        return content.decode("utf-16")
    return content.decode("utf-8")


def count_text_lines(content: bytes) -> int:
    """按用户看到的逻辑行计数；空文件是 0 行，末尾换行不会凭空多算一行。"""
    if not content:
        return 0
    return len(decode_text_content(content).splitlines())


def scan_repository_files(repo_path: Path, *, retain_indexable_bytes: bool = True) -> list[dict]:
    """扫描仓库目录；可选缓存可索引字节供 ingest 复用，避免重复读取。"""
    files: list[dict] = []
    for candidate in repo_path.rglob("*"):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(repo_path)
        if any(part in IGNORED_NAMES for part in relative.parts[:-1]):
            continue
        try:
            size_bytes = candidate.stat().st_size
            supported_type = (relative.suffix.lower() in INDEXABLE_EXTENSIONS
                              or relative.name.lower() in INDEXABLE_FILENAMES)
            # 大型且扩展名不支持的文件无需全量读取；先按路径/类型/大小排除。
            if not supported_type and size_bytes > MAX_FULL_SCAN_BYTES:
                content = b""
                binary = False
            else:
                content = candidate.read_bytes()
                binary = is_binary_content(content)
        except OSError:
            continue

        indexable = supported_type and not binary
        ignored_reason = None if indexable else ("binary" if binary else "unsupported_file_type")
        files.append(
            {
                "relative_path": relative.as_posix(),
                "absolute_path": str(candidate),
                "language": detect_language(relative),
                # 当前解析器只区分可读取文本和其他文件；代码/配置类别由 language 字段继续表达。
                "file_type": "text" if indexable else ("binary" if binary else "other"),
                "extension": candidate.suffix or None,
                "size_bytes": size_bytes,
                "line_count": count_text_lines(content) if indexable else None,
                "is_binary": binary,
                "is_test_file": is_test_file(relative),
                "ignored_reason": ignored_reason,
                "hash": hashlib.sha1(content).hexdigest(),
                "parse_status": "pending" if indexable else "skipped",
                **({"captured_bytes": content} if retain_indexable_bytes and indexable else {}),
            }
        )
    return files
