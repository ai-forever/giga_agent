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

  if (!process.env.VITE_MCP_PROXY_URL) {
    process.env.VITE_MCP_PROXY_URL =
      env.VITE_MCP_PROXY_URL || process.env.VITE_MCP_PROXY_URL || "";
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
                target: "http://localhost:9090/api",
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
