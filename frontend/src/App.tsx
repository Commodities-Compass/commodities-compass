import React, { useEffect, useRef, Suspense } from 'react';
import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
} from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import { useAuth } from '@/hooks/useAuth';
import LoadingSpinner from '@/components/LoadingSpinner';

const DashboardLayout = React.lazy(() => import('@/components/dashboard-layout'));
const LoginPage = React.lazy(() => import('@/pages/login-page-auth0'));
const DashboardPage = React.lazy(() => import('@/pages/dashboard-page'));
const HistoricalPage = React.lazy(() => import('@/pages/historical-page'));

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

function NotFoundPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="text-center space-y-4 p-8">
        <h1 className="text-4xl font-bold text-foreground">404</h1>
        <p className="text-muted-foreground">Page not found</p>
        <a
          href="/dashboard"
          className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Go to Dashboard
        </a>
      </div>
    </div>
  );
}

export default function App() {
  const { isAuthenticated, logout } = useAuth0();
  const logoutInProgressRef = useRef(false);

  // Initialize token getter via useAuth hook
  useAuth();

  // Listen for 401 errors from API calls and trigger logout
  useEffect(() => {
    const handleTokenExpired = () => {
      if (isAuthenticated && !logoutInProgressRef.current) {
        logoutInProgressRef.current = true;
        logout({
          logoutParams: {
            returnTo: window.location.origin + '/login',
          },
        });
      }
    };

    window.addEventListener('auth:token-expired', handleTokenExpired);
    return () => {
      window.removeEventListener('auth:token-expired', handleTokenExpired);
    };
  }, [isAuthenticated, logout]);

  // Reset logout flag when auth state changes
  useEffect(() => {
    if (!isAuthenticated) {
      logoutInProgressRef.current = false;
    }
  }, [isAuthenticated]);

  return (
    <Router>
      <Suspense fallback={<LoadingSpinner />}>
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

          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </Router>
  );
}
