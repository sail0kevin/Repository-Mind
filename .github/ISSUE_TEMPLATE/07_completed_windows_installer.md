---
name: Windows打包与安装器
about: 一键安装的Windows Setup安装器
title: '[COMPLETED] Windows打包与安装器'
labels: deployment, completed
assignees: ''
---

## 完成状态
✅ 已完成并验证

## 实现内容
使用PyInstaller + Electron打包，生成Windows Setup安装器，内置demo预建索引。

## 技术细节
- PyInstaller编译backend为`repomind-backend.exe`
- Electron打包desktop为独立应用
- Inno Setup生成`RepoMindSetup-<version>.exe`
- 自动注册到Claude Code/Codex配置

## 验证结果
- 安装→自动注册→MCP可用 端到端验证通过
- 内置demo索引无需配置直接可用
- 卸载完整移除不留残留

## 相关文件
- `scripts/package_windows.ps1`
- `scripts/build_installer.iss`
- `scripts/setup_mcp.py` (自动注册脚本)
- Windows CI workflow
