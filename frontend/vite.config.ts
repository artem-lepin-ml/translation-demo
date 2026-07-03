/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Override for a side-by-side backend (e.g. debugging on a non-default port):
      //   VITE_API_PROXY=http://localhost:8010 npm run dev -- --port 5183
      '/api': process.env.VITE_API_PROXY ?? 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    css: false,
  },
});
