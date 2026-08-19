---
name: 多语言Parser扩展
about: 支持Java/TypeScript/Go等更多语言
title: '[PLANNED] 多语言Parser扩展'
labels: enhancement, parser
assignees: ''
---

## 计划状态
📋 待开发

## 需求背景
当前主要支持Python解析，需要扩展到Java/TypeScript/Go等主流语言以支持更多仓库。

## 支持语言优先级
1. **TypeScript/JavaScript** - 前端项目必需
2. **Java** - Spring Boot等企业级项目
3. **Go** - 云原生基础设施项目
4. **Rust** - 系统级项目

## 技术方案
- 使用tree-sitter统一解析
- 每种语言独立Parser实现
- 统一Symbol/Relation抽象
- 支持语言特定的Evidence切分

## 挑战
- 不同语言的作用域规则差异大
- 泛型/trait等高级特性解析复杂
- 测试覆盖成本高

## 相关文件
- `backend/service/core/parsing/` (新增语言Parser)
- `backend/service/core/parsing/registry.py` (注册机制)
