import { useEffect, useRef } from 'react';
import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
} from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import DashboardLayout from '@/components/dashboard-layout';
import LoginPage from '@/pages/login-page-auth0';
import DashboardPage from '@/pages/dashboard-page';
import HistoricalPage from '@/pages/historical-page';
import LoadingSpinner from '@/components/LoadingSpinner';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth0();

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}

export default function App() {
  const { isAuthenticated, getAccessTokenSilently, logout } = useAuth0();
  const tokenRefreshAttemptedRef = useRef(false);
  const logoutInProgressRef = useRef(false);

  // Listen for 401 errors from API calls and trigger logout
  useEffect(() => {
    const handleTokenExpired = () => {
      if (isAuthenticated && !logoutInProgressRef.current) {
        console.warn('Token expired detected - logging out');
        logoutInProgressRef.current = true;

        logout({
          logoutParams: {
            returnTo: window.location.origin + '/login'
          }
        });
      }
    };

    window.addEventListener('auth:token-expired', handleTokenExpired);
    return () => {
      window.removeEventListener('auth:token-expired', handleTokenExpired);
    };
  }, [isAuthenticated, logout]);

  useEffect(() => {
    const getToken = async () => {
      // Only try to refresh token once to prevent infinite loops
      if (isAuthenticated && !tokenRefreshAttemptedRef.current) {
        tokenRefreshAttemptedRef.current = true;

        try {
          const token = await getAccessTokenSilently();
          localStorage.setItem('auth0_token', token);
          // Clear any previous 401 error flags on successful token refresh
          sessionStorage.removeItem('auth_401_error');
        } catch (error) {
          console.error('Error getting access token:', error);

          // Clear stored token
          localStorage.removeItem('auth0_token');

          // Properly logout from Auth0 to clear session state
          // This breaks the redirect loop by setting isAuthenticated to false
          if (!logoutInProgressRef.current) {
            logoutInProgressRef.current = true;
            logout({
              logoutParams: {
                returnTo: window.location.origin + '/login'
              }
            });
          }
        }
      }
    };

    getToken();

    // Reset the flags when authentication state changes
    if (!isAuthenticated) {
      tokenRefreshAttemptedRef.current = false;
      logoutInProgressRef.current = false;
    }
  }, [isAuthenticated, getAccessTokenSilently, logout]);

  return (
    <Router>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />

        <Route path="/login" element={<LoginPage />} />

        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <DashboardLayout>
                <DashboardPage />
              </DashboardLayout>
            </ProtectedRoute>
          }
        />

        <Route
          path="/dashboard/historical"
          element={
            <ProtectedRoute>
              <DashboardLayout>
                <HistoricalPage />
              </DashboardLayout>
            </ProtectedRoute>
          }
        />
      </Routes>
    </Router>
  );
}
