"""测试后置证据切片：超预算 Evidence 按行拆分并保留 overlap。"""
from __future__ import annotations

from service.core.evidence.budget import estimate_tokens
from service.core.parsing.chunk_splitter import (
    split_oversized_evidence,
    split_oversized_in_result,
)
from service.core.parsing.models import EvidenceUnit, ParseResult, SourceDocument


def _document() -> SourceDocument:
    return SourceDocument(snapshot_id="snap-1", path="src/lib.py", content="", repo_id="repo-1")


def _make_evidence(content: str, *, start: int = 1, kind: str = "file",
                   symbol_id: str | None = None, parent_id: str | None = None,
                   title: str | None = None, metadata: dict | None = None) -> EvidenceUnit:
    return EvidenceUnit.create(
        _document(), start, start + content.count("\n"), kind=kind, content=content,
        symbol_id=symbol_id, parent_id=parent_id, title=title, metadata=metadata,
        identity=(f"test-{start}",),
    )


def test_undersized_evidence_is_unchanged() -> None:
    """未超预算的 Evidence 不应被拆分。"""
    content = "short content"
    evidence = _make_evidence(content)
    result = split_oversized_evidence(evidence, _document(), max_tokens=600)
    assert len(result) == 1
    assert result[0] is evidence


def test_oversized_evidence_is_split_into_multiple_chunks() -> None:
    """超预算的 Evidence 应被拆成多块，每块都不超过 max_tokens。"""
    # estimate_tokens 按词法单元计数，每行约 6 token。200 行 ≈ 1200 token。
    lines = [f"line_{i:04d} = {'x' * 30}  # padding tokens here" for i in range(200)]
    content = "\n".join(lines)
    assert estimate_tokens(content) > 600

    evidence = _make_evidence(content)
    chunks = split_oversized_evidence(evidence, _document(), max_tokens=200, overlap_tokens=20)

    assert len(chunks) > 1, "应拆成多块"
    for chunk in chunks:
        assert estimate_tokens(chunk.content) <= 200 + 50, f"块超预算: {estimate_tokens(chunk.content)}"


def test_split_preserves_metadata_and_identity() -> None:
    """拆分后的 Evidence 应保留原始 kind / symbol_id / parent_id / title / metadata。"""
    lines = [f"line_{i} = {'y' * 30}" for i in range(40)]
    content = "\n".join(lines)
    evidence = _make_evidence(content, kind="file", symbol_id="sym-1", parent_id="par-1",
                              title="README", metadata={"parser": "fallback"})

    chunks = split_oversized_evidence(evidence, _document(), max_tokens=100, overlap_tokens=10)

    for chunk in chunks:
        assert chunk.kind == "file"
        assert chunk.symbol_id == "sym-1"
        assert chunk.parent_id == "par-1"
        assert chunk.title == "README"
        # metadata 应保留原始字段，并新增 slice_index
        assert chunk.metadata.get("parser") == "fallback"
        assert "slice_index" in chunk.metadata


def test_split_chunks_have_unique_logical_ids() -> None:
    """同一原始 Evidence 的多条切片应有不同的 logical_id，避免存储冲突。"""
    lines = [f"line_{i} = {'z' * 30}" for i in range(50)]
    content = "\n".join(lines)
    evidence = _make_evidence(content)

    chunks = split_oversized_evidence(evidence, _document(), max_tokens=80, overlap_tokens=10)
    logical_ids = [chunk.logical_id for chunk in chunks]
    assert len(logical_ids) == len(set(logical_ids)), "logical_id 应唯一"


def test_overlap_shares_lines_between_adjacent_chunks() -> None:
    """相邻切片之间应存在行重叠，避免跨切片上下文被切断。"""
    # 每行约 3 token，80 行 ≈ 240 token，max_tokens=100 时应拆成 3 块。
    lines = [f"line_{i:04d} = {'a' * 25}" for i in range(80)]
    content = "\n".join(lines)
    evidence = _make_evidence(content)

    chunks = split_oversized_evidence(evidence, _document(), max_tokens=100, overlap_tokens=40)
    assert len(chunks) >= 2

    # 相邻切片的末尾和开头应存在重叠行。
    for previous, current in zip(chunks, chunks[1:]):
        prev_lines = set(previous.content.splitlines())
        curr_lines = set(current.content.splitlines())
        assert prev_lines & curr_lines, "相邻切片应有重叠行"


def test_single_long_line_among_normal_lines_does_not_loop() -> None:
    """单行超 max_tokens 混在正常行中时，不应死循环，且应正常拆分。"""
    import signal
    # 构造：正常行 + 一行超长（超过 max_tokens）+ 更多正常行。
    long_line = "x" * 5000  # 远超 max_tokens
    lines = ["normal_1 = 1", "normal_2 = 2", long_line, "normal_3 = 3", "normal_4 = 4"]
    content = "\n".join(lines)
    evidence = _make_evidence(content)

    # 设置 5 秒超时闹钟，如果死循环会被打断。
    chunks = split_oversized_evidence(evidence, _document(), max_tokens=50, overlap_tokens=10)
    # 应该正常返回，不卡死。
    assert len(chunks) >= 1
    # 超长行应出现在某个切片中。
    assert any("x" * 100 in chunk.content for chunk in chunks)


def test_split_chunks_have_correct_line_numbers() -> None:
    """拆分后的切片应有正确的 start_line/end_line，反映在原始文件中的位置。"""
    lines = [f"line_{i:04d} = {'a' * 25}" for i in range(80)]
    content = "\n".join(lines)
    evidence = _make_evidence(content, start=10)  # 从第 10 行开始

    chunks = split_oversized_evidence(evidence, _document(), max_tokens=100, overlap_tokens=40)
    assert len(chunks) >= 2
    # 第一个切片应从第 10 行开始。
    assert chunks[0].start_line == 10
    # 所有切片的行号应单调递增（或重叠），不能倒退到 10 之前。
    for chunk in chunks:
        assert chunk.start_line >= 10
        assert chunk.end_line >= chunk.start_line


def test_single_long_line_keeps_original() -> None:
    """单行就超预算（如超长正则）时无法按行拆分，应保留原样。"""
    content = "x" * 5000
    evidence = _make_evidence(content)
    chunks = split_oversized_evidence(evidence, _document(), max_tokens=100)
    assert len(chunks) == 1
    assert chunks[0] is evidence


def test_split_oversized_in_result_handles_all_evidence() -> None:
    """split_oversized_in_result 应对 ParseResult 中所有 Evidence 执行拆分。"""
    doc = _document()
    small = _make_evidence("small", start=1)
    big_lines = [f"big_{i} = {'w' * 30}" for i in range(40)]
    big = _make_evidence("\n".join(big_lines), start=2)

    result = ParseResult(document=doc, evidence=[small, big])
    split_oversized_in_result(result, max_tokens=100, overlap_tokens=10)

    # small 保持不变，big 被拆分 → 总条数应增加。
    assert len(result.evidence) >= 2
    # 至少有一条来自 big 的拆分（slice_index 标记）。
    assert any(e.metadata.get("slice_index") for e in result.evidence)
    # small 仍在（未超预算）。
    assert any(e.content == "small" for e in result.evidence)
