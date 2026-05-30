import { createContext, useState, useMemo, useCallback } from 'react';
import type { ReactNode } from 'react';
import { usePositionStatus, useNonTradingDays } from '@/hooks/useDashboard';

export interface DashboardDateContextValue {
  /** Date sent to backend queries (resolves to a real trading session). */
  currentDate: string;
  /**
   * Date displayed on the calendar trigger / popover.
   * - Refresh today = today's calendar date (Friday 29, Saturday 30, etc.)
   * - User pick = the picked date
   * Visually decoupled from `currentDate` so the dashboard can display the
   * last fully-complete session (e.g. Thursday) while the calendar pill
   * still reads today's date (e.g. Saturday).
   */
  calendarDate: string;
  setCurrentDate: (date: string) => void;
  sessionDate: string | null;
}

export const DashboardDateContext = createContext<DashboardDateContextValue | null>(null);

const todayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export function DashboardDateProvider({ children }: { children: ReactNode }) {
  const [userPickedDate, setUserPickedDate] = useState<string | null>(null);
  const today = todayISO();
  const currentYear = new Date().getFullYear();
  const { data: nonTradingDays } = useNonTradingDays(currentYear);
  const latestTradingDay = nonTradingDays?.latest_trading_day;

  // currentDate (API): user pick > backend latest_trading_day > today.
  //   Backend `latest_trading_day` = MAX(pl_contract_data_daily.display_date)
  //   WHERE display_date <= today. On weekends this resolves to the previous
  //   trading day's display_date, so the dashboard reads the last fully-
  //   complete session (Thursday) — Friday's row is "Phase A only" through
  //   the weekend (Phase B fires Sunday eve and only THEN completes Friday).
  //
  // calendarDate (visual): user pick > today.
  //   The calendar pill always tracks the real-world calendar date.
  //   Diverges from currentDate on weekends/holidays, when the dashboard
  //   shows older data than today.
  const currentDate = userPickedDate ?? latestTradingDay ?? today;
  const calendarDate = userPickedDate ?? today;

  const setCurrentDate = useCallback((date: string) => {
    setUserPickedDate(date);
  }, []);

  const { data: positionData } = usePositionStatus(currentDate);
  const sessionDate = positionData?.date ?? null;

  const value = useMemo(
    () => ({ currentDate, calendarDate, setCurrentDate, sessionDate }),
    [currentDate, calendarDate, sessionDate, setCurrentDate],
  );

  return <DashboardDateContext.Provider value={value}>{children}</DashboardDateContext.Provider>;
}
