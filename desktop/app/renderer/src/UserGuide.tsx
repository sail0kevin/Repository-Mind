import { useState } from "react";
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  HelpCircle,
  KeyRound,
  Search,
  Settings,
  Workflow,
  X,
} from "lucide-react";

import { Dialog } from "./components/ui/Dialog";
import { IconButton } from "./components/ui/IconButton";

interface UserGuideProps {
  isOpen: boolean;
  onClose: () => void;
}

const GUIDE_STEPS = [
  {
    title: "配置模型",
    icon: Settings,
    description: "模型配置是可选项。无 Key 也能完成 Snapshot、Catalog、lexical 检索和规则回答。",
    details: [
      "Chat 与 Embedding 使用彼此独立的凭据",
      "API Key 使用 Windows DPAPI 保存",
      "只向你明确配置并信任的模型 Endpoint 发送 Evidence；远程 HTTP 地址会明文传输，请优先使用 HTTPS",
    ],
  },
  {
    title: "添加仓库",
    icon: KeyRound,
    description: "选择公开 GitHub URL、本地干净 Git 仓库，或者直接打开离线内置 Demo。",
    details: [
      "GitHub URL 会克隆到 RepoMind 本地数据目录",
      "每次成功索引都会生成不可变 Snapshot",
      "RepoMind 只读分析仓库，不执行或修改目标代码",
    ],
  },
  {
    title: "调查仓库",
    icon: Search,
    description: "从知识目录定位模块，或在智能问答中获取带文件、行号和 Trace 的回答。",
    details: [
      "系统先检索有限 Evidence，不会把整个仓库直接塞给模型",
      "局部解释通常走零工具路径",
      "安全与影响问题只调用对应的受约束 Specialist Tool",
    ],
  },
  {
    title: "导出结论",
    icon: Workflow,
    description: "工作流报告与 Main Agent Trace 可以导出，便于复核、展示和面试讲解。",
    details: [
      "导出记录 Snapshot、Commit 与证据行号",
      "本机绝对路径、数据库路径和凭据会被脱敏",
      "Legacy 多角色页面仅为兼容入口，不代表自由多 Agent 运行时",
    ],
  },
];

export function UserGuide({ isOpen, onClose }: UserGuideProps) {
  const [index, setIndex] = useState(0);
  const step = GUIDE_STEPS[index];
  const Icon = step.icon;

  return (
    <Dialog
      isOpen={isOpen}
      onClose={onClose}
      className="guide-modal"
      title={<><HelpCircle size={21} /> RepoMind 使用指南</>}
      description="四步完成从仓库接入到可追溯结论导出的闭环。"
    >
      <div className="guide-header">
        <div className="guide-icon" aria-hidden="true"><HelpCircle size={24} /></div>
        <div className="guide-header-text">
          <h2>Repository Intelligence Workbench</h2>
          <span className="guide-subtitle">Snapshot 绑定、Evidence 优先、执行轨迹可复核</span>
        </div>
        <IconButton label="关闭使用指南" onClick={onClose}><X size={18} /></IconButton>
      </div>

      <div className="guide-body">
        <nav className="guide-nav" aria-label="使用指南步骤">
          {GUIDE_STEPS.map((item, itemIndex) => (
            <button
              key={item.title}
              type="button"
              className={`guide-nav-item ${itemIndex === index ? "active" : ""} ${itemIndex < index ? "done" : ""}`}
              aria-current={itemIndex === index ? "step" : undefined}
              onClick={() => setIndex(itemIndex)}
            >
              <span className="guide-nav-num">
                {itemIndex < index ? <CheckCircle2 size={12} /> : itemIndex + 1}
              </span>
              <span className="guide-nav-title">{item.title}</span>
            </button>
          ))}
        </nav>

        <section className="guide-content" aria-live="polite">
          <div className="guide-step-title">
            <Icon size={22} />
            <h3>{step.title}</h3>
          </div>
          <p className="guide-description">{step.description}</p>
          <div className="guide-items">
            {step.details.map((detail) => (
              <div key={detail} className="guide-item"><strong>{detail}</strong></div>
            ))}
          </div>
        </section>
      </div>

      <div className="guide-footer">
        <button className="guide-btn secondary" disabled={index === 0} onClick={() => setIndex((value) => Math.max(0, value - 1))}>
          <ChevronLeft size={16} /> 上一步
        </button>
        <span className="guide-progress" role="status">{index + 1} / {GUIDE_STEPS.length}</span>
        {index === GUIDE_STEPS.length - 1 ? (
          <button className="guide-btn primary" onClick={onClose}>开始使用</button>
        ) : (
          <button className="guide-btn primary" onClick={() => setIndex((value) => Math.min(GUIDE_STEPS.length - 1, value + 1))}>
            下一步 <ChevronRight size={16} />
          </button>
        )}
      </div>
    </Dialog>
  );
}
