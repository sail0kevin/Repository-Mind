import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "./AppShell";

type Listener = (event: MediaQueryListEvent) => void;

function installMatchMedia(initialWidth: number) {
  let width = initialWidth;
  const listeners = new Map<string, Set<Listener>>();

  function matches(query: string) {
    const limit = Number(query.match(/max-width:\s*(\d+)px/)?.[1] ?? Number.POSITIVE_INFINITY);
    return width <= limit;
  }

  vi.stubGlobal("matchMedia", vi.fn((query: string) => {
    const mediaQuery = {
      media: query,
      get matches() { return matches(query); },
      onchange: null,
      addEventListener: (_type: string, listener: Listener) => {
        const current = listeners.get(query) ?? new Set<Listener>();
        current.add(listener);
        listeners.set(query, current);
      },
      removeEventListener: (_type: string, listener: Listener) => listeners.get(query)?.delete(listener),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    };
    return mediaQuery;
  }));

  return {
    resize(nextWidth: number) {
      width = nextWidth;
      listeners.forEach((queryListeners, query) => {
        queryListeners.forEach((listener) => listener({ matches: matches(query), media: query } as MediaQueryListEvent));
      });
    },
  };
}

function renderShell(onOverlayOpenChange = vi.fn()) {
  render(
    <AppShell
      leftPanel={<div>左侧内容</div>}
      centerPanel={<div>中心内容</div>}
      rightPanel={<div>右侧内容</div>}
      leftPanelWidth={280}
      onResizeStart={vi.fn()}
      onResizeReset={vi.fn()}
      onResizeKeyDown={vi.fn()}
      onOverlayOpenChange={onOverlayOpenChange}
    />,
  );
}

describe("AppShell responsive drawers", () => {
  beforeEach(() => {
    document.body.style.overflow = "";
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("closes the resource drawer when the desktop sidebar returns", () => {
    const media = installMatchMedia(800);
    renderShell();

    fireEvent.click(screen.getByRole("button", { name: /仓库与目录/ }));
    expect(screen.getByRole("dialog", { name: "仓库与知识目录" })).toBeVisible();

    act(() => media.resize(1024));
    expect(screen.queryByRole("dialog", { name: "仓库与知识目录" })).not.toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "仓库资源导航" })).toBeVisible();
    expect(document.body.style.overflow).toBe("");
  });

  it("closes the Inspector drawer when the three-column layout returns", () => {
    const media = installMatchMedia(1100);
    renderShell();

    fireEvent.click(screen.getByRole("button", { name: /Evidence 与状态/ }));
    expect(screen.getByRole("dialog", { name: "Evidence 与状态" })).toBeVisible();

    act(() => media.resize(1280));
    expect(screen.queryByRole("dialog", { name: "Evidence 与状态" })).not.toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Evidence 与仓库状态" })).toBeVisible();
    expect(document.body.style.overflow).toBe("");
  });
});
