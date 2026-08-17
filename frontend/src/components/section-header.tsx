import type { ReactNode } from 'react';
interface SectionHeaderProps {
  numeral: string;
  title: string;
  /**
   * Optional control anchored to the right of the rule — for a section that owns
   * its own period, like VI. Sections I-V pass nothing and are unchanged.
   */
  aside?: ReactNode;
  className?: string;
}

/**
 * Editorial section header — title in Inter sans uppercase (the "structural"
 * voice of the magazine), numeral in Playfair light gray (decorative).
 * Tab labels (rendered via EditorialTabs) use the Playfair italic voice.
 */
export default function SectionHeader({
  numeral,
  title,
  aside,
  className,
}: SectionHeaderProps) {
  return (
    <div
      className={`flex items-baseline gap-4 mb-6 ${className ?? ''}`.trim()}
      style={{ borderBottom: '1px solid var(--ink)', paddingBottom: 12 }}
    >
      <span
        style={{
          fontFamily: 'var(--font-display)',
          fontWeight: 300,
          fontSize: 'clamp(22px, 4vw, 32px)',
          color: 'var(--ink-light)',
          letterSpacing: '0.04em',
          lineHeight: 1,
        }}
      >
        {numeral}
      </span>
      <h2
        className="uppercase"
        style={{
          fontFamily: 'var(--font-sans)',
          fontWeight: 700,
          fontSize: 'clamp(12px, 1.4vw, 14px)',
          color: 'var(--ink)',
          letterSpacing: '0.22em',
          lineHeight: 1.2,
          margin: 0,
        }}
      >
        {title}
      </h2>
      <span aria-hidden className="flex-1 h-px" style={{ background: 'var(--rule)' }} />
      {aside}
    </div>
  );
}
