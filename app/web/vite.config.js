import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";
const apiProxyPrefix = "^/api(/|$)";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      [apiProxyPrefix]: apiProxyTarget,
    },
  },
  preview: {
    port: 4173,
    strictPort: false,
    proxy: {
      [apiProxyPrefix]: apiProxyTarget,
    },
  },
});
