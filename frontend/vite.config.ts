import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  // PRODUCTION: the browser calls the backend directly at VITE_API_BASE_URL (baked into the
  // bundle at build time). Without it the deployed site would call its own origin and fail in
  // a confusing way, so fail the build with a clear message instead.
  // (Set it to "/" if a reverse proxy serves frontend and API under one origin.)
  if (command === 'build' && !env.VITE_API_BASE_URL) {
    throw new Error(
      'VITE_API_BASE_URL is not set. Set it to your backend URL, e.g. ' +
        'VITE_API_BASE_URL=https://your-api.onrender.com (Vercel: Project > Settings > Environment Variables).',
    )
  }

  // DEVELOPMENT ONLY (this code runs in Node, never in the browser bundle): the backend has no
  // CORS config for the dev origin by default, so `npm run dev` forwards /api and /health to
  // BACKEND_URL. 127.0.0.1 rather than "localhost": on Windows "localhost" tries IPv6 first.
  const backend = env.BACKEND_URL || 'http://127.0.0.1:8000'
  const proxy = {
    '/api': { target: backend, changeOrigin: true },
    '/health': { target: backend, changeOrigin: true },
  }

  return {
    plugins: [react(), tailwindcss()],
    server: { proxy },
    preview: { proxy },
  }
})
