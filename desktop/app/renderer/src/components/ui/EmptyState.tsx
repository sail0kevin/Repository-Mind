import type { ReactNode } from "react";

export function EmptyState(props: { icon?: ReactNode; title: string; description?: string; action?: ReactNode; compact?: boolean }) {
  return (
    <div className={`rm-empty-state ${props.compact ? "compact" : ""}`}>
      {props.icon && <div className="rm-empty-icon">{props.icon}</div>}
      <strong>{props.title}</strong>
      {props.description && <p>{props.description}</p>}
      {props.action}
    </div>
  );
}
