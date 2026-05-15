import { Loader2 } from 'lucide-react';
import { useWeather } from '@/hooks/useDashboard';
import type { LocationDiagnostic } from '@/types/dashboard';
import SectionHeader from '@/components/section-header';
import { Eyebrow } from '@/components/editorial';
import CampaignBlock from '@/components/weather/CampaignBlock';
import StressHistoryBlock from '@/components/weather/StressHistoryBlock';
import HarmattanBlock from '@/components/weather/HarmattanBlock';

interface WeatherUpdateCardProps {
  targetDate?: string;
  className?: string;
}

export default function WeatherUpdateCard({ targetDate, className }: WeatherUpdateCardProps) {
  const { data, isLoading, error } = useWeather(targetDate);

  if (isLoading) {
    return (
      <section className={className} style={{ padding: '24px 0' }}>
        <SectionHeader numeral="V" title="Weather Intelligence" />
        <div className="flex items-center justify-center py-12" style={{ color: 'var(--ink-light)' }}>
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          <span className="text-sm">Chargement du rapport météo...</span>
        </div>
      </section>
    );
  }

  if (error || !data) {
    return (
      <section className={className} style={{ padding: '24px 0' }}>
        <SectionHeader numeral="V" title="Weather Intelligence" />
        <p style={{ color: 'var(--ink-light)', textAlign: 'center', fontSize: 14 }}>
          Aucun rapport météo pour cette date.
        </p>
      </section>
    );
  }

  const diagnostics: LocationDiagnostic[] = data.daily_diagnostics ?? data.diagnostics ?? [];

  return (
    <section className={className} style={{ padding: '24px 0' }}>
      <SectionHeader numeral="V" title="Weather Intelligence" />

      {data.campaign && data.seasons && data.seasons.length > 0 && (
        <CampaignBlock
          campaign={data.campaign}
          campaignHealth={data.campaign_health}
          seasons={data.seasons}
        />
      )}

      {data.stress_history && data.stress_history.length > 0 && (
        <StressHistoryBlock history={data.stress_history} />
      )}

      <HarmattanBlock harmattan={data.harmattan} diagnostics={diagnostics} />

      {data.description && (
        <div
          style={{
            padding: '16px 18px',
            background: 'var(--paper-off)',
            borderLeft: '3px solid var(--ink)',
          }}
        >
          <Eyebrow as="div" tracking="0.2em" style={{ marginBottom: 8 }}>
            Bulletin du jour
          </Eyebrow>
          {data.description
            .split(/\n{2,}/)
            .map((s) => s.trim())
            .filter(Boolean)
            .map((p, i) => (
              <p
                key={i}
                style={{
                  fontFamily: 'var(--font-editorial)',
                  fontSize: 14,
                  lineHeight: 1.65,
                  color: 'var(--ink-dark)',
                  marginBottom: 10,
                }}
              >
                {p}
              </p>
            ))}
        </div>
      )}
    </section>
  );
}
