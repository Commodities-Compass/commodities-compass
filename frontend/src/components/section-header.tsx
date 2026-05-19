interface SectionHeaderProps {
  numeral: string;
  title: string;
  className?: string;
}

/**
 * Editorial section header — title in Inter sans uppercase (the "structural"
 * voice of the magazine), numeral in Playfair light gray (decorative).
 * Tab labels (rendered via EditorialTabs) use the Playfair italic voice.
 */
export default function SectionHeader({ numeral, title, className }: SectionHeaderProps) {
  return (
    <div
      className={`flex items-baseline gap-4 mb-6 ${className ?? ''}`.trim()}
      style={{ borderBottom: '1px solid var(--ink)', paddingBottom: 12 }}
    >
      <span
        style={{
          fontFamily: 'var(--font-display)',
          fontWeight: 300,
          fontSize: 32,
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
          fontSize: 14,
          color: 'var(--ink)',
          letterSpacing: '0.22em',
          lineHeight: 1.2,
          margin: 0,
        }}
      >
        {title}
      </h2>
      <span aria-hidden className="flex-1 h-px" style={{ background: 'var(--rule)' }} />
    </div>
  );
}
