import { useQuery } from '@tanstack/react-query';
import { originApi } from '@/api/origin';
import type {
  OriginCampaignResponse,
  OriginMarketViewsResponse,
} from '@/types/origin';

/**
 * Origin flow hooks — matrix block ②.
 *
 * Same 24 h posture as the rest of the dashboard, and here it is not even a
 * compromise: origin data is loaded **manually, once a month** by an operator
 * running `watchai-sync`. There is nothing to refetch for.
 *
 * The query key carries the season, not a date. Section VI has its own period
 * selector and is deliberately NOT wired to `DashboardDateContext` — folding a
 * monthly dimension into the daily one is the collision the timeseries-uniqueness
 * rule exists to prevent, and it would also refetch this data every time the user
 * moved the daily date picker.
 */
const MONTHLY_QUERY_OPTIONS = {
  staleTime: 24 * 60 * 60 * 1000,
  refetchInterval: false as const,
  refetchOnWindowFocus: false,
  refetchOnMount: false,
};

export const useOriginCampaign = (season?: string, month?: string) => {
  return useQuery<OriginCampaignResponse>({
    queryKey: ['origin-campaign', season, month],
    queryFn: () => originApi.getCampaign(season, month),
    ...MONTHLY_QUERY_OPTIONS,
  });
};

export const useOriginMarketViews = (season?: string, enabled = true) => {
  return useQuery<OriginMarketViewsResponse>({
    queryKey: ['origin-market-views', season],
    queryFn: () => originApi.getMarketViews(season),
    // Skipped for tiers without `read:watchai:market_views` — firing it would
    // guarantee a 403 and a red line in the console for a section that is simply
    // not sold to them.
    enabled,
    ...MONTHLY_QUERY_OPTIONS,
  });
};
