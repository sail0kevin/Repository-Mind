# Repository-Mind / RepoMind

RepoMind 是一个本地桌面版 GitHub / Git 仓库知识助手。

## 功能

- 配置 OpenAI 兼容模型。
- 添加公开 GitHub URL 或本地 Git 仓库路径。
- 扫描、解析、索引仓库内容。
- 基于证据向代码库提问。
- 使用工作流视角理解项目结构。
- 使用代码图谱查询函数、类和调用链。

## 项目结构

- `backend/`：FastAPI 后端
- `desktop/`：Electron + React 桌面端
- `scripts/`：构建与发布脚本
- `docs/`：开发报告与说明文档

## 平台

当前主要面向 Windows 桌面端构建与验证。

## 说明

本项目默认只读分析目标仓库，不执行被分析代码，也不修改目标仓库。
