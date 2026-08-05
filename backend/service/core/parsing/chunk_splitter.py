"""后置证据切片：在解析完成后把超预算的 EvidenceUnit 拆成小块。

解析器只负责产出语言事实，不关心 token 预算。FallbackParser 会把整个文件
当成一条 Evidence，一个 2000 行的 Python 函数也只产生一条 Evidence。这些
超大 Evidence 在 Embedding 和检索时都会出问题：

- Embedding 模型有输入上限，超长文本会被截断或降质
- 检索时一条巨大 Evidence 会吞掉大部分 token budget
- 行号范围太粗，引用不精确

本模块在 ``ingest_service`` 的归一化之后、存储之前运行，对所有解析器产出
的超预算 Evidence 按行拆分，并保留 overlap 避免边界信息丢失。
"""
from __future__ import annotations

from service.core.evidence.budget import estimate_tokens
from service.core.parsing.models import EvidenceUnit, ParseResult, SourceDocument


# 单条 Evidence 的 token 上限，与 EvidenceBudget.max_evidence_tokens 保持一致。
DEFAULT_MAX_TOKENS = 600
# 相邻切片之间的 overlap token 数，避免跨切片的上下文被切断。
DEFAULT_OVERLAP_TOKENS = 60


def split_oversized_evidence(
    evidence: EvidenceUnit,
    document: SourceDocument,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[EvidenceUnit]:
    """把一条超预算 Evidence 拆成若干小块。

    未超预算时返回单元素列表（原对象不变）。拆分后的每条 Evidence：
    - 保留原始 kind / symbol_id / parent_id / title / metadata
    - 重新计算 start_line / end_line / content / id / logical_id
    - identity 加入切片序号，避免多条切片 logical_id 相撞
    """
    if estimate_tokens(evidence.content) <= max_tokens:
        return [evidence]

    lines = evidence.content.splitlines()
    if len(lines) <= 1:
        # 单行就超预算（比如超长正则）：无法按行拆分，保留原样。
        return [evidence]

    chunks: list[EvidenceUnit] = []
    cursor = 0
    chunk_index = 0

    while cursor < len(lines):
        # 正向累积行，直到再加一行就超预算。
        chunk_start = cursor
        chunk_lines: list[str] = []
        chunk_tokens = 0
        while cursor < len(lines):
            line = lines[cursor]
            line_tokens = estimate_tokens(line)
            if chunk_lines and chunk_tokens + line_tokens > max_tokens:
                break
            chunk_lines.append(line)
            chunk_tokens += line_tokens
            cursor += 1

        if chunk_lines:
            chunk_index += 1
            chunks.append(_make_slice(evidence, document, chunk_lines, chunk_start, chunk_index))

        # 回退若干行作为下一片的 overlap，避免跨切片上下文被切断。
        # 关键：cursor 必须越过 chunk_start，否则单行超 max_tokens 时会死循环。
        if cursor < len(lines):
            stepped = _step_back(lines, cursor, overlap_tokens)
            cursor = max(chunk_start + 1, stepped)

    return chunks if chunks else [evidence]


def _step_back(lines: list[str], cursor: int, overlap_tokens: int) -> int:
    """从 cursor 往回走，直到再退一行就会超过 overlap_tokens。"""
    target = cursor
    accumulated = 0
    while target > 0 and accumulated < overlap_tokens:
        target -= 1
        accumulated += estimate_tokens(lines[target])
        if accumulated > overlap_tokens:
            target += 1
            break
    # 至少退一行，否则会死循环；但不能退到 cursor 之前的位置。
    return max(cursor - 1, target)


def _make_slice(
    evidence: EvidenceUnit,
    document: SourceDocument,
    chunk_lines: list[str],
    chunk_start: int,
    chunk_index: int,
) -> EvidenceUnit:
    """用拆分出的行创建一条新的 EvidenceUnit。

    chunk_start 是该切片在原始 lines 列表中的起始下标（0-based），
    用于计算正确的 start_line / end_line。
    """
    content = "\n".join(chunk_lines)
    # 元数据里保留原始 identity，便于溯源。
    metadata = {**(evidence.metadata or {}), "slice_index": chunk_index}
    return EvidenceUnit.create(
        document,
        evidence.start_line + chunk_start,
        evidence.start_line + chunk_start + len(chunk_lines) - 1,
        kind=evidence.kind,
        content=content,
        symbol_id=evidence.symbol_id,
        parent_id=evidence.parent_id,
        title=evidence.title,
        metadata=metadata,
        # identity 加入切片序号，避免同一原始 Evidence 的多条切片 logical_id 相撞。
        identity=(evidence.logical_id, chunk_index),
    )


def split_oversized_in_result(
    result: ParseResult,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> ParseResult:
    """对 ParseResult 中所有 Evidence 执行超预算拆分。

    拆分后重映射 parent_id：如果被拆分的 Evidence 是其他 Evidence 的父节点，
    子节点的 parent_id 会被更新为第一个切片的 ID，避免外键悬空。
    """
    if not result.evidence:
        return result

    # 拆分会生成新的 id / logical_id，原始 ID 随之消失。所有引用它的地方
    # （evidence.parent_id、symbol.evidence_id、relation 的多个字段）都必须
    # 重指向第一个切片，否则写库时会触发外键约束失败。
    id_remap: dict[str, str] = {}
    logical_remap: dict[str, str] = {}
    new_evidence: list[EvidenceUnit] = []
    for item in result.evidence:
        slices = split_oversized_evidence(
            item, result.document, max_tokens=max_tokens, overlap_tokens=overlap_tokens,
        )
        if len(slices) > 1:
            id_remap[item.id] = slices[0].id
            logical_remap[item.logical_id] = slices[0].logical_id
        new_evidence.extend(slices)

    if not id_remap:
        return result

    from dataclasses import replace

    def remap_id(value: str | None) -> str | None:
        return id_remap.get(value, value) if value else value

    # Evidence 的父引用。
    new_evidence = [
        replace(item, parent_id=remap_id(item.parent_id))
        if item.parent_id in id_remap else item
        for item in new_evidence
    ]
    # Symbol 指向定义证据。
    result.symbols = [
        replace(item, evidence_id=remap_id(item.evidence_id))
        if item.evidence_id in id_remap else item
        for item in result.symbols
    ]
    # Relation 引用 Evidence 的地方一共五处，漏掉任何一处都会在写库时
    # 触发外键失败：
    #   1. evidence_id —— 关系的出处证据，所有解析器都填。
    #   2. source_id —— config 解析器用父 Evidence 的 id 当关系起点。
    #   3. target_id —— 结构关系可能直接指向 Evidence。
    #   4. metadata 的 source_evidence_id / target_evidence_id —— 入库时
    #      evidence_store 会读它们填 source_evidence_id / target_evidence_id 列。
    #   5. target_ref —— markdown 把 evidence.logical_id 写在这里（非外键，
    #      但不改会让未解析目标指向消失的逻辑 ID）。
    # source_id / target_id 也可能是 Symbol ID；Symbol ID 不在 id_remap 里，
    # 所以按字典命中判断是安全的。
    relation_id_fields = ("source_id", "target_id")
    metadata_id_keys = ("source_evidence_id", "target_evidence_id")
    remapped_relations = []
    for item in result.relations:
        metadata = item.metadata or {}
        changed_fields = [
            name for name in relation_id_fields if getattr(item, name) in id_remap
        ]
        changed_metadata = [key for key in metadata_id_keys if metadata.get(key) in id_remap]
        needs_ref_remap = item.target_ref in logical_remap
        if (
            item.evidence_id not in id_remap
            and not changed_fields
            and not changed_metadata
            and not needs_ref_remap
        ):
            remapped_relations.append(item)
            continue
        updates: dict[str, object] = {
            name: remap_id(getattr(item, name)) for name in changed_fields
        }
        if item.evidence_id in id_remap:
            updates["evidence_id"] = remap_id(item.evidence_id)
        if changed_metadata:
            updates["metadata"] = {
                **metadata,
                **{key: remap_id(metadata[key]) for key in changed_metadata},
            }
        if needs_ref_remap:
            updates["target_ref"] = logical_remap[item.target_ref]
        remapped_relations.append(replace(item, **updates))
    result.relations = remapped_relations

    result.evidence = new_evidence
    return result
