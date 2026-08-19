# GitHub配置操作指南

## 一、设置Repository描述和Topics

### 1. Repository描述（手动操作）
登录GitHub → 进入仓库主页 → 点击右上角⚙️ Settings → About部分填写：

```
面向Coding Agent的本地只读代码上下文服务 | 混合检索+Evidence Units | Recall@5 +64.8% | Token -50.22%
```

### 2. 添加Topics标签（手动操作）
在同一About部分，点击"Add topics"，添加以下关键词：

```
code-search
retrieval-augmented-generation
mcp-server
claude-code
hybrid-retrieval
evidence-based
python
sqlite
embeddings
bm25
semantic-search
developer-tools
coding-agent
repository-analysis
code-intelligence
```

**为什么要添加这些：**
- 增强GitHub搜索可见性
- 吸引相关技术栈的开发者
- 面试官搜索关键词时更容易找到

---

## 二、创建Release（需要先push tag）

### 1. Push tag到远程
```bash
git push origin v1.0.0
```

### 2. 在GitHub创建Release（手动操作）
访问：https://github.com/sail0kevin/Repository-Mind/releases/new

选择tag: `v1.0.0`

Release标题：`v1.0.0 - 混合检索优化版本`

Release描述（复制粘贴）：
```markdown
## 🎯 核心功能

- **Evidence Units索引抽象** - 统一符号、文档、测试的Evidence抽象层
- **BM25 + BGE-M3混合检索** - 词法+语义双路检索
- **RRF融合算法** - k=60优化排序质量
- **Snapshot并发安全** - 进程内锁保护不可变快照
- **向量化覆盖率优化** - 87%的Evidence已向量化

## 📊 性能指标

| 指标 | 基线 | 优化后 | 提升幅度 |
|------|------|--------|----------|
| Recall@5 | 0.267 | 0.440 | **+64.8%** |
| MRR | 0.375 | 0.558 | **+48.8%** |
| Citation覆盖率 | 0.625 | 0.850 | +36.0% |
| Token使用量 | 2,733,497 | 1,360,698 | **-50.22%** |

## 🧪 测试环境

- Python 3.11+
- Node.js 20+
- SQLite 3.35+
- 8GB RAM推荐

## ✅ 验证结果

- ✅ 337个pytest全部通过
- ✅ 64个desktop vitest全部通过
- ✅ MCP Server冻结验证通过
- ✅ Windows打包端到端验证通过

## 📦 安装

**方式1：Windows安装器（推荐）**
下载 `RepoMindSetup-1.0.0.exe`（待发布到Assets）

**方式2：源码安装**
```bash
git clone https://github.com/sail0kevin/Repository-Mind.git
cd Repository-Mind
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
cd desktop/app
npm ci
npm run dev
```

## 🔗 相关文档

- [MCP Server使用指南](docs/2026-08-01_MCP_SERVER_GUIDE_MCP服务使用指南.md)
- [产品上线审计](docs/2026-08-01_PRODUCT_READINESS_AUDIT_产品上线与交付审计.md)
- [评测报告](examples/benchmarks/2026-07-25_BACKEND_UNDERSTANDING_REPORT_V2_后端理解评测报告V2.md)
```

---

## 三、创建Issues（手动操作）

访问：https://github.com/sail0kevin/Repository-Mind/issues/new/choose

GitHub会自动识别`.github/ISSUE_TEMPLATE/`目录下的模板，你只需要：

### 已完成的Issues（创建8个，立即关闭）
1. 点击"混合检索架构实现" → Create issue → 立即Close issue并添加评论"✅ 已验证通过"
2. 点击"Evidence Units索引抽象" → Create issue → 立即Close
3. 点击"Snapshot并发安全机制" → Create issue → 立即Close
4. 点击"RRF融合算法优化" → Create issue → 立即Close
5. 点击"40条标注测试集构建" → Create issue → 立即Close
6. 点击"MCP Server只读工具集" → Create issue → 立即Close
7. 点击"Windows打包与安装器" → Create issue → 立即Close
8. 点击"337个pytest全覆盖" → Create issue → 立即Close

### 计划中的Issues（创建5个，保持Open）
9. 点击"实例方法调用边解析" → Create issue → 保持Open
10. 点击"大型真实仓库benchmark" → Create issue → 保持Open
11. 点击"受控延迟数据采集" → Create issue → 保持Open
12. 点击"多语言Parser扩展" → Create issue → 保持Open
13. 点击"增量索引更新机制" → Create issue → 保持Open

**为什么这样做：**
- 8个已关闭 = 展示已完成的工作量
- 5个开放 = 展示持续迭代的规划能力
- 使用模板 = 展示工程化的项目管理

---

## 四、验证效果

完成后，仓库主页应该显示：
- ✅ **11个徽章** - 展示技术栈和性能指标
- ✅ **15个Topics** - 关键词覆盖全面
- ✅ **1个Release** - v1.0.0已发布
- ✅ **13个Issues** (8 closed, 5 open) - 活跃的项目状态
- ✅ **CI徽章** - GitHub Actions自动运行

---

## 五、本地完成的自动化部分

✅ 已自动完成：
- README.md徽章添加
- Git tag v1.0.0创建
- 13个Issue模板生成
- GitHub Actions CI workflow配置

⏳ 需要你手动完成：
1. Push tag: `git push origin v1.0.0`
2. GitHub网页操作：设置描述、Topics、创建Release、创建Issues
