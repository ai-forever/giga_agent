import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import compression from "vite-plugin-compression";
import path from "path";
import { fileURLToPath } from "url";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = path.dirname(__filename);
  const env = loadEnv(mode, path.resolve(__dirname, ".."), "");
  const runningEnv = env.RUNNING_ENV || process.env.RUNNING_ENV || "local";

  const JUPYTER_UPLOAD_API =
    env.JUPYTER_UPLOAD_API ||
    process.env.JUPYTER_UPLOAD_API ||
    "http://127.0.0.1:9092/";
  const LANGGRAPH_API_URL =
    env.LANGGRAPH_API_URL ||
    process.env.LANGGRAPH_API_URL ||
    "http://127.0.0.1:2024/";

  const GIGA_AGENT_API = "http://127.0.0.1:9090/";

  if (!process.env.VITE_LANGCONNECT_API_URL) {
    process.env.VITE_LANGCONNECT_API_URL =
      env.LANGCONNECT_API_URL || process.env.LANGCONNECT_API_URL || "";
  }
  if (!process.env.VITE_LANGCONNECT_API_SECRET_TOKEN) {
    process.env.VITE_LANGCONNECT_API_SECRET_TOKEN =
      env.LANGCONNECT_API_SECRET_TOKEN ||
      process.env.LANGCONNECT_API_SECRET_TOKEN ||
      "";
  }
  if (!process.env.VITE_MCP_PROXY_URL) {
    process.env.VITE_MCP_PROXY_URL =
      env.VITE_MCP_PROXY_URL || process.env.VITE_MCP_PROXY_URL || "";
  }
  if (!process.env.VITE_MEMORY_ENABLED) {
    process.env.VITE_MEMORY_ENABLED =
      env.GIGA_AGENT_MEMORY_ENABLED ||
      process.env.GIGA_AGENT_MEMORY_ENABLED ||
      "true";
  }

  return {
    plugins: [
      tailwindcss(),
      react(),
      compression({
        algorithm: "gzip",
        ext: ".gz",
        // включаем .map
        filter: /\.(js|mjs|json|css|map)$/i,
        threshold: 1024, // сжимать файлы больше 1КБ
        deleteOriginFile: false,
      }),
    ],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },

    server:
      runningEnv === "local"
        ? {
            proxy: {
              "/api": {
                target: GIGA_AGENT_API,
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api/, ""),
              },
            },
            port: 3000,
          }
        : {},
    build: {
      outDir: "dist",
      sourcemap: false,
    },
  };
});
