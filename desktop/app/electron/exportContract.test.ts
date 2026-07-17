import { describe, expect, it } from "vitest";

import { validateSaveTextRequest } from "./exportContract";

describe("共享导出 IPC 契约", () => {
  it("接受共享契约定义的 Markdown 和 JSON 请求", () => {
    expect(validateSaveTextRequest({ suggestedName: "report", content: "# report", kind: "markdown" })).toEqual({
      suggestedName: "report",
      content: "# report",
      kind: "markdown",
    });
    expect(validateSaveTextRequest({ suggestedName: "trace", content: "{}", kind: "json" }).kind).toBe("json");
  });

  it("拒绝未知 kind，不能静默转换为 Markdown", () => {
    expect(() => validateSaveTextRequest({
      suggestedName: "report",
      content: "content",
      kind: "html",
    })).toThrow("不支持的导出类型");
  });

  it("按 UTF-8 字节数限制非 ASCII 内容，而不是按 JavaScript 字符数", () => {
    const chinese = "中".repeat(Math.floor((10 * 1024 * 1024) / 3));
    expect(validateSaveTextRequest({
      suggestedName: "中文报告",
      content: chinese,
      kind: "markdown",
    }).content).toBe(chinese);
    expect(() => validateSaveTextRequest({
      suggestedName: "中文报告",
      content: chinese + "中",
      kind: "markdown",
    })).toThrow("10 MB");
  });

  it("在 IPC 边界拒绝缺失文件名和超限内容", () => {
    expect(() => validateSaveTextRequest({ content: "content", kind: "markdown" })).toThrow("文件名无效");
    expect(() => validateSaveTextRequest({
      suggestedName: "report",
      content: "x".repeat(10 * 1024 * 1024 + 1),
      kind: "markdown",
    })).toThrow("10 MB");
  });
});
