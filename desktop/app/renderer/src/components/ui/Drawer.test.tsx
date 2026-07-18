import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { Drawer } from "./Drawer";

afterEach(cleanup);

describe("Drawer", () => {
  it("keeps the current field focused when the parent rerenders", () => {
    function Harness() {
      const [value, setValue] = useState("");
      return (
        <Drawer isOpen onClose={() => undefined} title="仓库导航">
          <input aria-label="仓库路径" value={value} onChange={(event) => setValue(event.target.value)} />
          <button>关闭</button>
        </Drawer>
      );
    }

    render(<Harness />);
    const input = screen.getByRole("textbox", { name: "仓库路径" });
    expect(input).toHaveFocus();
    fireEvent.change(input, { target: { value: "G:/repo" } });
    expect(input).toHaveFocus();
    expect(input).toHaveValue("G:/repo");
  });

  it("keeps one modal boundary and restores the underlying drawer", () => {
    function Harness() {
      const [outerOpen, setOuterOpen] = useState(true);
      const [innerOpen, setInnerOpen] = useState(true);
      return (
        <>
          <Drawer isOpen={outerOpen} onClose={() => setOuterOpen(false)} title="Inspector">
            <button>底层按钮</button>
          </Drawer>
          <Drawer isOpen={innerOpen} onClose={() => setInnerOpen(false)} title="源码证据">
            <button>顶层按钮</button>
          </Drawer>
        </>
      );
    }

    render(<Harness />);
    const outer = screen.getByText("Inspector").closest("aside")!;
    expect(outer).toHaveAttribute("aria-hidden", "true");
    expect(outer).toHaveProperty("inert", true);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "源码证据" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Inspector" })).toBeVisible();
    expect(outer).not.toHaveAttribute("aria-hidden");
    expect(outer).toHaveProperty("inert", false);
  });
});
