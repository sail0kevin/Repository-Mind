"""
这个文件负责 RepoMind 的首次仓库工作流分析。
它用规则优先的轻量 Agent 分工读取代码、文档、配置和安全风险，并生成可追溯报告。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import ast
import json
import re
import subprocess
from urllib.parse import urlparse
from uuid import uuid4

from service.config.settings import get_settings
from service.core.repo_map import build_repo_map, build_repo_summary, classify_file
from service.core.repo_scanner import get_current_branch, get_current_commit, scan_repository_files, validate_git_repository
from service.storage.chunk_store import count_chunks
from service.storage.repository_store import create_repo_record, list_file_records, replace_file_records


@dataclass(frozen=True)
class WorkflowFinding:
    """工作流 Agent 产出的单条发现。"""

    title: str
    detail: str
    severity: str = "info"
    evidence: list[dict] | None = None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "detail": self.detail,
            "severity": self.severity,
            "evidence": self.evidence or [],
        }


GITHUB_URL_PATTERN = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
SECRET_PATTERNS = (
    ("疑似硬编码密钥", re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*=\s*['\"][^'\"]{8,}['\"]")),
    ("疑似私钥内容", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)
SECURITY_RULES = (
    ("使用 eval", "high", re.compile(r"\beval\s*\("), "eval 会执行动态字符串，容易放大注入风险。"),
    ("使用 exec", "high", re.compile(r"\bexec\s*\("), "exec 会执行动态代码，建议改为显式函数或白名单映射。"),
    ("使用 pickle.loads", "high", re.compile(r"\bpickle\.loads\s*\("), "pickle 反序列化不可信数据可能导致任意代码执行。"),
    ("yaml.load 未指定安全加载器", "medium", re.compile(r"\byaml\.load\s*\("), "建议使用 yaml.safe_load 或显式 SafeLoader。"),
    ("subprocess shell=True", "medium", re.compile(r"subprocess\.[A-Za-z_]+\([^\n]*shell\s*=\s*True"), "shell=True 会扩大命令注入风险。"),
)


def normalize_github_url(remote_url: str) -> tuple[str, str, str]:
    """校验并规范化公开 GitHub 仓库 URL。"""

    parsed = urlparse(remote_url.strip())
    candidate = remote_url.strip()
    if parsed.scheme and parsed.netloc.lower() != "github.com":
        raise ValueError("当前只支持 github.com 的公开仓库 URL。")
    match = GITHUB_URL_PATTERN.match(candidate)
    if not match:
        raise ValueError("请输入形如 https://github.com/owner/repo 的公开仓库地址。")
    owner, repo = match.groups()
    normalized = f"https://github.com/{owner}/{repo}.git"
    return owner, repo, normalized


def clone_public_github_repo(remote_url: str) -> Path:
    """把公开 GitHub 仓库浅克隆到本地数据目录。"""

    owner, repo, normalized_url = normalize_github_url(remote_url)
    settings = get_settings()
    clone_root = settings.paths.data_dir / "repos"
    clone_root.mkdir(parents=True, exist_ok=True)
    target = clone_root / f"{owner}__{repo}"
    if target.exists() and (target / ".git").exists():
        return target
    if target.exists():
        raise ValueError(f"目标目录已存在但不是 Git 仓库：{target}")

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", normalized_url, str(target)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or "git clone 失败。"
        raise ValueError(f"克隆公开仓库失败：{message}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("克隆公开仓库超时，请换一个更小的仓库或稍后重试。") from exc
    return target


def register_cloned_repository(repo_path: Path, remote_url: str, alias: str | None = None) -> str:
    """把克隆后的仓库登记到 RepoMind 本地库。"""

    validate_git_repository(repo_path)
    scanned_files = scan_repository_files(repo_path)
    repo_id = create_repo_record(
        repo_path=repo_path,
        alias=alias or repo_path.name,
        remote_url=remote_url,
        branch=get_current_branch(repo_path),
        current_commit=get_current_commit(repo_path),
    )
    replace_file_records(repo_id, scanned_files)
    return repo_id


def read_text_sample(path: Path, max_chars: int = 12000) -> str:
    """读取分析所需的文本样本，避免把超大文件完整加载进内存。"""

    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except OSError:
        return ""


def evidence_for_file(file_record: dict, start_line: int | None = None, end_line: int | None = None, reason: str = "workflow analysis") -> dict:
    return {
        "file_path": file_record["relative_path"],
        "chunk_id": "",
        "start_line": start_line,
        "end_line": end_line,
        "source_type": file_record.get("language") or file_record.get("file_type") or "text",
        "score": 1.0,
        "reason": reason,
        "snippet": "",
        "title": PurePosixPath(file_record["relative_path"]).name,
        "symbol_name": None,
    }


def analyze_python_symbols(files: list[dict], limit: int = 16) -> list[WorkflowFinding]:
    """用 Python AST 提取核心类、函数、入口点线索。"""

    findings: list[WorkflowFinding] = []
    for file_record in files:
        if file_record.get("language") != "python" or file_record.get("ignored_reason"):
            continue
        source = read_text_sample(Path(file_record["absolute_path"]))
        if not source.strip():
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            findings.append(
                WorkflowFinding(
                    title="Python 文件存在语法解析失败",
                    detail=f"{file_record['relative_path']} 无法被 AST 解析，可能使用了不完整语法或文件编码特殊。",
                    severity="medium",
                    evidence=[evidence_for_file(file_record, reason="python ast parse")],
                )
            )
            continue

        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        has_main_guard = "if __name__" in source and "__main__" in source
        if classes or functions or has_main_guard:
            symbol_bits = []
            if classes:
                symbol_bits.append("类：" + ", ".join(item.name for item in classes[:6]))
            if functions:
                symbol_bits.append("函数：" + ", ".join(item.name for item in functions[:8]))
            if imports:
                symbol_bits.append(f"顶层 import 约 {len(imports)} 处")
            if has_main_guard:
                symbol_bits.append("包含 __main__ 入口保护")
            findings.append(
                WorkflowFinding(
                    title=f"代码结构线索：{file_record['relative_path']}",
                    detail="；".join(symbol_bits),
                    severity="info",
                    evidence=[evidence_for_file(file_record, reason="python ast symbols")],
                )
            )
        if len(findings) >= limit:
            break
    return findings


def document_agent(files: list[dict], limit: int = 8) -> list[WorkflowFinding]:
    """分析 README 和文档类文件。"""

    docs = [item for item in files if classify_file(item) in {"readme", "docs"} and item.get("ignored_reason") is None]
    findings: list[WorkflowFinding] = []
    for file_record in docs[:limit]:
        text = read_text_sample(Path(file_record["absolute_path"]), max_chars=8000)
        headings = [line.strip("# ").strip() for line in text.splitlines() if line.lstrip().startswith("#")][:8]
        mentions = []
        lower_text = text.lower()
        for keyword, label in (("install", "安装"), ("usage", "使用"), ("quickstart", "快速开始"), ("api", "API"), ("test", "测试")):
            if keyword in lower_text:
                mentions.append(label)
        detail = ""
        if headings:
            detail += "主要章节：" + "、".join(headings)
        if mentions:
            detail += ("；" if detail else "") + "覆盖主题：" + "、".join(mentions)
        if not detail:
            detail = "文档文件存在，但没有提取到明显标题或常见使用说明关键词。"
        findings.append(
            WorkflowFinding(
                title=f"文档线索：{file_record['relative_path']}",
                detail=detail,
                severity="info",
                evidence=[evidence_for_file(file_record, reason="documentation scan")],
            )
        )
    return findings


def configuration_agent(files: list[dict]) -> list[WorkflowFinding]:
    """分析配置和依赖文件。"""

    findings: list[WorkflowFinding] = []
    config_files = [item for item in files if classify_file(item) == "config" and item.get("ignored_reason") is None]
    for file_record in config_files[:14]:
        name = PurePosixPath(file_record["relative_path"].lower()).name
        text = read_text_sample(Path(file_record["absolute_path"]), max_chars=10000)
        detail = "配置文件。"
        if name == "package.json":
            try:
                data = json.loads(text)
                scripts = data.get("scripts") or {}
                deps = len(data.get("dependencies") or {})
                dev_deps = len(data.get("devDependencies") or {})
                detail = f"Node 项目配置，scripts={list(scripts.keys())[:8]}，dependencies={deps}，devDependencies={dev_deps}。"
            except json.JSONDecodeError:
                detail = "package.json 解析失败，请检查 JSON 格式。"
        elif name in {"requirements.txt", "pyproject.toml", "setup.py"}:
            dependency_lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
            detail = f"Python 依赖/构建配置，提取到约 {len(dependency_lines)} 行有效配置。"
        elif name.startswith("docker"):
            detail = "容器相关配置，说明项目可能支持 Docker 构建或运行。"
        findings.append(
            WorkflowFinding(
                title=f"配置线索：{file_record['relative_path']}",
                detail=detail,
                severity="info",
                evidence=[evidence_for_file(file_record, reason="configuration scan")],
            )
        )
    return findings


def security_agent(files: list[dict], limit: int = 20) -> list[WorkflowFinding]:
    """执行规则优先的静态安全线索扫描。"""

    findings: list[WorkflowFinding] = []
    for file_record in files:
        if file_record.get("file_type") != "text" or file_record.get("ignored_reason"):
            continue
        if file_record.get("language") not in {"python", "javascript", "typescript", "yaml", "json", "toml", "text"}:
            continue
        text = read_text_sample(Path(file_record["absolute_path"]), max_chars=30000)
        lines = text.splitlines()
        for index, line in enumerate(lines, start=1):
            for title, severity, pattern, detail in SECURITY_RULES:
                if pattern.search(line):
                    findings.append(
                        WorkflowFinding(
                            title=title,
                            detail=detail,
                            severity=severity,
                            evidence=[{**evidence_for_file(file_record, index, index, "security rule"), "snippet": line.strip()[:240]}],
                        )
                    )
            for title, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        WorkflowFinding(
                            title=title,
                            detail="发现疑似敏感信息硬编码线索，请人工确认是否为示例值或真实凭据。",
                            severity="high",
                            evidence=[{**evidence_for_file(file_record, index, index, "secret pattern"), "snippet": line.strip()[:240]}],
                        )
                    )
            if len(findings) >= limit:
                return findings
    return findings


def architecture_agent(repo: dict, files: list[dict], repo_map: dict) -> list[WorkflowFinding]:
    """基于 Repo Map 和 AST 线索分析项目结构。"""

    findings = [
        WorkflowFinding(
            title="仓库结构概览",
            detail=(
                f"扫描到 {repo_map['file_count']} 个文件，{repo_map['indexable_file_count']} 个可索引文本文件；"
                f"主要语言/文本类型：{', '.join(repo_map['language_counts'].keys()) or '未知'}。"
            ),
            evidence=[evidence_for_file(item, reason="repo map") for item in files[:3]],
        )
    ]
    entrypoints = repo_map["key_files"].get("entrypoints", [])
    if entrypoints:
        findings.append(
            WorkflowFinding(
                title="可能入口文件",
                detail="优先阅读这些文件理解启动链路：" + "、".join(entrypoints[:8]),
                evidence=[evidence_for_file(item, reason="entrypoint heuristic") for item in files if item["relative_path"] in entrypoints[:4]],
            )
        )
    findings.extend(analyze_python_symbols(files))
    return findings


def build_reading_guide(sections):
    """Build CloudCode-style reading guide from per-agent findings."""
    ordered = []
    priority = {"architecture": 0, "documents": 1, "configuration": 2, "security": 3}
    for section in sorted(sections, key=lambda s: priority.get(s["key"], 99)):
        findings = section.get("findings") or []
        ordered.append({
            "key": section["key"],
            "title": section["title"],
            "summary": f"{section['title']} gathered {len(findings)} findings.",
            "reading_order": [item["title"] for item in findings[:5]],
            "needs_review": [
                {"title": item["title"], "severity": item["severity"], "detail": item["detail"]}
                for item in findings if item.get("severity") in {"medium", "high"}
            ],
        })
    return ordered


def editor_in_chief(sections, repo):
    """Aggregate per-agent findings into a CloudCode-style briefing."""
    highlights, risks, reading = [], [], []
    for section in sections:
        items = section.get("findings") or []
        if items:
            highlights.append(f"{section['title']}: {len(items)} findings")
        for item in items:
            severity = item.get("severity")
            title = item.get("title") or ""
            if severity in {"high", "medium"} and title:
                risks.append(f"[{severity}] {title}")
            if title and title not in reading:
                reading.append(title)
    joined = ", ".join(highlights) if highlights else "no notable findings"
    summary = f"Workflow summary for {repo['alias']}: {joined}."
    return {"summary": summary, "key_reading": reading[:8], "risk_items": risks[:10]}


def render_markdown_report(report: dict) -> str:
    """Render the structured workflow report as Markdown, with reading guide and risks."""
    alias = (report.get("repo") or {}).get("alias") or "repo"
    lines = [
        f"# {alias} workflow report",
        "",
        report.get("summary") or "",
        "",
        "## Repo overview",
    ]
    repo_block = report.get("repo") or {}
    if repo_block:
        lines.append(f"- ID: {repo_block.get('repo_id', '')}")
        lines.append(f"- Path: {repo_block.get('repo_path', '')}")
        lines.append(f"- Branch: {repo_block.get('branch') or 'unknown'}")
        lines.append(f"- Commit: {repo_block.get('current_commit') or 'unknown'}")
    lines.append("")
    for section in report.get("sections") or []:
        lines.extend([f"## {section.get('title')}", ""])
        findings = section.get("findings") or []
        if not findings:
            lines.extend(["No notable findings.", ""])
            continue
        for finding in findings:
            lines.append(f"- **[{finding.get('severity', 'info')}] {finding.get('title', '')}**: {finding.get('detail', '')}")
            for ev in (finding.get("evidence") or [])[:3]:
                loc = ev.get("file_path", "")
                if ev.get("start_line"):
                    loc = f"{loc}:{ev['start_line']}"
                lines.append(f"  - evidence: {loc}")
        lines.append("")
    reading_guide = report.get("reading_guide") or []
    if reading_guide:
        lines.extend(["## Reading guide (chapter summaries)", ""])
        for section in reading_guide:
            lines.append(f"- **{section.get('title')}**: {section.get('summary')}")
            for t in section.get("reading_order") or []:
                lines.append(f"  - recommended: {t}")
            needs = section.get("needs_review") or []
            if needs:
                lines.append("  - needs review:")
                for item in needs:
                    lines.append(f"    - [{item['severity']}] {item['title']}")
        lines.append("")
    risks = report.get("risk_items") or []
    if risks:
        lines.extend(["## Risks to review", ""])
        for risk in risks:
            lines.append(f"- {risk}")
        lines.append("")
    lines.extend(["## Next steps", ""])
    for step in report.get("next_steps") or []:
        lines.append(f"- {step}")
    return "\n".join(lines).strip() + "\n"


def build_workflow_report(repo: dict, files: list[dict]) -> dict:
    """Multi-agent workflow: each role reads its chapter, then editor-in-chief summarises."""
    repo_map = build_repo_map(repo, files, chunk_count=count_chunks(repo["id"]))
    build_repo_summary(repo_map)
    architecture = architecture_agent(repo, files, repo_map)
    documents = document_agent(files)
    configuration = configuration_agent(files)
    security = security_agent(files)

    sections = [
        {"key": "architecture", "title": "Code structure agent", "findings": [item.to_dict() for item in architecture]},
        {"key": "documents", "title": "Documentation understanding agent", "findings": [item.to_dict() for item in documents]},
        {"key": "configuration", "title": "Configuration & dependency agent", "findings": [item.to_dict() for item in configuration]},
        {"key": "security", "title": "Security risk agent", "findings": [item.to_dict() for item in security]},
    ]

    chief = editor_in_chief(sections, repo)
    reading_guide = build_reading_guide(sections)

    summary = chief["summary"]
    if security:
        summary += f" Security scan found {len(security)} risk lines for manual review."
    else:
        summary += " Security scan found no high-priority risk lines."

    report = {
        "analysis_id": f"analysis_{uuid4().hex}",
        "status": "succeeded",
        "repo": {
            "repo_id": repo["id"],
            "alias": repo["alias"],
            "repo_path": repo["repo_path"],
            "remote_url": repo["remote_url"],
            "branch": repo["branch"],
            "current_commit": repo["commit_hash"],
        },
        "summary": summary,
        "sections": sections,
        "reading_guide": reading_guide,
        "chief_summary": chief["summary"],
        "key_reading": chief["key_reading"],
        "risk_items": chief["risk_items"],
        "next_steps": [
            "Follow the reading guide.",
            "Manually review the high/medium risk lines flagged by the security agent.",
            "Use the Q&A surface to interrogate specific modules.",
        ],
        "limitations": [
            "Workflow is rule-first: no code execution, no dependency installation.",
            "Security findings are static snippets, not a full audit.",
            "Future work: plug in a local or OpenAI-compatible model for richer summaries.",
        ],
    }
    report["markdown"] = render_markdown_report(report)
    return report


