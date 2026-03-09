import axios from 'axios';
import * as Sentry from '@sentry/react';

const API_BASE_URL = import.meta.env.API_BASE_URL || 'http://localhost:8000/api/v1';

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
    if (tokenGetter) {
      try {
        const token = await tokenGetter();
        config.headers.Authorization = `Bearer ${token}`;
      } catch {
        // Token fetch failed — proceed without auth header
      }
    }
    return config;
  },
  (error) => Promise.reject(error),
);

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      sessionStorage.setItem('auth_401_error', 'true');
      window.dispatchEvent(new CustomEvent('auth:token-expired'));
    } else {
      Sentry.captureException(error, {
        tags: {
          api_url: error.config?.url,
          api_status: String(error.response?.status ?? 'network'),
        },
      });
    }
    return Promise.reject(error);
  },
);
