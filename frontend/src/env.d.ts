/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly AUTH0_DOMAIN: string;
  readonly AUTH0_CLIENT_ID: string;
  readonly AUTH0_API_AUDIENCE: string;
  readonly AUTH0_REDIRECT_URI: string;
  readonly API_BASE_URL: string;
  readonly MODE: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
