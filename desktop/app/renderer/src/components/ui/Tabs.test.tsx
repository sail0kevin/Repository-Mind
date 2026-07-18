import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Tabs } from "./Tabs";

afterEach(cleanup);

describe("Tabs", () => {
  it("exposes tab semantics and supports arrow navigation", () => {
    const onChange = vi.fn();
    render(
      <Tabs
        ariaLabel="工作区"
        value="qa"
        onChange={onChange}
        items={[
          { value: "catalog", label: "目录" },
          { value: "qa", label: "问答" },
          { value: "workflow", label: "工作流" },
        ]}
      />,
    );

    expect(screen.getByRole("tablist", { name: "工作区" })).toBeVisible();
    const qa = screen.getByRole("tab", { name: "问答" });
    expect(qa).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(qa, { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("workflow");
    expect(screen.getByRole("tab", { name: "工作流" })).toHaveFocus();
  });

  it("links the selected tab to a real panel", () => {
    function Harness() {
      const [value, setValue] = useState("catalog");
      return (
        <>
          <Tabs
            idBase="test-workspace"
            ariaLabel="工作区"
            value={value}
            onChange={setValue}
            items={[
              { value: "catalog", label: "目录" },
              { value: "qa", label: "问答" },
            ]}
          />
          <div
            id={`test-workspace-panel-${value}`}
            role="tabpanel"
            aria-labelledby={`test-workspace-tab-${value}`}
          >
            {value}
          </div>
        </>
      );
    }

    render(<Harness />);
    const catalog = screen.getByRole("tab", { name: "目录" });
    expect(document.getElementById(catalog.getAttribute("aria-controls")!)).toBe(screen.getByRole("tabpanel"));
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", catalog.id);

    fireEvent.click(screen.getByRole("tab", { name: "问答" }));
    const qa = screen.getByRole("tab", { name: "问答" });
    expect(document.getElementById(qa.getAttribute("aria-controls")!)).toBe(screen.getByRole("tabpanel"));
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", qa.id);
  });
});
