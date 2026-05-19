/**
 * Editorial dot separator — small `rule`-colored circle used between ticker
 * cells and inline metadata. Replaces the inline 4px dot pattern.
 */
export default function DotSeparator({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={className}
      style={{
        display: 'inline-block',
        width: 4,
        height: 4,
        borderRadius: '50%',
        background: 'var(--rule)',
        verticalAlign: 'middle',
        flexShrink: 0,
      }}
    />
  );
}
