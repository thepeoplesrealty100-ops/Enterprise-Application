import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Response Console is built standalone and served by the backend at /console
// (see backend/app.py — mounted only when frontend/dist exists). During
// development it proxies /api to the FastAPI backend on :8000 so the
// existing routers/response.py endpoints work without CORS setup.
export default defineConfig({
  plugins: [react()],
  base: '/console/',
  build: {
    outDir: 'dist',
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
});
