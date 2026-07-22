import { useTranslation } from 'react-i18next';
import GaugeIndicator from '@/components/gauge-indicator';
import GroupHeader from './group-header';
import type { IndicatorsGridResponse } from '@/types/dashboard';
import { INDICATOR_KEYS, gridStyle5 } from './helpers';

interface TechnicalsGaugesProps {
  indicators?: IndicatorsGridResponse['indicators'];
}

export default function TechnicalsGauges({
  indicators,
}: TechnicalsGaugesProps) {
  const { t } = useTranslation();
  return (
    <div style={{ marginBottom: 28 }}>
      <GroupHeader
        name={t('market.grp_technicals')}
        cadence={t('market.cad_daily')}
      />
      {indicators ? (
        <div className="gauges-row" style={gridStyle5}>
          {INDICATOR_KEYS.map((key) =>
            indicators[key] ? (
              <GaugeIndicator
                key={key}
                value={indicators[key].value}
                min={indicators[key].min}
                max={indicators[key].max}
                label={indicators[key].label}
                ranges={indicators[key].ranges}
              />
            ) : null
          )}
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
    </div>
  );
}
