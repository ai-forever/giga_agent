import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import compression from "vite-plugin-compression";
import path from "path";
import { fileURLToPath } from "url";

export default defineConfig(({ mode }) => {
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = path.dirname(__filename);
  const env = loadEnv(mode, path.resolve(__dirname, ".."), "");

  const JUPYTER_UPLOAD_API = env.JUPYTER_UPLOAD_API || process.env.JUPYTER_UPLOAD_API || "http://127.0.0.1:9092/";
  const LANGGRAPH_API_URL = env.LANGGRAPH_API_URL || process.env.LANGGRAPH_API_URL || "http://127.0.0.1:2024/";

  return {
    plugins: [
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
    server: {
      proxy: {
        "/files": {
          target: JUPYTER_UPLOAD_API,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/files/, ""),
        },
        "/graph": {
          target: LANGGRAPH_API_URL,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/graph/, ""),
        },
      },
      port: 3000,
    },
    build: {
      outDir: "dist",
      sourcemap: false,
    },
  };
});
