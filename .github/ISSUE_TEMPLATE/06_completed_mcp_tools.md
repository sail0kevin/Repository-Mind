---
name: MCP Server只读工具集
about: 7个只读工具的MCP Server实现
title: '[COMPLETED] MCP Server只读工具集'
labels: feature, completed
assignees: ''
---

## 完成状态
✅ 已完成并验证

## 实现内容
实现7个只读MCP工具，向Claude Code/Codex等外部Agent提供代码上下文检索能力。

## 工具列表
1. `list_repositories` - 列出已索引仓库
2. `locate_code` - 自然语言代码定位
3. `get_symbol_definition` - 获取符号定义
4. `find_references` - 查找引用位置
5. `get_dependency_impact` - 依赖影响分析
6. `security_review` - 安全审查
7. `get_test_candidates` - 测试候选定位

## 验证结果
- Claude Code集成测试通过
- Token消耗: -50.22%（外部A/B验证）
- 通过率: 60/60 cohort-task全通过

## 相关文件
- `backend/service/mcp_server.py`
- `docs/2026-08-01_MCP_SERVER_GUIDE_MCP服务使用指南.md`
- Windows Setup自动注册脚本
