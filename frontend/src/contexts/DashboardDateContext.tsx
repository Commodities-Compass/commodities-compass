import { createContext, useState, useMemo, useCallback } from 'react';
import type { ReactNode } from 'react';
import { usePositionStatus, useNonTradingDays } from '@/hooks/useDashboard';

export interface DashboardDateContextValue {
  currentDate: string;
  setCurrentDate: (date: string) => void;
  sessionDate: string | null;
}

export const DashboardDateContext = createContext<DashboardDateContextValue | null>(null);

const todayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export function DashboardDateProvider({ children }: { children: ReactNode }) {
  // Default date derivation, in priority order:
  //   1. User pick (calendar) — wins as soon as set
  //   2. Backend's `latest_trading_day` — MAX(pl_contract_data_daily.display_date)
  //      WHERE display_date <= today. On Saturday/Sunday this is the previous
  //      trading day's display_date, so the dashboard lands on the last
  //      fully-complete session (e.g. Saturday morning → Thursday's session
  //      under the "Vendredi 29 mai" label) instead of the just-closed-but-
  //      partial session whose Phase B narrative will only arrive Sunday eve.
  //   3. Today (synchronous fallback before the endpoint resolves, or if it
  //      fails).
  const [userPickedDate, setUserPickedDate] = useState<string | null>(null);
  const currentYear = new Date().getFullYear();
  const { data: nonTradingDays } = useNonTradingDays(currentYear);

  const currentDate =
    userPickedDate ?? nonTradingDays?.latest_trading_day ?? todayISO();

  const setCurrentDate = useCallback((date: string) => {
    setUserPickedDate(date);
  }, []);

  const { data: positionData } = usePositionStatus(currentDate);
  const sessionDate = positionData?.date ?? null;

  const value = useMemo(
    () => ({ currentDate, setCurrentDate, sessionDate }),
    [currentDate, sessionDate, setCurrentDate],
  );

  return <DashboardDateContext.Provider value={value}>{children}</DashboardDateContext.Provider>;
}
