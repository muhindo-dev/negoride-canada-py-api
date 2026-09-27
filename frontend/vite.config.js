import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// Dev: `npm run dev` proxies the API + Socket.IO to the Flask backend
// (VITE_API_TARGET, default http://localhost:5001). Prod: Flask serves
// frontend/build at `/` (backend/app.py serve_admin*).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const target = env.VITE_API_TARGET || 'http://localhost:5001';
  return {
    plugins: [react()],
    server: {
      port: 3000,
      proxy: {
        '/api': { target, changeOrigin: true },
        '/uploads': { target, changeOrigin: true },
        '/storage': { target, changeOrigin: true },
        '/socket.io': { target, changeOrigin: true, ws: true },
      },
    },
    build: {
      outDir: 'build',
      emptyOutDir: true,
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            mantine: ['@mantine/core', '@mantine/hooks', '@mantine/notifications'],
            query: ['@tanstack/react-query', 'axios', 'socket.io-client'],
            charts: ['recharts'],
          },
        },
      },
    },
  };
});
