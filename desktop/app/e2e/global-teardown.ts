/**
 * E2E 应优先通过 Electron 正式生命周期关闭本次启动的后端。
 * 这里故意不扫描或强制终止系统进程；若仍有残留，让测试失败并保留诊断信息。
 */
export default function globalTeardown(): void {
  // 无额外系统级清理。
}
