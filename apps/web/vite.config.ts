import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  // pdf.js 的 worker 以 IIFE 经典 worker 加载（部分内嵌 WebView 不支持 module worker）
  worker: { format: "iife" },
  resolve: {
    alias: {
      "@shared": fileURLToPath(new URL("../../shared", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8787",
    },
  },
});
