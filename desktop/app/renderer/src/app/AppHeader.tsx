import { BrainCircuit, CheckCircle2, CircleDollarSign, Command, HelpCircle, Loader2, Settings } from "lucide-react";

import { IconButton } from "../components/ui/IconButton";
import { StatusBadge } from "../components/ui/StatusBadge";

/**
 * 顶部应用栏展示产品身份、当前仓库上下文和全局入口。
 * 后端连接、设置保存等业务状态仍由 App 统一管理，避免拆分时改变启动流程。
 */
export function AppHeader(props: {
  isHealthy: boolean;
  repositoryLabel?: string | null;
  snapshotLabel?: string | null;
  onOpenCommandBar: () => void;
  onOpenGuide: () => void;
  onOpenPricing: () => void;
  onOpenSettings: () => void;
}) {
  return (
    <header className="af-header">
      <div className="af-header-left">
        <div className="af-logo" aria-hidden="true"><BrainCircuit size={21} /></div>
        <div>
          <h1>RepoMind</h1>
          <span className="af-subtitle">Repository Intelligence Workbench</span>
        </div>
        <div className="af-header-context" aria-label="当前仓库上下文">
          <span className="af-header-repo">{props.repositoryLabel || "尚未选择仓库"}</span>
          <span className="af-header-snapshot">{props.snapshotLabel || "等待 succeeded Snapshot"}</span>
        </div>
      </div>
      <div className="af-header-right">
        <StatusBadge live tone={props.isHealthy ? "success" : "warning"} className={`af-pill ${props.isHealthy ? "ok" : "warn"}`}>
          {props.isHealthy ? <CheckCircle2 size={13} /> : <Loader2 size={13} className="spin" />}
          {props.isHealthy ? "后端在线" : "正在连接"}
        </StatusBadge>
        <button className="rm-command-trigger" type="button" onClick={props.onOpenCommandBar} aria-label="打开命令面板">
          <Command size={15} /><span>命令</span><kbd>Ctrl K</kbd>
        </button>
        <IconButton label="打开使用指南" onClick={props.onOpenGuide}><HelpCircle size={17} /></IconButton>
        <IconButton label="打开费用估算设置" onClick={props.onOpenPricing}><CircleDollarSign size={17} /></IconButton>
        <IconButton label="打开系统设置" onClick={props.onOpenSettings}><Settings size={17} /></IconButton>
      </div>
    </header>
  );
}
