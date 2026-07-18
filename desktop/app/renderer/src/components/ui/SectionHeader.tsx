import type { ReactNode } from "react";

export function SectionHeader(props: {
  title: ReactNode;
  eyebrow?: string;
  actions?: ReactNode;
  description?: string;
}) {
  return (
    <header className="rm-section-header">
      <div>
        {props.eyebrow && <span className="rm-section-eyebrow">{props.eyebrow}</span>}
        <div className="rm-section-title">{props.title}</div>
        {props.description && <p>{props.description}</p>}
      </div>
      {props.actions && <div className="rm-section-actions">{props.actions}</div>}
    </header>
  );
}
