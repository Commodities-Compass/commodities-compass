import { useTranslation } from 'react-i18next';
import GaugeIndicator from '@/components/gauge-indicator';
import Socle, { type SocleEntry } from './socle';
import type { IndicatorsGridResponse } from '@/types/dashboard';
import { INDICATOR_KEYS, gridStyle } from './helpers';

interface TechnicalsGaugesProps {
  indicators?: IndicatorsGridResponse['indicators'];
  /** Front-month contract for the requested date, e.g. "CAU26". */
  contractCode?: string | null;
  /** Session date of the indicators (ISO string from the API). */
  sessionDate?: string | null;
}

export default function TechnicalsGauges({
  indicators,
  contractCode,
  sessionDate,
}: TechnicalsGaugesProps) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language?.startsWith('en') ? 'en' : 'fr';

  const available = indicators
    ? INDICATOR_KEYS.filter((key) => indicators[key])
    : [];

  // Provenance only — never padding. If neither field resolved, the panel
  // renders without a socle and is simply shorter than its neighbours.
  const entries: SocleEntry[] = [];
  if (contractCode) {
    entries.push({ label: t('market.socle_contract'), value: contractCode });
  }
  if (sessionDate) {
    const parsed = new Date(sessionDate);
    if (!Number.isNaN(parsed.getTime())) {
      entries.push({
        label: t('market.socle_session'),
        value: new Intl.DateTimeFormat(lang, {
          day: 'numeric',
          month: 'short',
          year: 'numeric',
        }).format(parsed),
        muted: true,
      });
    }
  }

  return (
    <div>
      {available.length > 0 ? (
        <div className="gauges-row" style={gridStyle(available.length)}>
          {available.map((key) => (
            <GaugeIndicator
              key={key}
              value={indicators![key].value}
              min={indicators![key].min}
              max={indicators![key].max}
              label={indicators![key].label}
              ranges={indicators![key].ranges}
            />
          ))}
        </div>
      ) : (
        <p
          style={{
            color: 'var(--ink-light)',
            fontSize: 14,
            textAlign: 'center',
          }}
        >
          {t('market.no_indicators')}
        </p>
      )}
      <Socle entries={entries} />
    </div>
  );
}
