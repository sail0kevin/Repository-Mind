---
name: 受控延迟数据采集
about: P50/P95查询延迟的生产监控
title: '[PLANNED] 受控延迟数据采集'
labels: performance, monitoring
assignees: ''
---

## 计划状态
📋 待开发

## 需求背景
当前只有实测耗时打印，缺少受控的P50/P95延迟数据，无法量化性能边界。

## 监控指标
- **索引构建延迟**: 按文件数/chunk数分层统计
- **查询延迟**: locate_code、get_symbol_definition等工具
- **Embedding延迟**: 批量向量化的P95
- **数据库查询**: SQLite FTS5/向量检索耗时

## 技术方案
- 使用Python `time.perf_counter()` 精确计时
- 按百分位数聚合（P50/P90/P95/P99）
- 集成到`service/evaluation/`模块
- 支持导出JSON/CSV格式

## 预期收益
- 性能回归检测
- 瓶颈定位更精确
- 面试时能给出具体延迟数据

## 相关文件
- `backend/service/evaluation/performance_monitor.py` (待创建)
- `backend/service/core/ingest_service.py` (埋点)
