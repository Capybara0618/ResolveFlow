// 'vitest/config' re-exports Vite's defineConfig widened with the `test` block,
// so one config file type-checks for both the build and the test runner.
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

// The config runs in Node, and this project deliberately has no @types/node dependency.
// Declaring the one global it reads keeps the type-check honest without adding a package
// for two environment lookups.
declare const process: { env: Record<string, string | undefined> }

// The backend the dev server proxies to, and the port it serves on. Both default to the shared
// local stack, so an ordinary `pnpm dev` is unchanged. The reviewer demonstration sets them
// explicitly (VITE_API_PROXY=http://127.0.0.1:8180 VITE_PORT=5174) rather than pointing 5173 at
// another backend behind the user's back: a page that silently reads a different environment is
// exactly the confusion the demonstration exists to avoid.
const apiTarget = process.env.VITE_API_PROXY || 'http://127.0.0.1:8080'
const devPort = Number(process.env.VITE_PORT || 5173)

export default defineConfig({
  plugins: [vue()],
  server: {
    port: devPort,
    proxy: { '/api': apiTarget },
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
