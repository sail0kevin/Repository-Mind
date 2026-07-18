type OverlayEntry = {
  id: symbol;
  element: HTMLElement;
  close: () => void;
  returnFocus: HTMLElement | null;
};

const overlays: OverlayEntry[] = [];
const backgroundStates = new Map<HTMLElement, { inert: boolean; ariaHidden: string | null }>();
let previousBodyOverflow = "";
let listening = false;

function updateModalBoundary() {
  overlays.forEach((entry, index) => {
    const isTopmost = index === overlays.length - 1;
    entry.element.inert = !isTopmost;
    if (isTopmost) entry.element.removeAttribute("aria-hidden");
    else entry.element.setAttribute("aria-hidden", "true");
  });

  const appRoot = document.querySelector<HTMLElement>(".af-app");
  Array.from(appRoot?.children ?? []).forEach((child) => {
    if (!(child instanceof HTMLElement)) return;
    const containsOverlay = overlays.some((entry) => child.contains(entry.element));
    const containsTopmost = overlays.length > 0 && child.contains(overlays[overlays.length - 1].element);
    if (containsOverlay) {
      child.inert = !containsTopmost;
      if (containsTopmost) child.removeAttribute("aria-hidden");
      else child.setAttribute("aria-hidden", "true");
      return;
    }
    if (!backgroundStates.has(child)) {
      backgroundStates.set(child, { inert: child.inert, ariaHidden: child.getAttribute("aria-hidden") });
    }
    child.inert = overlays.length > 0;
    if (overlays.length > 0) child.setAttribute("aria-hidden", "true");
  });
}

function handleEscape(event: KeyboardEvent) {
  if (event.key !== "Escape") return;
  const topmost = overlays[overlays.length - 1];
  if (!topmost) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  topmost.close();
}

/** 小白说明：所有 Dialog 和 Drawer 共用一个栈，Escape 永远只关闭视觉最上层。 */
export function registerOverlay(entry: OverlayEntry) {
  if (overlays.length === 0) {
    previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  overlays.push(entry);
  updateModalBoundary();

  if (!listening) {
    document.addEventListener("keydown", handleEscape);
    listening = true;
  }

  return () => {
    const index = overlays.findIndex((item) => item.id === entry.id);
    const wasTopmost = index === overlays.length - 1;
    if (index >= 0) overlays.splice(index, 1);
    updateModalBoundary();

    if (overlays.length === 0) {
      document.body.style.overflow = previousBodyOverflow;
      backgroundStates.forEach((state, element) => {
        element.inert = state.inert;
        if (state.ariaHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", state.ariaHidden);
      });
      backgroundStates.clear();
      document.removeEventListener("keydown", handleEscape);
      listening = false;
      if (entry.returnFocus?.isConnected) entry.returnFocus.focus();
      else document.querySelector<HTMLElement>(".af-header button, .af-center button, .af-left button")?.focus();
    } else if (wasTopmost) {
      const nextTopmost = overlays[overlays.length - 1];
      if (entry.returnFocus?.isConnected && nextTopmost.element.contains(entry.returnFocus)) {
        entry.returnFocus.focus();
        return;
      }
      const firstFocusable = nextTopmost.element.querySelector<HTMLElement>(
        'button:not([disabled]):not([tabindex="-1"]), [href]:not([tabindex="-1"]), input:not([disabled]):not([tabindex="-1"]), select:not([disabled]):not([tabindex="-1"]), textarea:not([disabled]):not([tabindex="-1"]), [tabindex]:not([tabindex="-1"])',
      );
      (firstFocusable ?? nextTopmost.element).focus();
    }
  };
}

export function isTopOverlay(id: symbol) {
  return overlays[overlays.length - 1]?.id === id;
}
