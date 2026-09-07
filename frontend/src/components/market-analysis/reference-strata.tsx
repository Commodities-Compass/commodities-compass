import type { CSSProperties, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useIsTouch } from '@/hooks/useIsTouch';
import Socle from './socle';
import { hasFarmgateData } from './helpers';
import type {
  FarmgateEquivEntry,
  FarmgatePriceEntry,
  FarmgatePriceResponse,
} from '@/types/dashboard';

interface ReferenceStrataProps {
  farmgate?: FarmgatePriceResponse;
}

const measure: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
  minWidth: 0,
};
const eyebrow: CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 9.5,
  fontWeight: 500,
  letterSpacing: '0.16em',
  textTransform: 'uppercase',
  color: 'var(--ink-light)',
  display: 'flex',
  alignItems: 'center',
  gap: 7,
};
const dot: CSSProperties = {
  width: 6,
  height: 6,
  borderRadius: '50%',
  flex: 'none',
};
// Editorial figure — Playfair, the brand's headline face, used here as a
// magazine pull-stat. Bigger + near-black ink = the legibility the mono 17px
// values lacked, without any box.
const figure: CSSProperties = {
  fontFamily: 'var(--font-display)',
  fontWeight: 500,
  fontSize: 'clamp(30px, 3.4vw, 40px)',
  lineHeight: 0.95,
  color: 'var(--ink)',
  letterSpacing: '-0.015em',
  display: 'flex',
  alignItems: 'baseline',
  gap: 7,
  flexWrap: 'wrap',
};
const unit: CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontWeight: 400,
  fontSize: 11,
  letterSpacing: '0.02em',
  color: 'var(--ink-mid)',
};
const figureAwait: CSSProperties = {
  ...figure,
  fontStyle: 'italic',
  fontWeight: 400,
  fontSize: 'clamp(22px, 2.6vw, 28px)',
  color: 'var(--ink-light)',
};
const deltaBase: CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: '0.02em',
  lineHeight: 1.3,
};
const vs: CSSProperties = { color: 'var(--ink-light)', fontWeight: 400 };
const subnote: CSSProperties = {
  fontFamily: 'var(--font-display)',
  fontStyle: 'italic',
  fontSize: 13.5,
  lineHeight: 1.35,
  color: 'var(--ink-mid)',
};
const meta: CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 9,
  letterSpacing: '0.07em',
  textTransform: 'uppercase',
  color: 'var(--ink-light)',
  marginTop: 'auto',
  paddingTop: 4,
};

/** Hover tooltip explaining a reference metric — mirrors the gauge tooltip. */
function InfoTooltip({
  name,
  desc,
  children,
}: {
  name: string;
  desc: string;
  children: ReactNode;
}) {
  const isTouch = useIsTouch();
  if (isTouch) return <>{children}</>;
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>{children}</TooltipTrigger>
        <TooltipContent
          side="top"
          sideOffset={10}
          className="max-w-70 p-0 border-0 rounded-none shadow-[0_8px_20px_rgba(0,0,0,0.25)] data-[state=open]:zoom-in-100 data-[state=closed]:zoom-out-100"
          style={{
            background: 'var(--ink)',
            color: 'var(--paper)',
            borderRadius: 0,
            borderLeft: '2px solid var(--ink-light)',
          }}
        >
          <div style={{ padding: '12px 14px' }}>
            <div
              className="uppercase"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                fontWeight: 600,
                letterSpacing: '0.22em',
                marginBottom: 8,
              }}
            >
              {name}
            </div>
            <div
              style={{
                fontFamily: 'var(--font-sans)',
                fontSize: 12,
                lineHeight: 1.55,
                color: '#CFCFCF',
              }}
            >
              {desc}
            </div>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default function ReferenceStrata({ farmgate }: ReferenceStrataProps) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language?.startsWith('en') ? 'en' : 'fr';

  if (!hasFarmgateData(farmgate)) return null;

  const nf0 = new Intl.NumberFormat(lang, { maximumFractionDigits: 0 });
  const fmtDate = (iso: string) =>
    new Intl.DateTimeFormat(lang, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    }).format(new Date(`${iso}T00:00:00`));

  const unitLabel = (u: string) =>
    u === 'per_kg' ? '/kg' : u === 'per_tonne' ? '/t' : t('market.fg_unit_bag');
  const currencyLabel = (c: string) => (c === 'XOF' ? 'FCFA' : c);
  const pct = (p: number) =>
    `${p > 0 ? '+' : ''}${new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(p)} %`;

  // --- Official price (per origin) ---
  const officialCell = (region: string, source: string, entry: FarmgatePriceEntry) => (
    <div style={measure}>
      <span style={eyebrow}>
        {t('market.fg_official')} · {region}
      </span>
      <span style={figure}>
        {nf0.format(entry.price_native)}{' '}
        <span style={unit}>
          {currencyLabel(entry.currency)}
          {unitLabel(entry.unit)}
        </span>
      </span>
      <InfoTooltip
        name={t(`market.fg_camp_${entry.campaign_type}`)}
        desc={t(`market.fg_camp_${entry.campaign_type}_desc`)}
      >
        <span style={{ ...subnote, cursor: 'help', alignSelf: 'flex-start' }}>
          {t(`market.fg_camp_${entry.campaign_type}`)}
        </span>
      </InfoTooltip>
      <span style={meta}>
        {entry.season_label} · {fmtDate(entry.effective_date)} · {source}
      </span>
    </div>
  );

  const officialPending = (region: string, source: string, season: string) => (
    <div style={measure}>
      <span style={eyebrow}>
        {t('market.fg_official')} · {region}
      </span>
      <span style={figureAwait}>{t('market.fg_await')}</span>
      <span style={subnote}>{t('market.fg_await_note')}</span>
      <span style={meta}>
        {season} · {source}
      </span>
    </div>
  );

  // --- Market-implied equivalent (per origin) ---
  const equivCell = (region: string, e: FarmgateEquivEntry) => {
    const d = e.delta_pct_vs_official;
    const color =
      d == null
        ? 'var(--ink-light)'
        : d >= 0
          ? 'var(--color-signal-open)'
          : 'var(--color-signal-hedge)';
    return (
      <div style={measure}>
        <InfoTooltip
          name={t('market.fg_equiv')}
          desc={e.estimated ? t('market.fg_equiv_ghana_desc') : t('market.fg_equiv_desc')}
        >
          <span style={{ ...eyebrow, cursor: 'help' }}>
            <span style={{ ...dot, background: color }} />
            {t('market.fg_equiv')} · {region}
            {e.estimated && (
              <span style={{ color: 'var(--color-signal-monitor)' }}>
                {' · '}
                {t('market.fg_est')}
              </span>
            )}
          </span>
        </InfoTooltip>
        <span style={figure}>
          ≈ {nf0.format(e.price_native)}{' '}
          <span style={unit}>
            {currencyLabel(e.currency)}
            {unitLabel(e.unit)}
          </span>
        </span>
        {d != null ? (
          <span style={{ ...deltaBase, color }}>
            {d >= 0 ? '▲' : '▼'} {pct(d)} <span style={vs}>{t('market.fg_equiv_vs')}</span>
          </span>
        ) : (
          <span style={subnote}>{t('market.fg_equiv_anticip')}</span>
        )}
        <span style={meta}>
          {t('market.fg_equiv_src')} ·{' '}
          {e.estimated
            ? t('market.fg_est')
            : new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(
                e.coefficient * 100
              ) + ' %'}
        </span>
      </div>
    );
  };

  const cells: ReactNode[] = [];
  for (const [key, label, source] of [
    ['civ', 'CIV', 'CCC'],
    ['ghana', 'Ghana', 'COCOBOD'],
  ] as const) {
    const entry = farmgate?.[key];
    if (entry) cells.push(officialCell(label, source, entry));
    else if (farmgate?.season)
      cells.push(officialPending(label, source, farmgate.season));
  }
  const equiv = farmgate?.equivalent;
  if (equiv?.civ) cells.push(equivCell('CIV', equiv.civ));
  if (equiv?.ghana) cells.push(equivCell('Ghana', equiv.ghana));

  return (
    <div>
      <style>{`
        .fg-strip { display: grid; grid-template-columns: repeat(${cells.length || 1}, minmax(0,1fr)); }
        .fg-strip > .fg-m { padding: 4px 28px; border-left: 1px solid var(--rule); }
        .fg-strip > .fg-m:first-child { padding-left: 0; border-left: 0; }
        @media (max-width: 900px) {
          .fg-strip { grid-template-columns: 1fr 1fr; row-gap: 28px; }
          .fg-strip > .fg-m:nth-child(odd) { border-left: 0; padding-left: 0; }
          .fg-strip > .fg-m:nth-child(n+3) { border-top: 1px solid var(--rule); padding-top: 24px; }
        }
        @media (max-width: 480px) {
          .fg-strip { grid-template-columns: 1fr; row-gap: 0; }
          .fg-strip > .fg-m { border-left: 0; padding: 22px 0; border-top: 1px solid var(--rule); }
          .fg-strip > .fg-m:first-child { border-top: 0; padding-top: 4px; }
        }
      `}</style>
      <div className="fg-strip">
        {cells.map((c, i) => (
          <div className="fg-m" key={i}>
            {c}
          </div>
        ))}
      </div>
      {hasFarmgateData(farmgate) && <Socle>{t('market.fg_disclaimer')}</Socle>}
    </div>
  );
}
