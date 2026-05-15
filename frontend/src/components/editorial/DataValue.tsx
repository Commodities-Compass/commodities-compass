import type { CSSProperties, ReactNode } from 'react';

interface DataValueProps {
  children: ReactNode;
  /** Color override (e.g. signal-open for positive deltas). Defaults to ink. */
  color?: string;
  /** Font size in px. Defaults to 11. */
  size?: 10 | 11 | 12 | 13 | 14;
  /** Font weight. Defaults to 600. */
  weight?: 500 | 600 | 700;
  className?: string;
  style?: CSSProperties;
}

/**
 * Editorial data value — mono tabular numerals, used for ticker numbers,
 * scores, prices, and any other numeric data. Replaces the repeated
 * `fontFamily: mono, tabular-nums` inline pattern.
 */
export default function DataValue({
  children,
  color = 'var(--ink)',
  size = 11,
  weight = 600,
  className,
  style,
}: DataValueProps) {
  return (
    <span
      className={`tabular-nums ${className ?? ''}`.trim()}
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: size,
        fontWeight: weight,
        color,
        letterSpacing: '0.05em',
        ...style,
      }}
    >
      {children}
    </span>
  );
}
