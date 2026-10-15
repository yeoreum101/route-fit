import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 원래 화면(web/)과 같은 주소를 쓰도록 페이지 3개(/, /stats.html, /admin.html)를 각각 빌드한다.
// 개발 서버는 /api 요청을 FastAPI(8000)로 넘긴다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
  build: {
    rollupOptions: {
      input: {
        index: "index.html",
        stats: "stats.html",
        admin: "admin.html",
      },
    },
  },
});
