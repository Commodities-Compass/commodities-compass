import { Eyebrow } from '@/components/editorial';

interface GroupHeaderProps {
  name: string;
  cadence: string;
}

/** Group label with its data cadence — encodes the section's fast→slow order. */
export default function GroupHeader({ name, cadence }: GroupHeaderProps) {
  return (
    <Eyebrow
      as="div"
      tone="muted"
      size={10}
      style={{ marginBottom: 14, letterSpacing: '0.22em' }}
    >
      {name} <span style={{ color: 'var(--ink-light)' }}>· {cadence}</span>
    </Eyebrow>
  );
}
