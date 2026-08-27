import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// ── Kora — dev proxies for the two backends ──────────────────
//  /api   → Backend Auditor      (default http://localhost:8000)
//  /conc  → Backend Conciliador  (default http://localhost:8001)
//
// In production, point the frontend straight at the deployed URLs with
//   VITE_AUDITOR_URL / VITE_CONCILIADOR_URL  (see .env.example) — the
//   proxies below are only used during `npm run dev`.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const AUDITOR = env.VITE_AUDITOR_PROXY || 'http://localhost:8000'
  const CONCILIADOR = env.VITE_CONCILIADOR_PROXY || 'http://localhost:8001'

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: AUDITOR,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/api/, '/api'),
        },
        '/conc': {
          target: CONCILIADOR,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/conc/, ''),
        },
      },
    },
  }
})
