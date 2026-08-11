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
}

export const authApi = {
  getMe: async (): Promise<MeResponse> => {
    const res = await apiClient.get<MeResponse>('/auth/me');
    return res.data;
  },
};
