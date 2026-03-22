import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { oidcSpa } from 'oidc-spa/vite-plugin'
import path from 'path'

export default defineConfig({
  plugins: [react(), oidcSpa()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:3200',
        changeOrigin: true,
      },
    },
  },
})
