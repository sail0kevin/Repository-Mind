---
name: 实例方法调用边解析
about: 完整解析Python实例方法的调用关系
title: '[PLANNED] 实例方法调用边解析'
labels: enhancement, parser
assignees: ''
---

## 计划状态
📋 待开发

## 需求背景
当前Parser标记入口和测试为"源码引用候选"，但未完整解析实例方法调用边。需要增强类型推断能力。

## 技术方案
- 局部变量类型传播分析
- 实例化点到调用点的数据流跟踪
- 支持简单赋值链的类型推断

## 预期收益
- 依赖影响分析更准确
- 测试定位召回率提升
- 调用图谱完整性改善

## 技术难点
- Python动态类型推断复杂度高
- 需要平衡准确率与性能开销
- 跨文件类型传播边界问题

## 相关文件
- `backend/service/core/parsing/python_parser.py`
- `backend/service/storage/symbol_store.py`
