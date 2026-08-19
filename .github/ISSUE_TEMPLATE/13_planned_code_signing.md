---
name: GitHub代码签名证书
about: 为Windows安装器添加代码签名
title: '[PLANNED] GitHub代码签名证书'
labels: deployment, security
assignees: ''
---

## 计划状态
📋 待开发

## 需求背景
当前Windows Setup未签名，用户安装时会看到"未知发布者"警告，影响信任度。

## 技术方案
- 购买或申请代码签名证书
- 集成到CI/CD流程
- 使用signtool.exe签名`RepoMindSetup-<version>.exe`
- GitHub Releases自动发布签名版本

## 成本评估
- EV代码签名证书: ~$300-500/年
- 或使用开源项目免费证书（需审核）

## 预期收益
- 提升用户安装信任度
- 消除SmartScreen警告
- 符合企业安全规范

## 技术挑战
- 证书购买与验证流程
- CI环境密钥安全管理
- 证书续期自动化

## 相关文件
- `scripts/sign_installer.ps1` (待创建)
- `.github/workflows/release.yml` (签名步骤)
