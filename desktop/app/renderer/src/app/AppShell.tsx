import { useEffect, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { PanelLeftOpen, PanelRightOpen, X } from "lucide-react";

import { Drawer } from "../components/ui/Drawer";
import { IconButton } from "../components/ui/IconButton";

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return matches;
}

/**
 * 三栏工作区的纯布局组件。
 * 它只管理区域摆放、窄窗口 Drawer 和左栏拖动入口，仓库注册、问答等行为仍由父组件控制。
 */
export function AppShell(props: {
  leftPanel: ReactNode;
  centerPanel: ReactNode;
  rightPanel: ReactNode;
  leftPanelWidth: number;
  onResizeStart: (event: PointerEvent<HTMLDivElement>) => void;
  onResizeReset: () => void;
  onResizeKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void;
  onOverlayOpenChange?: (isOpen: boolean) => void;
}) {
  const isTaskFirst = useMediaQuery("(max-width: 1023px)");
  const isInspectorDrawer = useMediaQuery("(max-width: 1279px)");
  const [isResourceOpen, setIsResourceOpen] = useState(false);
  const [isInspectorOpen, setIsInspectorOpen] = useState(false);

  useEffect(() => {
    // 小白说明：窗口变宽并恢复固定左栏后，关闭之前的小屏抽屉，避免出现两份相同面板。
    if (!isTaskFirst) setIsResourceOpen(false);
  }, [isTaskFirst]);

  useEffect(() => {
    // 小白说明：窗口变宽并恢复右侧 Inspector 后，同时清除抽屉和全屏遮罩。
    if (!isInspectorDrawer) setIsInspectorOpen(false);
  }, [isInspectorDrawer]);

  useEffect(() => {
    props.onOverlayOpenChange?.((isTaskFirst && isResourceOpen) || (isInspectorDrawer && isInspectorOpen));
    return () => props.onOverlayOpenChange?.(false);
  }, [isInspectorDrawer, isInspectorOpen, isResourceOpen, isTaskFirst, props.onOverlayOpenChange]);

  return (
    <>
      <main
        className="af-workspace"
        style={{ "--af-left-panel-width": `${props.leftPanelWidth}px` } as CSSProperties}
      >
        {!isTaskFirst && <aside className="af-panel af-left" aria-label="仓库资源导航">{props.leftPanel}</aside>}
        {!isTaskFirst && (
          <div
            className="af-left-resizer"
            role="separator"
            aria-label="调整左侧面板宽度"
            aria-orientation="vertical"
            aria-valuemin={240}
            aria-valuemax={480}
            aria-valuenow={props.leftPanelWidth}
            tabIndex={0}
            title="拖动调整左侧面板宽度，双击恢复默认"
            onPointerDown={props.onResizeStart}
            onDoubleClick={props.onResizeReset}
            onKeyDown={props.onResizeKeyDown}
          />
        )}
        <section className="af-panel af-center" aria-label="调查工作区">
          {(isTaskFirst || isInspectorDrawer) && (
            <div className="rm-mobile-panel-bar" aria-label="工作台面板">
              {isTaskFirst && <button className="af-btn secondary" onClick={() => setIsResourceOpen(true)}><PanelLeftOpen size={15} /> 仓库与目录</button>}
              {isInspectorDrawer && <button className="af-btn secondary" onClick={() => setIsInspectorOpen(true)}><PanelRightOpen size={15} /> Evidence 与状态</button>}
            </div>
          )}
          {props.centerPanel}
        </section>
        {!isInspectorDrawer && <aside className="af-panel af-right" aria-label="Evidence 与仓库状态">{props.rightPanel}</aside>}
      </main>

      <Drawer isOpen={isTaskFirst && isResourceOpen} onClose={() => setIsResourceOpen(false)} title="仓库与知识目录" className="rm-resource-drawer">
        <div className="rm-panel-drawer-header"><strong>仓库与知识目录</strong><IconButton label="关闭仓库导航" onClick={() => setIsResourceOpen(false)}><X size={17} /></IconButton></div>
        <div className="rm-panel-drawer-body">{props.leftPanel}</div>
      </Drawer>
      <Drawer isOpen={isInspectorDrawer && isInspectorOpen} onClose={() => setIsInspectorOpen(false)} title="Evidence 与状态" className="rm-inspector-drawer">
        <div className="rm-panel-drawer-header"><strong>Evidence 与状态</strong><IconButton label="关闭 Evidence 面板" onClick={() => setIsInspectorOpen(false)}><X size={17} /></IconButton></div>
        <div className="rm-panel-drawer-body">{props.rightPanel}</div>
      </Drawer>
    </>
  );
}
