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
});
