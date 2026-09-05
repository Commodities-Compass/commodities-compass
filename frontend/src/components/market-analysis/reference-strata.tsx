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
import { gridStyle, hasFarmgateData, hasReferenceData } from './helpers';
import type {
  FarmgatePriceEntry,
  FarmgatePriceResponse,
  MacroPanelResponse,
} from '@/types/dashboard';

interface ReferenceStrataProps {
  farmgate?: FarmgatePriceResponse;
  macro?: MacroPanelResponse;
}

const cell: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
};
const tagBase: CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 8,
  letterSpacing: '0.16em',
  textTransform: 'uppercase',
  border: '1px solid var(--rule)',
  padding: '1px 5px',
  alignSelf: 'flex-start',
  color: 'var(--ink-light)',
};
const tagSeason: CSSProperties = {
  ...tagBase,
  color: 'var(--ink-mid)',
  borderColor: 'var(--ink-light)',
};
const country: CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: 'var(--ink-mid)',
};
const valBig: CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 17,
  fontWeight: 600,
  fontVariantNumeric: 'tabular-nums',
  color: 'var(--ink)',
};
const valMid: CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 15,
  fontWeight: 600,
  fontVariantNumeric: 'tabular-nums',
  color: 'var(--ink)',
};
const cellHelp: CSSProperties = { ...cell, cursor: 'help' };

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
const unit: CSSProperties = {
  fontSize: 10,
  fontWeight: 400,
  color: 'var(--ink-mid)',
};
const meta: CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 9,
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  color: 'var(--ink-light)',
};

export default function ReferenceStrata({
  farmgate,
  macro,
}: ReferenceStrataProps) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language?.startsWith('en') ? 'en' : 'fr';

  if (!hasReferenceData(farmgate, macro)) return null;

  const nf0 = new Intl.NumberFormat(lang, { maximumFractionDigits: 0 });
  const nf2 = new Intl.NumberFormat(lang, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const fmtDate = (iso: string) =>
    new Intl.DateTimeFormat(lang, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    }).format(new Date(`${iso}T00:00:00`));

  const unitLabel = (u: string) =>
    u === 'per_kg' ? '/kg' : u === 'per_tonne' ? '/t' : t('market.fg_unit_bag');
  const currencyLabel = (c: string) => (c === 'XOF' ? 'FCFA' : c);

  // Campaign tag with a hover tooltip explaining the sub-campaign period.
  const campaignTag = (campaign: 'principale' | 'intermediaire') => (
    <InfoTooltip
      name={t(`market.fg_camp_${campaign}`)}
      desc={t(`market.fg_camp_${campaign}_desc`)}
    >
      <span style={{ ...tagSeason, cursor: 'help' }}>
        {t(`market.fg_camp_${campaign}`)}
      </span>
    </InfoTooltip>
  );

  const fgCell = (region: string, entry: FarmgatePriceEntry) => (
    <div style={cell}>
      {campaignTag(entry.campaign_type)}
      <span style={country}>
        {t('market.fg_price')} — {region}
      </span>
      <span style={valBig}>
        {nf0.format(entry.price_native)}{' '}
        <span style={unit}>
          {currencyLabel(entry.currency)}
          {unitLabel(entry.unit)}
        </span>
      </span>
      <span style={meta}>
        {entry.season_label} · {fmtDate(entry.effective_date)} ·{' '}
        {entry.source.toUpperCase()}
      </span>
    </div>
  );

  // An origin that hasn't announced the published season yet. The value slot
  // takes the same em dash every other no-data field in the folio uses — the
  // figure does not exist yet, and a sentence in a numeral's place reads as a
  // value. Reprinting last season's price under a fresh date would read as
  // current, which is the failure this card exists to prevent; the meta line
  // carries the reason.
  const fgPending = (region: string, source: string, season: string) => (
    <div style={cell}>
      <span style={tagSeason}>{season}</span>
      <span style={country}>
        {t('market.fg_price')} — {region}
      </span>
      <span style={{ ...valBig, color: 'var(--ink-light)' }}>—</span>
      <span style={meta}>{t('market.fg_pending_meta', { source })}</span>
    </div>
  );

  // Collected first so the grid can fit its own column count — the rail shows
  // one stratum at a time. One card per origin: the price in force for the
  // published season, or the pending card until that origin announces it.
  const cells: ReactNode[] = [];
  for (const [key, label, source] of [
    ['civ', 'CIV', 'CCC'],
    ['ghana', 'Ghana', 'COCOBOD'],
  ] as const) {
    const entry = farmgate?.[key];
    if (entry) cells.push(fgCell(label, entry));
    else if (farmgate?.season)
      cells.push(fgPending(label, source, farmgate.season));
  }
  if (macro?.enso_oni_month != null) {
    cells.push(
      <InfoTooltip
        name={t('indicators.enso_oni_name')}
        desc={t('indicators.enso_oni_desc')}
      >
        <div style={cellHelp}>
          <span style={tagBase}>{t('market.tag_monthly')}</span>
          <span style={country}>ENSO ONI</span>
          <span style={valMid}>{nf2.format(macro.enso_oni_month)}</span>
          {macro.enso_reference_date && (
            <span style={meta}>
              {t('market.enso_ref', {
                date: fmtDate(macro.enso_reference_date),
              })}
            </span>
          )}
        </div>
      </InfoTooltip>
    );
  }
  if (macro?.enso_nino34_anomaly != null) {
    cells.push(
      <InfoTooltip
        name={t('indicators.nino34_name')}
        desc={t('indicators.nino34_desc')}
      >
        <div style={cellHelp}>
          <span style={tagBase}>{t('market.tag_monthly')}</span>
          <span style={country}>Niño 3.4</span>
          <span style={valMid}>{nf2.format(macro.enso_nino34_anomaly)}</span>
          <span style={meta}>{t('market.nino_meta')}</span>
        </div>
      </InfoTooltip>
    );
  }

  return (
    <div>
      <div className="gauges-row" style={gridStyle(cells.length || 1)}>
        {cells.map((cell, i) => (
          <div key={i}>{cell}</div>
        ))}
      </div>
      {hasFarmgateData(farmgate) && <Socle>{t('market.fg_disclaimer')}</Socle>}
    </div>
  );
}
