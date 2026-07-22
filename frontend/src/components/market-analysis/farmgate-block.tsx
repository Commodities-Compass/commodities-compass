import { Eyebrow } from '@/components/editorial';
import type {
  FarmgatePriceEntry,
  FarmgatePriceResponse,
} from '@/types/dashboard';
import { fmtDate } from './helpers';

interface FarmgateBlockProps {
  farmgate?: FarmgatePriceResponse;
}

const REGION_LABEL: Record<string, string> = {
  civ: 'Côte d’Ivoire',
  ghana: 'Ghana',
};

const CURRENCY_LABEL: Record<string, string> = {
  XOF: 'FCFA',
  GHS: 'GHS',
};

const UNIT_LABEL: Record<string, string> = {
  per_kg: '/kg',
  per_bag_64kg: '/sac 64 kg',
  per_tonne: '/t',
};

function formatPrice(entry: FarmgatePriceEntry): string {
  const value = new Intl.NumberFormat('fr-FR', {
    maximumFractionDigits: 0,
  }).format(entry.price_native);
  const currency = CURRENCY_LABEL[entry.currency] ?? entry.currency;
  const unit = UNIT_LABEL[entry.unit] ?? '';
  return `${value} ${currency}${unit}`;
}

function Tile({
  region,
  entry,
}: {
  region: string;
  entry: FarmgatePriceEntry | null;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <Eyebrow tone="subtle" size={9}>
        {REGION_LABEL[region] ?? region}
      </Eyebrow>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 20,
          fontWeight: 600,
          color: 'var(--ink)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {entry ? formatPrice(entry) : '—'}
      </span>
      {entry ? (
        <Eyebrow tone="subtle" size={9}>
          Campagne {entry.season_label} · en vigueur{' '}
          {fmtDate(entry.effective_date)}
        </Eyebrow>
      ) : (
        <Eyebrow tone="subtle" size={9}>
          Non annoncé
        </Eyebrow>
      )}
    </div>
  );
}

export default function FarmgateBlock({ farmgate }: FarmgateBlockProps) {
  if (!farmgate || (!farmgate.civ && !farmgate.ghana)) return null;

  return (
    <div style={{ marginBottom: 28 }}>
      <Eyebrow
        as="div"
        tone="muted"
        size={10}
        style={{ marginBottom: 14, letterSpacing: '0.22em' }}
      >
        Prix garanti officiel
      </Eyebrow>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
          gap: 24,
          alignItems: 'start',
        }}
      >
        <Tile region="civ" entry={farmgate.civ} />
        <Tile region="ghana" entry={farmgate.ghana} />
      </div>
      <div style={{ marginTop: 8 }}>
        <Eyebrow tone="subtle" size={9}>
          Prix officiel garanti (CCC / COCOBOD) — distinct du prix réel terrain
        </Eyebrow>
      </div>
    </div>
  );
}
