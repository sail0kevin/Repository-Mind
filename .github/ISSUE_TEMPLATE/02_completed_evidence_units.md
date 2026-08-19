---
name: Evidence Units索引抽象
about: 统一符号、文档、测试的Evidence抽象层
title: '[COMPLETED] Evidence Units索引抽象'
labels: enhancement, completed
assignees: ''
---

## 完成状态
✅ 已完成并验证

## 实现内容
建立统一的Evidence Units抽象层，将符号定义、文档片段、测试用例统一为可检索的Evidence单元。

## 技术细节
- 每个Evidence Unit包含: id, content, path, kind, symbol_id
- 支持FTS5全文检索
- 支持向量化embedding
- Snapshot级别隔离

## 验证结果
- 337个pytest全部通过
- Evidence覆盖率: 87%
- 单文件最大Evidence数: 50+

## 相关文件
- `backend/service/storage/evidence_store.py`
- `backend/service/core/ingest_service.py`
- `backend/tests/storage/test_evidence_store.py`
