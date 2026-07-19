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
