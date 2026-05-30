import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { sentryVitePlugin } from '@sentry/vite-plugin'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  const sentryAuthToken = env.SENTRY_AUTH_TOKEN
  const release = env.GIT_COMMIT_SHA

  const plugins = [react()]
  if (sentryAuthToken && release) {
    plugins.push(
      sentryVitePlugin({
        org: 'commodities-compass',
        project: 'commodities-compass',
        authToken: sentryAuthToken,
        release: { name: release },
        sourcemaps: {
          assets: ['dist/assets/**'],
          filesToDeleteAfterUpload: ['dist/assets/**/*.map'],
        },
        telemetry: false,
      })
    )
  }

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
            if (id.includes('@sentry')) {
              return 'sentry';
            }
          },
        },
      },
    },
    plugins,
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
      'import.meta.env.SENTRY_DSN': JSON.stringify(env.SENTRY_DSN),
      'import.meta.env.ENVIRONMENT': JSON.stringify(env.ENVIRONMENT ?? 'production'),
      'import.meta.env.GIT_COMMIT_SHA': JSON.stringify(env.GIT_COMMIT_SHA),
    },
  }
})
