import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuth0 } from '@auth0/auth0-react';
import { authApi } from '@/api/auth';

/**
 * Per-client entitlement context. Fetches /auth/me once and exposes membership
 * checks used to show/hide dashboard sections.
 *
 * Crucial: gating is active ONLY when the backend reports `enforced=true`. In
 * dark mode (default) `has`/`hasAny` return true for everything, so the UI is
 * unchanged and un-seeded/legacy users never see a blanked dashboard. The
 * frontend hide is cosmetic — the backend 403 is the real boundary.
 */
interface EntitlementsValue {
  enforced: boolean;
  entitlements: Set<string>;
  tier: string | null;
  /**
   * Payment state, orthogonal to `entitlements`. Deliberately NOT folded into
   * `has`/`hasAny`: a `past_due` account keeps its full key set on purpose (the
   * Stripe retry window keeps access open), so the banner — not the gating — is
   * what surfaces it. The backend is the real boundary either way.
   */
  billingStatus: string | null;
  isLoading: boolean;
  has: (key: string) => boolean;
  hasAny: (keys: string[]) => boolean;
}

const OPEN: EntitlementsValue = {
  enforced: false,
  entitlements: new Set(),
  tier: null,
  billingStatus: null,
  isLoading: false,
  has: () => true,
  hasAny: () => true,
};

const EntitlementsContext = createContext<EntitlementsValue | null>(null);

export function EntitlementsProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth0();
  const { data, isLoading } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: authApi.getMe,
    enabled: isAuthenticated,
    staleTime: 10 * 60 * 1000, // matches the backend principal cache TTL
  });

  const value = useMemo<EntitlementsValue>(() => {
    const enforced = data?.enforced ?? false;
    const entitlements = new Set(data?.entitlements ?? []);
    return {
      enforced,
      entitlements,
      tier: data?.tier ?? null,
      billingStatus: data?.billing_status ?? null,
      isLoading,
      has: (key: string) => !enforced || entitlements.has(key),
      hasAny: (keys: string[]) => !enforced || keys.some((k) => entitlements.has(k)),
    };
  }, [data, isLoading]);

  return (
    <EntitlementsContext.Provider value={value}>{children}</EntitlementsContext.Provider>
  );
}

export function useEntitlements(): EntitlementsValue {
  // Outside the provider → open (show everything). Never throws.
  return useContext(EntitlementsContext) ?? OPEN;
}

/** Renders children only if the principal holds at least one of `anyOf`. */
export function Entitled({ anyOf, children }: { anyOf: string[]; children: ReactNode }) {
  const { hasAny } = useEntitlements();
  return hasAny(anyOf) ? <>{children}</> : null;
}
