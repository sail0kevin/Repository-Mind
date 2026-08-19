---
name: 337个pytest全覆盖
about: 后端所有模块的测试覆盖
title: '[COMPLETED] 337个pytest全覆盖'
labels: testing, completed
assignees: ''
---

## 完成状态
✅ 已完成并验证

## 实现内容
建立完整的pytest测试套件，覆盖MCP、检索、快照隔离、桌面访问保护等核心模块。

## 测试覆盖范围
- MCP工具调用与参数验证
- `--index` CLI同步建索引
- 检索遥测与指标计算
- 快照隔离与并发安全
- 桌面访问保护机制
- 评测夹具回归门禁

## 验证结果
- `python -m pytest -q` → **337 passed**
- 所有核心功能回归保护
- CI自动运行确保质量

## 相关文件
- `backend/tests/` (所有测试文件)
- `backend/service/core/ingest_service.py`
- `.github/workflows/windows-ci.yml`
