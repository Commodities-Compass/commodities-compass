import axios from 'axios';
import * as Sentry from '@sentry/react';

const API_BASE_URL = import.meta.env.API_BASE_URL || 'http://localhost:8000/api/v1';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add auth token
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('auth0_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Token expired or invalid - set a flag and clear token
      // This flag will be checked by the login page to prevent redirect loops
      sessionStorage.setItem('auth_401_error', 'true');
      localStorage.removeItem('auth0_token');

      // Trigger a custom event that App.tsx can listen to for coordinated logout
      // This prevents multiple logout attempts and ensures proper cleanup
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
  }
);
