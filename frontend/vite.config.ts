import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { sentryVitePlugin } from '@sentry/vite-plugin'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    build: {
      sourcemap: 'hidden',
      rollupOptions: {
        output: {
          manualChunks(id: string) {
            if (id.includes('react-dom') || id.includes('react-router-dom') || id.includes('/react/')) {
              return 'vendor';
            }
            if (id.includes('@auth0/auth0-react')) {
              return 'auth';
            }
            if (id.includes('recharts')) {
              return 'charts';
            }
            if (id.includes('@tanstack/react-query')) {
              return 'query';
            }
          },
        },
      },
    },
    plugins: [
      react(),
      env.SENTRY_AUTH_TOKEN
        ? sentryVitePlugin({
            org: 'commodities-compass',
            project: 'commodities-compass',
            authToken: env.SENTRY_AUTH_TOKEN,
          })
        : null,
    ].filter(Boolean),
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    define: {
      'import.meta.env.AUTH0_DOMAIN': JSON.stringify(env.AUTH0_DOMAIN),
      'import.meta.env.AUTH0_CLIENT_ID': JSON.stringify(env.AUTH0_CLIENT_ID),
      'import.meta.env.AUTH0_API_AUDIENCE': JSON.stringify(env.AUTH0_API_AUDIENCE),
      'import.meta.env.AUTH0_REDIRECT_URI': JSON.stringify(env.AUTH0_REDIRECT_URI),
      'import.meta.env.API_BASE_URL': JSON.stringify(env.API_BASE_URL),
      'import.meta.env.SENTRY_DSN': JSON.stringify(env.SENTRY_DSN || ''),
    },
  }
})
