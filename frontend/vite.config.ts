import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The proxy avoids CORS in development: the browser only ever talks to Vite.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.API_URL ?? "http://localhost:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
