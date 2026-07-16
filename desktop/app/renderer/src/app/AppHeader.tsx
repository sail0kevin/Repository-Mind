import { BrainCircuit, CheckCircle2, CircleDollarSign, HelpCircle, Loader2, Settings } from "lucide-react";

/**
 * 顶部应用栏只负责展示产品身份和打开全局弹窗。
 * 后端连接、设置保存等业务状态仍由 App 统一管理，避免拆分时改变启动流程。
 */
export function AppHeader(props: {
  isHealthy: boolean;
  onOpenGuide: () => void;
  onOpenPricing: () => void;
  onOpenSettings: () => void;
}) {
  return (
    <header className="af-header">
      <div className="af-header-left">
        <div className="af-logo"><BrainCircuit size={22} /></div>
        <div>
          <h1>RepoMind</h1>
          <span className="af-subtitle">Repository Knowledge Assistant</span>
        </div>
      </div>
      <div className="af-header-right">
        <span className={`af-pill ${props.isHealthy ? "ok" : "warn"}`}>
          {props.isHealthy ? <CheckCircle2 size={14} /> : <Loader2 size={14} className="spin" />}
          {props.isHealthy ? "系统在线" : "连接中"}
        </span>
        <button className="af-icon-btn" onClick={props.onOpenGuide} title="使用指南"><HelpCircle size={18} /></button>
        <button className="af-icon-btn" onClick={props.onOpenPricing} title="费用设置"><CircleDollarSign size={18} /></button>
        <button className="af-icon-btn" onClick={props.onOpenSettings} title="系统设置"><Settings size={18} /></button>
      </div>
    </header>
  );
}
