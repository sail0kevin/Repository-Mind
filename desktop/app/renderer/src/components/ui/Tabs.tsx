import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";

export interface TabItem<T extends string> {
  value: T;
  label: ReactNode;
  testId?: string;
  badge?: string;
  disabled?: boolean;
}

/**
 * 小白说明：这个组件负责把一组按钮变成键盘和读屏软件都能理解的“标签页”。
 * 页面业务仍由父组件控制，Tabs 不会自己请求后端。
 */
export function Tabs<T extends string>(props: {
  ariaLabel: string;
  items: TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
  tabClassName?: string;
  idBase?: string;
}) {
  const generatedId = useId();
  const baseId = props.idBase ?? generatedId;
  const buttonsRef = useRef<Array<HTMLButtonElement | null>>([]);

  function moveFocus(event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) {
    const enabled = props.items
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => !item.disabled);
    const enabledPosition = enabled.findIndex(({ index }) => index === currentIndex);
    let nextPosition = enabledPosition;

    if (event.key === "ArrowRight") nextPosition = (enabledPosition + 1) % enabled.length;
    else if (event.key === "ArrowLeft") nextPosition = (enabledPosition - 1 + enabled.length) % enabled.length;
    else if (event.key === "Home") nextPosition = 0;
    else if (event.key === "End") nextPosition = enabled.length - 1;
    else return;

    event.preventDefault();
    const nextIndex = enabled[nextPosition]?.index;
    if (nextIndex === undefined) return;
    props.onChange(props.items[nextIndex].value);
    buttonsRef.current[nextIndex]?.focus();
  }

  return (
    <div className={props.className ?? "rm-tabs"} role="tablist" aria-label={props.ariaLabel}>
      {props.items.map((item, index) => {
        const selected = item.value === props.value;
        return (
          <button
            key={item.value}
            ref={(node) => { buttonsRef.current[index] = node; }}
            id={`${baseId}-tab-${item.value}`}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={selected ? `${baseId}-panel-${item.value}` : undefined}
            data-panel-id={`${baseId}-panel-${item.value}`}
            data-testid={item.testId}
            tabIndex={selected ? 0 : -1}
            disabled={item.disabled}
            className={`${props.tabClassName ?? "rm-tab"} ${selected ? "active" : ""}`}
            onClick={() => props.onChange(item.value)}
            onKeyDown={(event) => moveFocus(event, index)}
          >
            {item.label}
            {item.badge && <span className="rm-tab-badge">{item.badge}</span>}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel(props: {
  id: string;
  labelledBy: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div id={props.id} role="tabpanel" aria-labelledby={props.labelledBy} className={props.className}>
      {props.children}
    </div>
  );
}
