import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useWeather } from '@/hooks/useDashboard';
import SectionHeader from '@/components/section-header';
import { Eyebrow } from '@/components/editorial';
import CampaignBlock from '@/components/weather/CampaignBlock';
import StressHistoryBlock from '@/components/weather/StressHistoryBlock';

interface WeatherUpdateCardProps {
  targetDate?: string;
  className?: string;
  /** "résumé hebdo" tier: show the weekly campaign block only, hide daily detail. */
  summary?: boolean;
}

export default function WeatherUpdateCard({
  targetDate,
  className,
  summary = false,
}: WeatherUpdateCardProps) {
  const { t } = useTranslation();
  const { data, isLoading, error } = useWeather(targetDate);

  if (isLoading) {
    return (
      <section className={className} style={{ padding: '24px 0' }}>
        <SectionHeader numeral="V" title={t('sections.weather')} />
        <div className="flex items-center justify-center py-12" style={{ color: 'var(--ink-light)' }}>
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          <span className="text-sm">{t('loading.weather_report')}</span>
        </div>
      </section>
    );
  }

  if (error || !data) {
    return (
      <section className={className} style={{ padding: '24px 0' }}>
        <SectionHeader numeral="V" title={t('sections.weather')} />
        <p style={{ color: 'var(--ink-light)', textAlign: 'center', fontSize: 14 }}>
          {t('weather.empty_state')}
        </p>
      </section>
    );
  }

  const harmattanByLocation: Record<string, number | null> = Object.fromEntries(
    (data.diagnostics ?? []).map((d) => [d.location_name, d.harmattan_days ?? null]),
  );

  return (
    <section className={className} style={{ padding: '24px 0' }}>
      <SectionHeader numeral="V" title={t('sections.weather')} />

      {summary && (
        <Eyebrow as="div" tone="subtle" tracking="0.2em" style={{ marginBottom: 12 }}>
          {t('weather.weekly_summary_label', 'Résumé hebdomadaire')}
        </Eyebrow>
      )}

      {data.campaign && data.seasons && data.seasons.length > 0 && (
        <CampaignBlock
          campaign={data.campaign}
          campaignHealth={data.campaign_health}
          seasons={data.seasons}
        />
      )}

      {!summary && data.stress_history && data.stress_history.length > 0 && (
        <StressHistoryBlock
          history={data.stress_history}
          harmattanByLocation={harmattanByLocation}
        />
      )}

      {/* Always visible. The toggle moved to the 7-day stress table, which is
          the block worth folding away — this bulletin is three sentences. */}
      {!summary && data.description && (
        <div
          style={{
            padding: '16px 18px',
            background: 'var(--paper-off)',
            borderLeft: '3px solid var(--ink)',
          }}
        >
          <Eyebrow as="div" tracking="0.2em" style={{ marginBottom: 2 }}>
            {t('weather.daily_bulletin_title')}
          </Eyebrow>
          <Eyebrow as="div" tone="subtle" size={9} tracking="0.18em">
            {t('weather.horizon_subtitle')}
          </Eyebrow>

          <div style={{ marginTop: 12 }}>
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
        </div>
      )}

    </section>
  );
}
