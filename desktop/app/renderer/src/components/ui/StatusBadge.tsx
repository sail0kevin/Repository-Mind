import type { ReactNode } from "react";

export function StatusBadge(props: {
  tone: "success" | "warning" | "danger" | "info" | "neutral";
  children: ReactNode;
  className?: string;
  live?: boolean;
}) {
  return (
    <span
      className={`rm-status-badge ${props.tone} ${props.className ?? ""}`}
      role={props.live ? "status" : undefined}
      aria-live={props.live ? "polite" : undefined}
    >
      {props.children}
    </span>
  );
}
