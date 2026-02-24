import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy API requests to the Ground API server during development
      '/api': {
        target: 'http://localhost:3000',
        changeOrigin: true,
      },
      // Proxy WebSocket connections to the WS gateway
      '/ws': {
        target: 'ws://localhost:8081',
        ws: true,
      },
    },
  },
});
