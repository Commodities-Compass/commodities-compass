import type { CSSProperties, ReactNode } from 'react';

interface EyebrowProps {
  children: ReactNode;
  /** Visual emphasis. `primary` = ink, `muted` = ink-mid (default), `subtle` = ink-light. */
  tone?: 'primary' | 'muted' | 'subtle';
  /** Font size in px. Defaults to 10. */
  size?: 9 | 10 | 11;
  /** Letter-spacing override. Defaults to 0.18em. */
  tracking?: string;
  className?: string;
  style?: CSSProperties;
  as?: 'span' | 'div' | 'h3' | 'p';
}

const TONE_COLOR = {
  primary: 'var(--ink)',
  muted: 'var(--ink-mid)',
  subtle: 'var(--ink-light)',
} as const;

/**
 * Editorial eyebrow / kicker — mono uppercase label.
 * Replaces the repeated inline mono-uppercase block used as eyebrows,
 * sub-headers, data labels, and kickers throughout the magazine.
 */
export default function Eyebrow({
  children,
  tone = 'muted',
  size = 10,
  tracking = '0.18em',
  className,
  style,
  as: Tag = 'span',
}: EyebrowProps) {
  return (
    <Tag
      className={`uppercase ${className ?? ''}`.trim()}
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: size,
        fontWeight: 600,
        letterSpacing: tracking,
        color: TONE_COLOR[tone],
        ...style,
      }}
    >
      {children}
    </Tag>
  );
}
