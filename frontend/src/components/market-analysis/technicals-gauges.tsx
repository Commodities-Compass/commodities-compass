import GaugeIndicator from '@/components/gauge-indicator';
import { Eyebrow } from '@/components/editorial';
import type { IndicatorsGridResponse } from '@/types/dashboard';
import { INDICATOR_KEYS, gridStyle5 } from './helpers';

interface TechnicalsGaugesProps {
  indicators?: IndicatorsGridResponse['indicators'];
}

export default function TechnicalsGauges({ indicators }: TechnicalsGaugesProps) {
  return (
    <div style={{ marginBottom: 28 }}>
      <Eyebrow as="div" tone="muted" size={10} style={{ marginBottom: 14, letterSpacing: '0.22em' }}>
        Technicals
      </Eyebrow>
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
            ) : null,
          )}
        </div>
      ) : (
        <p style={{ color: 'var(--ink-light)', fontSize: 14, textAlign: 'center' }}>
          Aucun indicateur disponible.
        </p>
      )}
    </div>
  );
}
