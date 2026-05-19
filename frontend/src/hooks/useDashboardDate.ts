import { useContext } from 'react';
import {
  DashboardDateContext,
  type DashboardDateContextValue,
} from '@/contexts/DashboardDateContext';

export function useDashboardDate(): DashboardDateContextValue {
  const ctx = useContext(DashboardDateContext);
  if (!ctx) {
    throw new Error('useDashboardDate must be used within DashboardDateProvider');
  }
  return ctx;
}
