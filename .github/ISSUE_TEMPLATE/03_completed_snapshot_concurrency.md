---
name: Snapshot并发安全机制
about: 不可变快照的并发索引保护
title: '[COMPLETED] Snapshot并发安全机制'
labels: enhancement, completed
assignees: ''
---

## 完成状态
✅ 已完成并验证

## 实现内容
实现基于进程内锁的Snapshot并发安全机制，避免同一repo_id的不同commit反序发布。

## 技术细节
- `_repo_lock(repo_id)` 上下文管理器
- 进程内threading.Lock串行化
- CAS保护已发布快照不被降级
- 失败快照清理按外键依赖顺序执行

## 验证结果
- 并发索引测试通过
- 快照状态机严格五态转换
- 外键完整性校验通过

## 相关文件
- `backend/service/core/ingest_service.py` (lines 45-58)
- `backend/service/storage/snapshot_store.py`
- `backend/tests/core/test_ingest_service.py`
