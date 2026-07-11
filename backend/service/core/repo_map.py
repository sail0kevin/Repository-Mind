"""
这个文件负责基于扫描结果生成仓库地图和规则型摘要。
它在整个框架里扮演“项目结构理解”的角色，帮助检索和问答先判断仓库的关键区域。
"""

from collections import Counter
from pathlib import PurePosixPath


README_NAMES = {"readme.md", "readme.txt", "readme"}
CONFIG_NAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "vite.config.ts",
    "vite.config.js",
    "tsconfig.json",
    "dockerfile",
    "docker-compose.yml",
}
ENTRYPOINT_NAMES = {
    "main.py",
    "app.py",
    "server.py",
    "index.js",
    "index.ts",
    "main.ts",
    "main.tsx",
    "main.jsx",
    "main.tsx",
}
DOC_DIR_NAMES = {"docs", "doc", "documentation"}
SOURCE_DIR_NAMES = {"src", "app", "service", "services", "backend", "frontend", "desktop"}
TEST_DIR_NAMES = {"test", "tests", "spec", "__tests__"}


def first_path_part(path: str) -> str:
    """返回文件路径的第一层目录；根目录文件用 / 表示。"""

    parts = PurePosixPath(path).parts
    if len(parts) <= 1:
        return "/"
    return parts[0]


def classify_file(file_record: dict) -> str:
    """把文件粗略归类为 README、文档、源码、测试、配置或其他。"""

    relative_path = file_record["relative_path"]
    lower_path = relative_path.lower()
    name = PurePosixPath(lower_path).name
    parts = set(PurePosixPath(lower_path).parts)
    if name in README_NAMES:
        return "readme"
    if parts & DOC_DIR_NAMES or file_record.get("language") == "markdown":
        return "docs"
    if file_record.get("is_test_file") or parts & TEST_DIR_NAMES:
        return "tests"
    if name in CONFIG_NAMES or file_record.get("language") in {"json", "yaml", "toml"}:
        return "config"
    if parts & SOURCE_DIR_NAMES or file_record.get("language") in {"python", "javascript", "typescript"}:
        return "source"
    return "other"


def is_entrypoint_candidate(file_record: dict) -> bool:
    """判断文件是否可能是项目入口。"""

    lower_path = file_record["relative_path"].lower()
    name = PurePosixPath(lower_path).name
    if name in ENTRYPOINT_NAMES:
        return True
    return lower_path.endswith("/src/main.tsx") or lower_path.endswith("/src/main.ts")


def pick_reading_order(files: list[dict], limit: int = 12) -> list[str]:
    """生成建议阅读顺序，优先 README、配置、入口、源码、测试。"""

    priority = {"readme": 0, "config": 1, "source": 2, "docs": 3, "tests": 4, "other": 5}
    sorted_files = sorted(
        files,
        key=lambda item: (
            priority[classify_file(item)],
            0 if is_entrypoint_candidate(item) else 1,
            item["relative_path"].count("/"),
            item["relative_path"],
        ),
    )
    return [item["relative_path"] for item in sorted_files[:limit]]


def build_repo_map(repo: dict, files: list[dict], chunk_count: int = 0) -> dict:
    """生成仓库地图和结构统计。"""

    text_files = [item for item in files if item["file_type"] == "text" and item["ignored_reason"] is None]
    category_counts = Counter(classify_file(item) for item in files)
    language_counts = Counter((item.get("language") or "unknown") for item in text_files)
    directory_counts = Counter(first_path_part(item["relative_path"]) for item in files)

    key_files = {
        "readme": [item["relative_path"] for item in files if classify_file(item) == "readme"],
        "config": [item["relative_path"] for item in files if classify_file(item) == "config"][:12],
        "entrypoints": [item["relative_path"] for item in files if is_entrypoint_candidate(item)][:12],
        "docs": [item["relative_path"] for item in files if classify_file(item) == "docs"][:12],
        "tests": [item["relative_path"] for item in files if classify_file(item) == "tests"][:12],
    }
    return {
        "repo_id": repo["id"],
        "alias": repo["alias"],
        "status": repo["status"],
        "branch": repo["branch"],
        "current_commit": repo["commit_hash"],
        "file_count": len(files),
        "indexable_file_count": len(text_files),
        "chunk_count": chunk_count,
        "language_counts": dict(language_counts.most_common()),
        "category_counts": dict(category_counts.most_common()),
        "top_directories": dict(directory_counts.most_common(12)),
        "key_files": key_files,
        "reading_order": pick_reading_order(text_files),
    }


def build_repo_summary(repo_map: dict) -> dict:
    """基于仓库地图生成规则型摘要。"""

    languages = ", ".join(repo_map["language_counts"].keys()) or "未知语言"
    readme = repo_map["key_files"]["readme"][:1]
    entrypoints = repo_map["key_files"]["entrypoints"][:3]
    configs = repo_map["key_files"]["config"][:3]
    summary_lines = [
        f"仓库 {repo_map['alias']} 当前包含 {repo_map['file_count']} 个已扫描文件，其中 {repo_map['indexable_file_count']} 个可索引文本文件。",
        f"主要语言/文本类型：{languages}。",
    ]
    if readme:
        summary_lines.append(f"优先阅读 README：{readme[0]}。")
    if entrypoints:
        summary_lines.append(f"可能入口文件：{', '.join(entrypoints)}。")
    if configs:
        summary_lines.append(f"关键配置文件：{', '.join(configs)}。")
    if repo_map["chunk_count"]:
        summary_lines.append(f"当前已建立 {repo_map['chunk_count']} 个知识片段。")
    else:
        summary_lines.append("当前尚未建立知识片段，建议先执行关键词索引。")

    return {
        "repo_id": repo_map["repo_id"],
        "alias": repo_map["alias"],
        "summary": "".join(summary_lines),
        "languages": list(repo_map["language_counts"].keys()),
        "recommended_reading_order": repo_map["reading_order"],
        "next_steps": [
            "先阅读 README 和关键配置，确认项目用途与启动方式。",
            "再阅读入口文件和 src/app/backend 等核心目录。",
            "索引完成后使用关键词搜索定位具体函数、类或模块。",
        ],
    }
