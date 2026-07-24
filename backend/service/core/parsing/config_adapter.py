"""JSON/YAML/TOML 的统一 ParserAdapter。"""
from __future__ import annotations

import json
import tomllib
from pathlib import PurePosixPath
from typing import Any

from service.core.parsing.base import ParserAdapter
from service.core.parsing.models import Diagnostic, EvidenceUnit, ParseResult, Relation, SourceDocument

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_LOCKS = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "pnpm-lock.yml",
          "poetry.lock", "pdm.lock", "composer.lock", "cargo.lock", "gemfile.lock"}


class ConfigParser(ParserAdapter):
    """解析配置键路径；格式错误时保留完整 fallback 文本。"""

    languages = frozenset({"json", "yaml", "toml"})
    extensions = frozenset({".json", ".yaml", ".yml", ".toml"})

    def parse(self, document: SourceDocument) -> ParseResult:
        name = PurePosixPath(document.path).name.lower()
        if name in _LOCKS:
            return ParseResult(document=document, status="unsupported", diagnostics=[Diagnostic(
                "low_value_config", "低价值 lock 文件未做结构化展开。", "info", document.path,
                parser="config", snapshot_id=document.snapshot_id, file_id=document.file_id)])
        try:
            suffix = PurePosixPath(document.path).suffix.lower()
            if suffix == ".json":
                value = json.loads(document.content)
                fmt = "json"
            elif suffix in {".yaml", ".yml"}:
                if yaml is None:
                    raise RuntimeError("PyYAML 未安装")
                value = yaml.safe_load(document.content)
                fmt = "yaml"
            else:
                value = tomllib.loads(document.content)
                fmt = "toml"
        except Exception as exc:
            evidence = EvidenceUnit.create(document, 1, max(1, len(document.content.splitlines())),
                kind="fallback", content=document.content, title=document.path,
                metadata={"parser": "config", "parse_error": f"{type(exc).__name__}: {exc}"})
            return ParseResult(document=document, status="fallback_text", evidence=[evidence], diagnostics=[Diagnostic(
                "config_parse_error", str(exc), "warning", document.path, parser="config",
                snapshot_id=document.snapshot_id, file_id=document.file_id)])

        result = ParseResult(document=document)
        lines = document.content.splitlines()
        positions = self._build_position_index(lines)
        cursors: dict[str, int] = {}
        previous: dict[tuple[str | int, ...], EvidenceUnit] = {}
        for path, item in self._walk(value):
            key_path = self._path(path)
            start, end = self._locate(lines, path[-1] if path else None, positions, cursors)
            content = json.dumps(self._sort_keys_as_str(item), ensure_ascii=False, indent=2, default=str)
            parent = previous.get(path[:-1]) if path else None
            evidence = EvidenceUnit.create(document, start, end,
                kind="config_object" if isinstance(item, (dict, list)) else "config_value",
                content=content, parent_id=parent.id if parent else None, title=key_path,
                metadata={"parser": "config", "format": fmt, "key_path": key_path})
            result.evidence.append(evidence)
            previous[path] = evidence
            if parent:
                result.relations.append(Relation.create(document, kind="configures", source_id=parent.id,
                    target_id=None, target_ref=evidence.logical_id, observed=True, inferred=False, confidence=1.0,
                    evidence_id=evidence.id, line=start,
                    metadata={"source_evidence_id": parent.id, "target_evidence_id": evidence.id}))
        result.sort_facts()
        return result

    @staticmethod
    def _sort_keys_as_str(value: Any) -> Any:
        """按 str(key) 排序重建 dict，替代 json.dumps 的 sort_keys=True。

        YAML 1.1 把裸 on/off/yes/no 解析成布尔值，同一个 dict 里可能混有 str 和
        bool 类型的 key，导致 sort_keys=True 直接用 `<` 比较原始 key 时抛出
        TypeError。这里统一按 str(key) 排序后重建 dict，json.dumps 序列化非 str
        key（如 bool）时仍会按其原本方式转成字符串，行为与之前一致。
        """
        if isinstance(value, dict):
            return {
                key: ConfigParser._sort_keys_as_str(child)
                for key, child in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, list):
            return [ConfigParser._sort_keys_as_str(child) for child in value]
        return value

    @staticmethod
    def _walk(value: Any, path: tuple[str | int, ...] = ()):
        yield path, value
        if isinstance(value, dict):
            for key, child in value.items():
                yield from ConfigParser._walk(child, path + (str(key),))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from ConfigParser._walk(child, path + (index,))

    @staticmethod
    def _path(path: tuple[str | int, ...]) -> str:
        output = "$"
        for part in path:
            output += f"[{part}]" if isinstance(part, int) else f".{part}"
        return output

    @staticmethod
    def _build_position_index(lines: list[str]) -> dict[str, list[int]]:
        """单次扫描建立 token 到行号的倒排索引，避免每个配置节点重复扫全文。"""
        positions: dict[str, list[int]] = {}
        for line_number, line in enumerate(lines, start=1):
            for token in set(line.replace("=", " ").replace(":", " ").replace(",", " ").split()):
                normalized = token.strip("\"'[]{} ")
                if normalized:
                    positions.setdefault(normalized, []).append(line_number)
        return positions

    @staticmethod
    def _locate(lines: list[str], key: str | int | None, positions: dict[str, list[int]],
                cursors: dict[str, int]) -> tuple[int, int]:
        if key is None or isinstance(key, int):
            return 1, max(1, len(lines))
        matches = positions.get(key, [])
        cursor = cursors.get(key, 0)
        if cursor < len(matches):
            cursors[key] = cursor + 1
            return matches[cursor], matches[cursor]
        return 1, max(1, len(lines))
