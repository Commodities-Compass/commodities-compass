import { createContext, useState, useMemo } from 'react';
import type { ReactNode } from 'react';
import { usePositionStatus } from '@/hooks/useDashboard';

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
  const [currentDate, setCurrentDate] = useState(todayISO);
  const { data: positionData } = usePositionStatus(currentDate);
  const sessionDate = positionData?.date ?? null;

  const value = useMemo(
    () => ({ currentDate, setCurrentDate, sessionDate }),
    [currentDate, sessionDate],
  );

  return <DashboardDateContext.Provider value={value}>{children}</DashboardDateContext.Provider>;
}
