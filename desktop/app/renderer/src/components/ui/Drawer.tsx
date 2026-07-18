import { useEffect, useId, useRef, type ReactNode } from "react";

import { isTopOverlay, registerOverlay } from "./overlayStack";

function getFocusable(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLElement>(
    'button:not([disabled]):not([tabindex="-1"]), [href]:not([tabindex="-1"]), input:not([disabled]):not([tabindex="-1"]), select:not([disabled]):not([tabindex="-1"]), textarea:not([disabled]):not([tabindex="-1"]), [tabindex]:not([tabindex="-1"])',
  ));
}

/** 小白说明：Drawer 是从右侧打开的模态面板，源码证据与 Trace 共用它。 */
export function Drawer(props: {
  isOpen: boolean;
  title: ReactNode;
  children: ReactNode;
  onClose: () => void;
  testId?: string;
  className?: string;
}) {
  const titleId = useId();
  const drawerIdRef = useRef(Symbol("repomind-drawer"));
  const drawerRef = useRef<HTMLDivElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(props.onClose);

  useEffect(() => {
    onCloseRef.current = props.onClose;
  }, [props.onClose]);

  useEffect(() => {
    if (!props.isOpen) return;
    const drawerId = drawerIdRef.current;
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const drawer = drawerRef.current;
    if (!drawer) return;
    const unregister = registerOverlay({
      id: drawerId,
      element: drawer,
      close: () => onCloseRef.current(),
      returnFocus: returnFocusRef.current,
    });
    getFocusable(drawer)[0]?.focus();

    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (!isTopOverlay(drawerId)) return;
      if (event.key !== "Tab") return;
      const focusable = getFocusable(drawer);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      unregister();
    };
  }, [props.isOpen]);

  if (!props.isOpen) return null;

  return (
    <div className="rm-drawer-overlay" onMouseDown={(event) => event.target === event.currentTarget && props.onClose()}>
      <aside
        ref={drawerRef}
        className={`rm-drawer ${props.className ?? ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid={props.testId}
        tabIndex={-1}
      >
        <div id={titleId} className="rm-drawer-title">{props.title}</div>
        {props.children}
      </aside>
    </div>
  );
}
