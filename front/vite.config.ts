import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import compression from "vite-plugin-compression";
import path from "path";
import { fileURLToPath } from "url";
import tailwindcss from "@tailwindcss/vite";
import { constants as zlibConstants } from "zlib";
import svgr from "vite-plugin-svgr";

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
    base: "/",
    plugins: [
      tailwindcss(),
      svgr(),
      react(),
      compression({
        algorithm: "gzip",
        ext: ".gz",
        filter: /\.(js|mjs|json|css|html|svg)$/i,
        threshold: 1024, // сжимать файлы больше 1КБ
        deleteOriginFile: false,
        compressionOptions: {
          level: 9,
        },
      }),
      compression({
        algorithm: "brotliCompress",
        ext: ".br",
        filter: /\.(js|mjs|json|css|html|svg)$/i,
        threshold: 1024,
        deleteOriginFile: false,
        compressionOptions: {
          params: {
            [zlibConstants.BROTLI_PARAM_QUALITY]: 11,
          },
        },
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
              "/app-config.js": {
                target: "http://localhost:9090/",
                changeOrigin: true,
              },
            },
            port: 3000,
          }
        : {},
    build: {
      outDir: "dist",
      sourcemap: false,
      target: "es2020",
      minify: "terser",
      modulePreload: {
        polyfill: false,
      },
      terserOptions: {
        compress: {
          passes: 2,
          drop_console: true,
          drop_debugger: true,
        },
        format: {
          comments: false,
        },
      },
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes("node_modules")) return;
            if (id.includes("plotly.js") || id.includes("react-plotly.js")) {
              return "plotly";
            }
            if (id.includes("react-syntax-highlighter")) return "syntax";
            if (id.includes("katex")) return "katex";
            if (id.includes("@langchain")) return "langchain";
            if (id.includes("@radix-ui")) return "radix";
            if (id.includes("framer-motion")) return "motion";
          },
        },
      },
    },
  };
});
