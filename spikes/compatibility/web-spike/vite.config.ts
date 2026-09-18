import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// T00 spike: proves the fixed frontend line (Vue3 + TS + Vite + Node 22 + pnpm) builds.
export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})