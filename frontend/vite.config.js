import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期把 /api 代理到 FastAPI 后端。
// 联调端口由 LEXFIN_BACKEND_PORT 决定（默认 8002；8000/8001 曾被历史进程占用），
// scripts/dev-start.ps1 会注入同名环境变量，保证前后端端口一致。
// 详见 docs/12-本地联调环境说明.md。
const backendPort = process.env.LEXFIN_BACKEND_PORT || '8002'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
})
