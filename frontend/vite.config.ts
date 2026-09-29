import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // No secret may ship in the bundle: VITE_* values are public. The API key
  // used to be VITE_API_KEY; it is now typed at sign-in (services/session.ts).
  // Refuse to build or serve with it set, so an old .env cannot leak it.
  const env = loadEnv(mode, '.', 'VITE_')
  if (env.VITE_API_KEY) {
    throw new Error(
      'VITE_API_KEY is set, but every VITE_ value is compiled into the public bundle. ' +
        'Remove it: the UI signs in at runtime with the key (OGR_API_KEY / OGR_ADMIN_KEY).',
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
