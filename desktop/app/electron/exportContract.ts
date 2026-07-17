import type { DesktopBridge, SaveTextRequest, SaveTextResult } from "./bridgeContract";

/**
 * 运行时校验渲染进程传来的导出请求。TypeScript 类型不能保护 IPC 边界，
 * 因此主进程必须显式拒绝未知 kind，不能静默降级成 Markdown。
 */
export function validateSaveTextRequest(value: unknown): SaveTextRequest {
  if (!value || typeof value !== "object") {
    throw new Error("导出请求无效。");
  }
  const request = value as Partial<Record<keyof SaveTextRequest, unknown>>;
  if (typeof request.suggestedName !== "string" || request.suggestedName.length > 200) {
    throw new Error("导出文件名无效。");
  }
  if (typeof request.content !== "string" || Buffer.byteLength(request.content, "utf8") > 10 * 1024 * 1024) {
    throw new Error("导出内容无效或超过 10 MB 限制。");
  }
  if (request.kind !== "markdown" && request.kind !== "json") {
    throw new Error("不支持的导出类型。");
  }
  return request as SaveTextRequest;
}

/** 仅用于在三个边界都编译检查同一个桥类型。 */
export type { DesktopBridge, SaveTextRequest, SaveTextResult };
