import React from 'react';
import ReactDOM from 'react-dom/client';
import { Auth0Provider } from '@auth0/auth0-react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import { ErrorFallback } from './components/ErrorFallback';
import { initSentry, Sentry } from './sentry';
import './index.css';

initSentry();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      retry: 1,
    },
  },
});

const domain = import.meta.env.AUTH0_DOMAIN;
const clientId = import.meta.env.AUTH0_CLIENT_ID;
const audience = import.meta.env.AUTH0_API_AUDIENCE;
const redirectUri = import.meta.env.AUTH0_REDIRECT_URI || window.location.origin;

if (import.meta.env.PROD) {
  for (const [name, value] of Object.entries({ AUTH0_DOMAIN: domain, AUTH0_CLIENT_ID: clientId, AUTH0_API_AUDIENCE: audience })) {
    if (!value) throw new Error(`Missing required env var: ${name}`);
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Sentry.ErrorBoundary fallback={<ErrorFallback />}>
      <Auth0Provider
        domain={domain}
        clientId={clientId}
        authorizationParams={{
          redirect_uri: redirectUri,
          audience: audience,
        }}
        cacheLocation="localstorage"
        useRefreshTokens={true}
      >
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      </Auth0Provider>
    </Sentry.ErrorBoundary>
  </React.StrictMode>
);
