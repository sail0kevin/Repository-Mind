# RepoMind：RAG 与 Agentic Search 的结合定位

> 核心结论：RepoMind 不是“选 RAG 还是选 Agentic Search”，而是“以增强型 RAG 为知识底座，以轻量 Agentic 调度为大脑”。

## 一、为什么不能二选一

### 1.1 纯 Agentic Search 的局限

如果只让 Agent 直接探索 GitHub 仓库，会出现以下问题：

- **仓库太大，探索成本高**：一个中型项目可能有几百上千个文件，Agent 每次只能读取有限内容，容易遗漏关键代码。
- **缺少结构化索引，容易迷路**：没有 Catalog 和 Evidence Unit，Agent 很难快速定位入口、模块边界和依赖关系。
- **Token 成本不可控**：每问一个问题都重新探索一遍仓库，延迟和费用都很高。
- **结论难以溯源**：用户无法确认“这个结论到底来自哪一页代码”，在代码分析场景里不可接受。
- **容易产生幻觉**：没有真实代码证据时，模型会“看起来合理”地编造接口名、参数和业务逻辑。

因此，**纯 Agentic Search 不适合作为 RepoMind 的主架构**。

### 1.2 纯 RAG 的局限

传统 RAG 虽然能检索证据，但代码库有一类问题它处理不好：

- **多跳依赖追踪**：例如“这个配置文件改了之后，最终会影响哪些接口？”这种问题不能靠一次性召回几个片段，而需要多轮、多跳查询。
- **复杂任务推理**：例如“帮我梳理这个项目的启动流程。”这不是一个片段能回答的，需要 Agent 自己组织一条链路。
- **工具调用需求**：有些问题不只是“检索文档”，而是需要查符号定义、遍历依赖图、查测试关联、查配置引用。
- **模糊或宽泛问题**：例如“这个项目是怎么跑起来的？”RAG 容易返回一堆相关片段，但缺组织。

因此，**纯 RAG 也不足以支撑一个完整的代码库智能助手**。

### 1.3 正确的方向：RAG + Agentic 分层协作

RepoMind 的解决思路是让两者分层协作：

- **RAG 负责把仓库变成高质量、结构化、可追溯的知识源**；
- **Agent 负责理解问题、判断证据是否充足，并在复杂问题中调用专业工具继续探索**。

用一句话总结：

> **RAG 是项目的“知识硬盘”，Agent 是项目的“操作系统”。**

---

## 二、RAG 在 RepoMind 中负责什么

RAG 负责“把 GitHub 仓库变成可检索知识”，具体包括：

| 职责 | 对应模块 | 说明 |
|---|---|---|
| 仓库快照 | Repository Snapshot | 由 commit SHA 唯一确定的不可变仓库状态 |
| 结构解析 | ParserAdapter | 提取函数、类、接口、配置、文档章节、测试、依赖 |
| 知识切片 | Chunker | 符号/章节/配置感知切片，保留父子关系和源码位置 |
| 分层目录 | Repository Catalog | 符号→文件→目录/子系统→仓库的多层压缩目录 |
| 混合检索 | Retriever | BM25/FTS + Embedding + 结构扩展，融合重排 |
| 证据打包 | Evidence Bundle | 在 Token 预算内组装去重、重排后的证据集合 |
| 持久化 | SQLite | 保存 Evidence Units、Catalog、检索记录、回答引用 |

一句话：**RAG 负责把代码仓库变成高质量、结构化、可追溯的知识源。**

---

## 三、Agentic 在 RepoMind 中负责什么

Agentic 负责“理解问题并决定怎么使用知识”，具体包括：

| 职责 | 对应模块 | 说明 |
|---|---|---|
| 查询理解 | Main Agent | 判断问题是概览、定位、解释还是复杂分析 |
| 检索规划 | Retrieval Plan | 决定搜 Symbol、File、Subsystem 还是 Chunk |
| 直接回答 | Main Agent | 证据充分时直接基于 Evidence Bundle 回答 |
| 条件路由 | Router | 判断是否需要调用专业工具 |
| 工具调用 | Specialist Tools | 依赖分析、测试关联、安全审查、语言解析 |
| 证据综合 | Main Agent | 汇总子 Agent 的结构化发现，生成最终回答 |
| 溯源输出 | Main Agent | 将结论绑定到 commit、文件路径和代码行号 |

一句话：**Agent 负责在合适的时机用合适的方式消费 RAG 产出的知识。**

---

## 四、RAG 与 Agentic 的结合点

### 4.1 RAG 为 Agent 提供稳定起点

Agent 不会在空白仓库里盲目探索，而是直接得到：

- 分层 Catalog；
- 高质量的 Evidence Bundle；
- 可靠的 Evidence Units。

### 4.2 Agent 在证据不足或任务复杂时继续探索

- 直接解释一个函数 → RAG 检索 → 直接回答；
- 问“改这个配置会影响哪些接口” → RAG 初步证据不够 → Agent 调用依赖分析工具继续查。

### 4.3 Agent 的发现写回 RAG 体系

子 Agent 发现的依赖、测试、安全线索可以回写为新的 Evidence Unit，让知识库越用越好。

---

## 五、一个完整的真实例子

**用户问：**

> “如果把 `UserService` 里的认证逻辑改成异步，哪些 API 测试会受影响？”

**项目处理流程：**

```text
RAG 阶段
  ├─ 混合检索找到 UserService 证据
  └─ 生成 Evidence Bundle

Agent 规划
  └─ 判断这是“变更影响分析”问题，触发 Impact Analyst

子 Agent 多步探索
  ├─ 查 UserService.authenticate 的调用点
  ├─ 找到 /login, /profile 等 API 路由
  └─ 关联到 tests/test_api.py 中对应测试

回答阶段
  └─ Main Agent 综合成带 commit / path / line 引用的回答
```

这就是典型的 RAG + Agentic 混合链路，缺一不可。

---

## 六、当前项目在这个结合中的位置

### 6.1 已完成的 RAG 知识底座

- 仓库内容绑定不可变 commit Snapshot；
- ParserAdapter 对 Python、JS/TS、Markdown 和配置文件进行结构切片，并保留文本 fallback；
- SQLite FTS5/BM25 提供词法召回，可选独立 Embedding 提供语义召回；
- RRF、结构扩展和 Token 预算共同组装 Evidence Bundle；
- Catalog、Evidence 和引用均可追溯到 Snapshot、路径和行号。

### 6.2 已完成的轻量 Agentic 调度

- 普通问答由 Main Agent 统一处理；
- Router 根据问题类型和证据充分度条件调用 Specialist Tools；
- 单次请求最多调用两个工具，避免无限循环和无预算探索；
- 无 Key 时仍可运行本地检索、确定性工具和规则回答；
- 路由、检索、工具和综合过程持久化为可查询 Agent Trace；
- 旧多角色协作仅作为高级/Legacy 兼容入口。

### 6.3 后续重点是质量深化，而不是重新搭建主链路

- **RAG 深化**：扩充检索评测集、优化大型仓库增量索引、增强跨语言结构关系；
- **Agent 深化**：改进证据充分度评估、工具选择评测、超时与部分回答质量；
- **发布深化**：完成远端 Windows Actions、正式图标和代码签名。

---

## 七、面试标准口径

### 7.1 一句话回答

> RepoMind 的核心是“增强型 RAG + 轻量 Agentic 调度”。RAG 负责把代码仓库变成结构化、可追溯的知识源；Agent 负责理解问题、判断证据是否充足，并在复杂问题中调用专业工具继续探索。两者不是替代关系，而是分层协作。

### 7.2 被问到“为什么不只做 RAG”时

> 代码库有很多多跳依赖、变更影响、启动链路类问题，纯 RAG 一次检索无法回答。因此在 RAG 之上需要一个 Agent 层，负责在证据不足时继续探索、调用工具、组织多源证据。

### 7.3 被问到“为什么不只做 Agent”时

> 仓库太大，纯 Agent 每次探索成本高、容易遗漏、结论难溯源。RAG 提供了结构化知识底座和分层目录，让 Agent 的探索有起点、有导航、有证据。

### 7.4 被问到“两者怎么结合”时

> RAG 负责把仓库切片、建索引、生成 Catalog、打包 Evidence Bundle；Agent 负责理解问题，普通问题直接基于证据回答，复杂问题调用依赖、测试、安全等专业工具继续探索，最终综合成带引用的回答。

---

## 八、与路线图的关系

本文件是 `ARCHITECTURE_FUTURE_ROADMAP.md` 的补充说明，用于统一面试和文档口径。具体实现细节、里程碑和验收标准以路线图为准。
