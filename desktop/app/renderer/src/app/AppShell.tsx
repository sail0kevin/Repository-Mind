import type { CSSProperties, KeyboardEvent, PointerEvent, ReactNode } from "react";

/**
 * 三栏工作区的纯布局组件。
 * 它只管理左右区域的摆放和左栏拖动入口，仓库注册、问答等行为仍由父组件控制。
 */
export function AppShell(props: {
  leftPanel: ReactNode;
  centerPanel: ReactNode;
  rightPanel: ReactNode;
  leftPanelWidth: number;
  onResizeStart: (event: PointerEvent<HTMLDivElement>) => void;
  onResizeReset: () => void;
  onResizeKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void;
}) {
  return (
    <main
      className="af-workspace"
      style={{ "--af-left-panel-width": `${props.leftPanelWidth}px` } as CSSProperties}
    >
      <aside className="af-panel af-left">{props.leftPanel}</aside>
      <div
        className="af-left-resizer"
        role="separator"
        aria-label="调整左侧面板宽度"
        aria-orientation="vertical"
        aria-valuemin={240}
        aria-valuemax={520}
        aria-valuenow={props.leftPanelWidth}
        tabIndex={0}
        title="拖动调整左侧面板宽度，双击恢复默认"
        onPointerDown={props.onResizeStart}
        onDoubleClick={props.onResizeReset}
        onKeyDown={props.onResizeKeyDown}
      />
      <section className="af-panel af-center">{props.centerPanel}</section>
      <aside className="af-panel af-right">{props.rightPanel}</aside>
    </main>
  );
}
