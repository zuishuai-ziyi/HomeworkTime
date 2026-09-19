import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// server.web：后台管理前端（Vue3 + Vite + Element Plus）
// dev 模式通过 proxy 把 /api 与 /uploads 转发到本地服务端 127.0.0.1:3000；
// 构建产物（dist/）部署时由 nginx 反代 /api，此处无需额外配置。
export default defineConfig({
  plugins: [vue()],
  base: './',
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:3000',
        changeOrigin: true
      },
      '/uploads': {
        target: 'http://127.0.0.1:3000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500
  }
})