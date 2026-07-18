import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { Dialog } from "./Dialog";

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>打开设置</button>
      <Dialog isOpen={open} onClose={() => setOpen(false)} title="系统设置">
        <button>保存</button>
        <button onClick={() => setOpen(false)}>关闭</button>
      </Dialog>
    </>
  );
}

afterEach(cleanup);

describe("Dialog", () => {
  it("closes with Escape and restores trigger focus", () => {
    render(<DialogHarness />);
    const trigger = screen.getByRole("button", { name: "打开设置" });
    trigger.focus();
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "系统设置" })).toBeVisible();
    expect(screen.getByRole("button", { name: "保存" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("keeps the current field focused when the parent rerenders", () => {
    function RerenderHarness() {
      const [value, setValue] = useState("");
      return (
        <Dialog isOpen onClose={() => undefined} title="编辑设置">
          <input aria-label="模型名" value={value} onChange={(event) => setValue(event.target.value)} />
          <button>关闭</button>
        </Dialog>
      );
    }

    render(<RerenderHarness />);
    const input = screen.getByRole("textbox", { name: "模型名" });
    expect(input).toHaveFocus();
    fireEvent.change(input, { target: { value: "LongCat" } });
    expect(input).toHaveFocus();
    expect(input).toHaveValue("LongCat");
  });

  it("ignores descendants removed from the Tab order", () => {
    render(
      <Dialog isOpen onClose={() => undefined} title="命令面板">
        <input aria-label="筛选命令" />
        <button aria-label="关闭命令面板">关闭</button>
        <button tabIndex={-1}>命令选项</button>
      </Dialog>,
    );

    const input = screen.getByRole("textbox", { name: "筛选命令" });
    const close = screen.getByRole("button", { name: "关闭命令面板" });
    close.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(input).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(close).toHaveFocus();
  });
});
