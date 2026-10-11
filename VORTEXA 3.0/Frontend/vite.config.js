import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  preview: {
    host: '127.0.0.1',
    port: 4173,
    proxy: {
      '/api/v1/ingest': 'http://localhost:8000',
      '/api/v1/analyze': 'http://localhost:8001',
      '/api/v1/auth': 'http://localhost:8000',
      '/api/v1/audits': 'http://localhost:8000',
      '/api/v1/sources': 'http://localhost:8000',
    },
  },
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api/v1/ingest': 'http://localhost:8000',
      '/api/v1/analyze': 'http://localhost:8001',
      '/api/v1/auth': 'http://localhost:8000',
      '/api/v1/audits': 'http://localhost:8000',
      '/api/v1/sources': 'http://localhost:8000',
    },
  },
})
