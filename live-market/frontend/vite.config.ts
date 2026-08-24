import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Live Market frontend on port 5174 to avoid clashing with the parent
// app on 5173. The /api proxy strips its prefix and forwards to the
// Live Market backend on 8001.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5174,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
