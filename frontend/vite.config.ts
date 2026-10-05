import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // VITE_* values are compiled into the public bundle. The application has
  // no API key any more; refuse an old VITE_API_KEY so it cannot leak.
  const env = loadEnv(mode, '.', 'VITE_')
  if (env.VITE_API_KEY) {
    throw new Error(
      'VITE_API_KEY is set, but every VITE_ value is compiled into the public bundle. ' +
        'Remove it: the application is open and needs no key.',
    )
  }
  return {
    plugins: [react()],
    server: { port: 5173 },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
    },
  }
})
