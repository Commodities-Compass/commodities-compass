import { apiClient } from './client';

export interface MeResponse {
  sub: string | null;
  email: string | null;
  name: string | null;
  permissions: string[];
  tier: string | null;
  account_code: string | null;
  entitlements: string[];
  /** When false (dark mode), the UI shows everything regardless of entitlements. */
  enforced: boolean;
  /**
   * Payment state: trialing|active|past_due|unpaid|canceled|manual.
   * Orthogonal to `entitlements` — a `past_due` account keeps its FULL key set
   * (the Stripe retry window keeps access open), so this banner is the only
   * signal the client gets before the retries are exhausted.
   */
  billing_status: string | null;
}

export interface PortalSessionResponse {
  url: string;
}

export const authApi = {
  getMe: async (): Promise<MeResponse> => {
    const res = await apiClient.get<MeResponse>('/auth/me');
    return res.data;
  },

  /** Stripe Customer Portal URL — where a client fixes a failed card. */
  createPortalSession: async (): Promise<PortalSessionResponse> => {
    const res = await apiClient.post<PortalSessionResponse>('/billing/portal-session');
    return res.data;
  },
};
