import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const appWebDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(appWebDir, "../..");
const apiProxyPrefix = "^/api(/|$)";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repoRoot, "VITE_");
  const apiProxyTarget =
    process.env.VITE_API_PROXY_TARGET || env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";

  return {
    envDir: repoRoot,
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
  };
});
