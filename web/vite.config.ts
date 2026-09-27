// 'vitest/config' re-exports Vite's defineConfig widened with the `test` block,
// so one config file type-checks for both the build and the test runner.
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8080' },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.spec.ts'],
  },
})
