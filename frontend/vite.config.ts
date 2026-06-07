/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

const BACKEND = process.env.VITE_BACKEND_URL ?? "http://localhost:8000"

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 浏览器同源:前端请求 /api/* 代理到后端;SSE 也透传
      "/api": { target: BACKEND, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
})
