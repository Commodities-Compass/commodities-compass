import type { HarmattanStatus, LocationDiagnostic } from '@/types/dashboard';
import { Eyebrow } from '@/components/editorial';

interface HarmattanBlockProps {
  harmattan?: HarmattanStatus | null;
  diagnostics: LocationDiagnostic[];
}

export default function HarmattanBlock({ harmattan, diagnostics }: HarmattanBlockProps) {
  const affected = diagnostics.filter((d) => d.harmattan_days != null && d.harmattan_days > 0);
  if (!harmattan?.in_season && affected.length === 0) return null;

  const color = harmattan?.risk ? 'var(--color-signal-hedge)' : 'var(--ink)';

  return (
    <div style={{ marginBottom: 24 }}>
      <div className="flex items-baseline justify-between mb-3">
        <Eyebrow as="h3" tone="primary" size={11} tracking="0.18em">
          Harmattan
        </Eyebrow>
        <Eyebrow tone="subtle" size={9} tracking="0.15em">
          Seuil critique {harmattan?.threshold ?? 24}j
        </Eyebrow>
      </div>

      <div className="flex items-center gap-3 mb-2">
        <Eyebrow
          size={10}
          tracking="0.18em"
          style={{
            padding: '4px 10px',
            border: `1px solid ${color}`,
            color,
          }}
        >
          {harmattan?.risk ? '— Risk' : '— Active'}
        </Eyebrow>
        {harmattan && (
          <span
            className="tabular-nums"
            style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ink-mid)' }}
          >
            {harmattan.days} jours cumulés
          </span>
        )}
      </div>

      {affected.length > 0 && (
        <p
          style={{
            fontFamily: 'var(--font-editorial)',
            fontStyle: 'italic',
            fontSize: 13,
            color: 'var(--ink-dark)',
            lineHeight: 1.5,
          }}
        >
          Sites affectés :{' '}
          {affected.map((d) => `${d.location_name} (${d.harmattan_days}j)`).join(' · ')}
        </p>
      )}
    </div>
  );
}
