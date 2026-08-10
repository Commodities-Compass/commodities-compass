import type { CSSProperties, ReactNode } from 'react';
import { Eyebrow, DataValue } from '@/components/editorial';

export interface SocleEntry {
  label: string;
  value: ReactNode;
  /** Dimmed value — used for release dates, which are context, not readings. */
  muted?: boolean;
}

interface SocleProps {
  /** Label/value pairs. Mutually exclusive with `children`. */
  entries?: SocleEntry[];
  /** Free prose (methodology note, disclaimer). Mutually exclusive with `entries`. */
  children?: ReactNode;
}

const band: CSSProperties = {
  marginTop: 'var(--sp-5)',
  paddingTop: 'var(--sp-3)',
  borderTop: '1px dotted var(--rule)',
  display: 'flex',
  flexWrap: 'wrap',
  alignItems: 'baseline',
  columnGap: 24,
  rowGap: 8,
};

const cell: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'baseline',
  gap: 8,
  whiteSpace: 'nowrap',
};

/**
 * Second band of a rail panel — the socle.
 *
 * Every stratum panel is exactly two bands: the gauge/tile field, then this.
 * It carries provenance (where the numbers came from) or supplementary context,
 * and in doing so absorbs the height variance between strata — which is what
 * keeps the rail from reserving a tall track for one heavy panel.
 *
 * It must never be filled with invented content to even out heights: a stratum
 * with nothing true to say here should render no socle and simply be shorter.
 */
export default function Socle({ entries, children }: SocleProps) {
  if (entries && entries.length > 0) {
    return (
      <div style={band}>
        {entries.map((entry) => (
          <span key={entry.label} style={cell}>
            <Eyebrow tone="subtle" size={9}>
              {entry.label}
            </Eyebrow>
            <DataValue
              size={11}
              color={entry.muted ? 'var(--ink-mid)' : 'var(--ink)'}
            >
              {entry.value}
            </DataValue>
          </span>
        ))}
      </div>
    );
  }

  if (!children) return null;

  return (
    <div style={band}>
      <Eyebrow tone="subtle" size={9}>
        {children}
      </Eyebrow>
    </div>
  );
}
