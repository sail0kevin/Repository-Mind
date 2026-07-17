/// <reference types="vitest/config" />

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base: './' 是 Electron file:// 场景的关键，否则页面会空白
export default defineConfig({
  base: "./",
  plugins: [react()],
  root: "renderer",
  build: {
    outDir: "../dist-renderer",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
  },
  test: {
    // jsdom 让组件测试拥有浏览器 DOM；setupFiles 统一加载 RTL 断言。
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
    include: ["**/*.{test,spec}.{ts,tsx}", "../electron/**/*.{test,spec}.ts"],
    restoreMocks: true,
  },
});
