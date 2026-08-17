import { apiClient } from './client';
import type {
  OriginCampaignResponse,
  OriginMarketViewsResponse,
} from '@/types/origin';

/**
 * Origin flow endpoints (matrix block ②).
 *
 * Two calls rather than one because the two rows carry different entitlement
 * keys and the backend gate is per-endpoint. Coop Essentiel reaches `campaign`
 * and gets 403 on `market-views`, so a single combined call would have to be
 * filtered field-by-field server-side — machinery that does not exist.
 *
 * `season` and `month` are omitted when undefined so the backend applies its own
 * default (newest season, newest month with exports).
 */
export const originApi = {
  getCampaign: async (
    season?: string,
    month?: string
  ): Promise<OriginCampaignResponse> => {
    const response = await apiClient.get<OriginCampaignResponse>(
      '/dashboard/origin/campaign',
      { params: { ...(season && { season }), ...(month && { month }) } }
    );
    return response.data;
  },

  getMarketViews: async (
    season?: string
  ): Promise<OriginMarketViewsResponse> => {
    const response = await apiClient.get<OriginMarketViewsResponse>(
      '/dashboard/origin/market-views',
      { params: { ...(season && { season }) } }
    );
    return response.data;
  },
};
