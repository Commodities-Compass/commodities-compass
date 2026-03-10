import { useAuth0 } from '@auth0/auth0-react';
import { useLayoutEffect } from 'react';
import { setTokenGetter } from '@/api/client';

export const useAuth = () => {
  const { user, logout, getAccessTokenSilently, isLoading, isAuthenticated, error } = useAuth0();

  // useLayoutEffect runs before ALL regular useEffects (including React Query's
  // queryFn). This prevents a race condition where child component effects
  // (dashboard API calls) fire before tokenGetter is set.
  useLayoutEffect(() => {
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
