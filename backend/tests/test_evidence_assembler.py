"""EvidenceAssembler 的路径、去重、优先级和预算回归测试。"""

from service.core.evidence import EvidenceAssembler, EvidenceBudget


def _candidate(path: str, chunk_id: str, content: str, **extra) -> dict:
    """创建最小证据候选，方便测试只关注装配规则。"""
    return {
        "file_path": path,
        "chunk_id": chunk_id,
        "content": content,
        "start_line": 1,
        "end_line": 2,
        **extra,
    }


def test_assembler_filters_blank_paths_and_normalizes_separators() -> None:
    bundle = EvidenceAssembler().assemble(
        [
            _candidate("   ", "blank", "ignored"),
            _candidate("src\\service.py", "same", "first"),
            _candidate("src/service.py", "same", "second"),
        ],
        commit="a" * 40,
        limit=5,
    )

    assert [item.path for item in bundle.items] == ["src/service.py"]


def test_assembler_prefers_content_bearing_duplicate() -> None:
    bundle = EvidenceAssembler().assemble(
        [
            _candidate("src/service.py", "ev-1", ""),
            _candidate("src/service.py", "ev-1", "real source"),
        ],
        commit="a" * 40,
        limit=5,
    )

    assert len(bundle.items) == 1
    assert bundle.items[0].content == "real source"


def test_specialist_priority_stays_inside_item_and_token_budgets() -> None:
    assembler = EvidenceAssembler(EvidenceBudget(
        total_tokens=10,
        max_file_ratio=1.0,
        max_evidence_tokens=6,
        min_sources=1,
        max_items=2,
    ))
    bundle = assembler.assemble(
        [
            _candidate("README.md", "retrieval", "ordinary retrieval", score=50),
            _candidate("src/service.py", "tool", "specialist evidence", score=1,
                       specialist_priority=3),
            _candidate("tests/test_service.py", "tool-test", "test evidence", score=1,
                       specialist_priority=2),
        ],
        commit="a" * 40,
        limit=2,
    )

    assert len(bundle.items) <= 2
    assert bundle.total_tokens <= 10
    assert bundle.items[0].path == "src/service.py"


def test_parent_and_child_evidence_both_survive_assembly() -> None:
    """父子 Evidence 同时命中时都保留。

    曾尝试过"子联合覆盖父 ≥80% 就移除父"的去重策略，但 holdout 实测显示
    get_code_context 的 required_affected_path_coverage 从 0.636 掉到 0.273：
    行范围覆盖不等于信息覆盖，class header / 装饰器 / 导入等关键上下文恰好
    落在未被 method 覆盖的那部分行里。该策略已移除，这个测试锁定当前行为。
    """
    bundle = EvidenceAssembler(EvidenceBudget(max_items=10, min_sources=1)).assemble(
        [
            _candidate("src/service.py", "class-ev", "class body", start_line=1, end_line=100, score=80),
            _candidate("src/service.py", "method-1", "method 1", start_line=10, end_line=50, score=75),
            _candidate("src/service.py", "method-2", "method 2", start_line=50, end_line=95, score=78),
        ],
        commit="a" * 40,
        limit=10,
    )
    chunk_ids = {item.chunk_id for item in bundle.items}
    assert {"class-ev", "method-1", "method-2"}.issubset(chunk_ids)
