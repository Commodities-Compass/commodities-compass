import { useAuth0 } from '@auth0/auth0-react';
import { useEffect } from 'react';
import { setTokenGetter } from '@/api/client';

export const useAuth = () => {
  const { user, logout, getAccessTokenSilently, isLoading, isAuthenticated, error } = useAuth0();

  useEffect(() => {
    if (isAuthenticated) {
      setTokenGetter(() => getAccessTokenSilently());
    } else {
      setTokenGetter(null);
    }
  }, [isAuthenticated, getAccessTokenSilently]);

  const handleLogout = () => {
    setTokenGetter(null);
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
