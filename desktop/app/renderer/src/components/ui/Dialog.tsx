import { useEffect, useId, useRef, type MouseEvent, type ReactNode } from "react";

import { isTopOverlay, registerOverlay } from "./overlayStack";

function focusableElements(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLElement>(
    'button:not([disabled]):not([tabindex="-1"]), [href]:not([tabindex="-1"]), input:not([disabled]):not([tabindex="-1"]), select:not([disabled]):not([tabindex="-1"]), textarea:not([disabled]):not([tabindex="-1"]), [tabindex]:not([tabindex="-1"])',
  )).filter((element) => !element.hasAttribute("hidden") && element.getAttribute("aria-hidden") !== "true");
}

/** 小白说明：统一处理 Escape、焦点循环和关闭后的焦点返回。 */
export function Dialog(props: {
  isOpen: boolean;
  title: ReactNode;
  description?: string;
  children: ReactNode;
  onClose: () => void;
  className?: string;
  labelledBy?: string;
}) {
  const generatedTitleId = useId();
  const overlayIdRef = useRef(Symbol("repomind-dialog"));
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(props.onClose);
  const titleId = props.labelledBy ?? generatedTitleId;

  useEffect(() => {
    onCloseRef.current = props.onClose;
  }, [props.onClose]);

  useEffect(() => {
    if (!props.isOpen) return;
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const unregister = registerOverlay({
      id: overlayIdRef.current,
      element: dialog,
      close: () => onCloseRef.current(),
      returnFocus: returnFocusRef.current,
    });
    const first = focusableElements(dialog)[0];
    (first ?? dialog)?.focus();

    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (!isTopOverlay(overlayIdRef.current)) return;
      if (event.key !== "Tab") return;
      const focusable = focusableElements(dialog);
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const firstElement = focusable[0];
      const lastElement = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      unregister();
    };
  }, [props.isOpen]);

  if (!props.isOpen) return null;

  function closeFromOverlay(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) props.onClose();
  }

  return (
    <div className="rm-overlay" onMouseDown={closeFromOverlay}>
      <div
        ref={dialogRef}
        className={`rm-dialog ${props.className ?? ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={props.description ? descriptionId : undefined}
        tabIndex={-1}
      >
        <div className="rm-dialog-title" id={titleId}>{props.title}</div>
        {props.description && <p className="rm-dialog-description" id={descriptionId}>{props.description}</p>}
        {props.children}
      </div>
    </div>
  );
}
