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

interface UserGuideProps {
  isOpen: boolean;
  onClose: () => void;
}

const GUIDE_STEPS = [
  {
    title: "配置模型",
    icon: Settings,
    description: "打开右上角设置，填写 API Key、Base URL 和模型名。LongCat-2.0 可以直接使用预设。",
    details: [
      "LongCat Base URL: https://api.longcat.chat/openai/v1",
      "模型名: LongCat-2.0",
      "API Key 只保存在本机配置库中",
    ],
  },
  {
    title: "添加仓库",
    icon: KeyRound,
    description: "在左侧输入公开 GitHub URL 或本地 Git 仓库路径，然后点击注册并索引。",
    details: [
      "GitHub URL 会先克隆到本地 data/repos",
      "本地路径必须是 Git 仓库",
      "索引阶段会解析文件、生成知识片段并构建代码图谱",
    ],
  },
  {
    title: "开始问答",
    icon: Search,
    description: "索引完成后，在智能问答里提问。回答会尽量附带证据文件、行号和片段。",
    details: [
      "系统不会把整个仓库塞进模型",
      "系统会先检索相关片段，再构造有限上下文",
      "右侧证据流可辅助核对答案",
    ],
  },
  {
    title: "运行工作流",
    icon: Workflow,
    description: "工作流分析会从代码、文档、结构、风险等角度拆分项目，适合首次读懂一个仓库。",
    details: [
      "多智能体协作使用全局模型配置",
      "代码图谱可以查询重要函数和调用链",
      "费用估算只按你设置的单价做本地估算",
    ],
  },
];

export function UserGuide({ isOpen, onClose }: UserGuideProps) {
  const [index, setIndex] = useState(0);

  if (!isOpen) {
    return null;
  }

  const step = GUIDE_STEPS[index];
  const Icon = step.icon;

  return (
    <div className="guide-overlay" onClick={onClose}>
      <div className="guide-modal" onClick={(event) => event.stopPropagation()}>
        <div className="guide-header">
          <div className="guide-icon">
            <HelpCircle size={24} />
          </div>
          <div className="guide-header-text">
            <h2>RepoMind 使用指南</h2>
            <span className="guide-subtitle">按这四步完成从配置到仓库问答的闭环</span>
          </div>
          <button className="guide-close" onClick={onClose} title="关闭">
            <X size={18} />
          </button>
        </div>

        <div className="guide-body">
          <nav className="guide-nav">
            {GUIDE_STEPS.map((item, itemIndex) => (
              <button
                key={item.title}
                className={`guide-nav-item ${itemIndex === index ? "active" : ""} ${itemIndex < index ? "done" : ""}`}
                onClick={() => setIndex(itemIndex)}
              >
                <span className="guide-nav-num">
                  {itemIndex < index ? <CheckCircle2 size={12} /> : itemIndex + 1}
                </span>
                <span className="guide-nav-title">{item.title}</span>
              </button>
            ))}
          </nav>

          <section className="guide-content">
            <div className="guide-step-title">
              <Icon size={22} />
              <h3>{step.title}</h3>
            </div>
            <p className="guide-description">{step.description}</p>
            <div className="guide-items">
              {step.details.map((detail) => (
                <div key={detail} className="guide-item">
                  <strong>{detail}</strong>
                </div>
              ))}
            </div>
          </section>
        </div>

        <div className="guide-footer">
          <button
            className="guide-btn secondary"
            disabled={index === 0}
            onClick={() => setIndex((value) => Math.max(0, value - 1))}
          >
            <ChevronLeft size={16} /> 上一步
          </button>
          <span className="guide-progress">{index + 1} / {GUIDE_STEPS.length}</span>
          {index === GUIDE_STEPS.length - 1 ? (
            <button className="guide-btn primary" onClick={onClose}>
              开始使用
            </button>
          ) : (
            <button
              className="guide-btn primary"
              onClick={() => setIndex((value) => Math.min(GUIDE_STEPS.length - 1, value + 1))}
            >
              下一步 <ChevronRight size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
