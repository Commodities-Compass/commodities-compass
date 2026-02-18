import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { sentryVitePlugin } from '@sentry/vite-plugin'
import path from 'path'
import { fileURLToPath } from 'url'

// ES Module equivalent of __dirname
const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Load env file based on `mode` in the current working directory.
  // Set the third parameter to '' to load all env regardless of the `VITE_` prefix.
  const env = loadEnv(mode, process.cwd(), '')

  return {
    build: {
      sourcemap: true,
    },
    plugins: [
      react(),
      // Sourcemap upload — only runs when SENTRY_AUTH_TOKEN is set (CI/build)
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
        '@components': path.resolve(__dirname, './src/components'),
        'pages': path.resolve(__dirname, './src/pages'),
        '@utils': path.resolve(__dirname, './src/utils'),
        '(components)': path.resolve(__dirname, './src/(components)'),
      }
    },
    // Define environment variables to be exposed to the client
    define: {
      'import.meta.env.AUTH0_DOMAIN': JSON.stringify(env.AUTH0_DOMAIN),
      'import.meta.env.AUTH0_CLIENT_ID': JSON.stringify(env.AUTH0_CLIENT_ID),
      'import.meta.env.AUTH0_API_AUDIENCE': JSON.stringify(env.AUTH0_API_AUDIENCE),
      'import.meta.env.AUTH0_REDIRECT_URI': JSON.stringify(env.AUTH0_REDIRECT_URI),
      'import.meta.env.API_BASE_URL': JSON.stringify(env.API_BASE_URL),
      'import.meta.env.SENTRY_DSN': JSON.stringify(env.SENTRY_DSN || ''),
    }
  }
})
