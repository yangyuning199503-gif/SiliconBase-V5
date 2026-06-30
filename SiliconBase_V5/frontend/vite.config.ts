import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // 加载环境变量
  const env = loadEnv(mode, process.cwd(), '')
  
  // ═══════════════════════════════════════════════════════════════════════════
  // SiliconBase V5 端口配置
  // ═══════════════════════════════════════════════════════════════════════════
  // 标准端口配置：
  //   - HTTP API:    8600
  //   - WebSocket:   8600 (统一由 FastAPI 处理)
  //   - Frontend:    5173
  // 
  // 环境变量覆盖：
  //   VITE_API_PORT=8600
  //   VITE_API_PROXY_TARGET=http://127.0.0.1:8600
  // ═══════════════════════════════════════════════════════════════════════════
  
  // API 代理目标配置（优先使用环境变量）
  const apiPort = parseInt(env.VITE_API_PORT || '8600', 10)
  
  const apiTarget = env.VITE_API_PROXY_TARGET || `http://127.0.0.1:${apiPort}`
  
  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 5173,
      host: true,
      strictPort: false,  // 如果 5173 被占用，允许使用其他端口（如 5174）
      proxy: {
        // API 请求转发到后端 HTTP API
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          // 添加错误处理
          configure: (proxy, _options) => {
            proxy.on('error', (err, _req, _res) => {
              console.warn('[Vite Proxy] API 代理错误:', err.message);
            });
            proxy.on('proxyReq', (proxyReq, req, _res) => {
              console.log('[Vite Proxy] API 请求:', req.method, req.url, '->', apiTarget + req.url);
            });
          },
        },
        // WebSocket 统一代理到 FastAPI (8600)
        // 原独立 WebSocket 服务器 (8601) 已弃用，所有 /ws/* 由 cloud_api.py 处理
        '/ws': {
          target: apiTarget,
          ws: true,
          changeOrigin: true,
          configure: (proxy, _options) => {
            proxy.on('error', (err, _req, _res) => {
              console.warn('[Vite Proxy] WebSocket 代理错误:', err.message);
            });
            proxy.on('proxyReqWs', (proxyReq, req, _socket, _options, _head) => {
              console.log('[Vite Proxy] WebSocket 连接:', req.url, '->', apiTarget + req.url);
            });
          },
        },
        // [CORS FIX] 语音PTT接口代理
        '/voice_ptt': {
          target: apiTarget,
          changeOrigin: true,
          configure: (proxy, _options) => {
            proxy.on('error', (err, _req, _res) => {
              console.warn('[Vite Proxy] Voice PTT 代理错误:', err.message);
            });
            proxy.on('proxyReq', (proxyReq, req, _res) => {
              console.log('[Vite Proxy] Voice PTT 请求:', req.method, req.url, '->', apiTarget + req.url);
            });
          },
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: true,
    },
  }
})
