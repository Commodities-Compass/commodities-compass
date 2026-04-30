import axios from 'axios';

const API_BASE_URL = import.meta.env.API_BASE_URL || 'http://localhost:8000/api/v1';

if (!import.meta.env.API_BASE_URL && import.meta.env.PROD) {
  throw new Error('Missing required env var: API_BASE_URL');
}

let tokenGetter: (() => Promise<string>) | null = null;

export function setTokenGetter(getter: (() => Promise<string>) | null) {
  tokenGetter = getter;
}

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30_000,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use(
  async (config) => {
    // Try tokenGetter first (fresh token via Auth0 SDK)
    if (tokenGetter) {
      try {
        const token = await tokenGetter();
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
          localStorage.setItem('auth0_token', token);
          return config;
        }
      } catch {
        // tokenGetter failed — fall through to localStorage
      }
    }

    // Fallback: read cached token from localStorage
    const cachedToken = localStorage.getItem('auth0_token');
    if (cachedToken) {
      config.headers.Authorization = `Bearer ${cachedToken}`;
    }
    return config;
  },
  (error) => Promise.reject(error),
);

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('auth0_token');
      sessionStorage.setItem('auth_401_error', 'true');
      window.dispatchEvent(new CustomEvent('auth:token-expired'));
    } else {
      console.error(
        `[API Error] ${error.config?.method?.toUpperCase()} ${error.config?.url} — status=${error.response?.status ?? 'network'}`,
        error,
      );
    }
    return Promise.reject(error);
  },
);
