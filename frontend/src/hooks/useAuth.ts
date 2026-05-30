import { useAuth0 } from '@auth0/auth0-react';
import { useEffect } from 'react';
import { setTokenGetter } from '@/api/client';
import { Sentry } from '@/sentry';

export const useAuth = () => {
  const { user, logout, getAccessTokenSilently, isLoading, isAuthenticated, error } = useAuth0();

  useEffect(() => {
    if (isAuthenticated) {
      setTokenGetter(() => getAccessTokenSilently());

      if (user?.sub) {
        Sentry.setUser({ id: user.sub, email: user.email });
      }

      // Eagerly fetch and cache token in localStorage so the Axios
      // interceptor has a synchronous fallback on page load.
      getAccessTokenSilently()
        .then((token) => localStorage.setItem('auth0_token', token))
        .catch(() => {});
    } else {
      setTokenGetter(null);
      Sentry.setUser(null);
    }
  }, [isAuthenticated, getAccessTokenSilently, user?.sub, user?.email]);

  const handleLogout = () => {
    setTokenGetter(null);
    localStorage.removeItem('auth0_token');
    Sentry.setUser(null);
    logout({
      logoutParams: {
        returnTo: window.location.origin,
      },
    });
  };

  return {
    user,
    logout: handleLogout,
    isLoading,
    isAuthenticated,
    error,
  };
};
