---
name: 大型真实仓库benchmark
about: 扩展到Spring Boot/Django等大型开源项目
title: '[PLANNED] 大型真实仓库benchmark'
labels: testing, benchmark
assignees: ''
---

## 计划状态
📋 待开发

## 需求背景
当前40条测试集基于RepoMind自身后端（196文件），需要在更大规模真实仓库上验证检索质量。

## 测试目标仓库
- Spring Boot (Java, 10K+ files)
- Django (Python, 5K+ files)
- React (JavaScript, 3K+ files)
- 或其他典型开源项目

## 评测维度
- Recall@5 / MRR在大规模下的表现
- 索引构建时间（P50/P95）
- 查询延迟分布
- 内存占用峰值

## 技术挑战
- 人工标注成本高
- 需要领域专家验证答案质量
- 不同语言解析器成熟度差异

## 相关文件
- `examples/benchmarks/` (新增大型仓库配置)
- `backend/service/evaluation/` (评测框架扩展)
