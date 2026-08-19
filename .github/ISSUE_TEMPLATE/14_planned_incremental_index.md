---
name: 增量索引更新机制
about: 支持Git diff增量更新而非全量重建
title: '[PLANNED] 增量索引更新机制'
labels: enhancement, performance
assignees: ''
---

## 计划状态
📋 待开发

## 需求背景
当前每次commit都需要全量重建索引，对于大型仓库耗时过长。需要增量更新机制。

## 技术方案
- 基于Git diff识别变更文件
- 只重新解析变更文件的Evidence
- 更新受影响的Symbol关系
- 保留未变更文件的Embedding向量

## 预期收益
- 索引更新速度提升10-100x
- 降低Embedding API调用成本
- 支持实时索引更新

## 技术挑战
- 跨文件Symbol依赖的增量更新
- Snapshot不可变性与增量的平衡
- 索引一致性保证

## 相关文件
- `backend/service/core/ingest_service.py` (增量模式)
- `backend/service/core/repo_scanner.py` (diff检测)
