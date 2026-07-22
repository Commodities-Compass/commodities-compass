import type { CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import GroupHeader from './group-header';
import { Eyebrow } from '@/components/editorial';
import { gridStyle5 } from './helpers';
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
  fontVariantNumeric: 'tabular-nums',
  color: 'var(--ink)',
};
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

  const hasEnso =
    macro?.enso_oni_month != null || macro?.enso_nino34_anomaly != null;
  if (!farmgate && !hasEnso) return null;

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

  const fgCell = (region: string, entry: FarmgatePriceEntry | null) => (
    <div style={cell}>
      <span style={tagSeason}>{t('market.tag_season')}</span>
      <span style={country}>
        {t('market.fg_price')} — {region}
      </span>
      {entry ? (
        <>
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
        </>
      ) : (
        <span style={valBig}>{t('market.fg_not_announced')}</span>
      )}
    </div>
  );

  return (
    <div style={{ marginBottom: 28 }}>
      <GroupHeader
        name={t('market.grp_reference')}
        cadence={t('market.cad_seasonal')}
      />
      <div style={gridStyle5}>
        {farmgate && fgCell('CIV', farmgate.civ)}
        {farmgate && fgCell('Ghana', farmgate.ghana)}
        {macro?.enso_oni_month != null && (
          <div style={cell}>
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
        )}
        {macro?.enso_nino34_anomaly != null && (
          <div style={cell}>
            <span style={tagBase}>{t('market.tag_monthly')}</span>
            <span style={country}>Niño 3.4</span>
            <span style={valMid}>{nf2.format(macro.enso_nino34_anomaly)}</span>
            <span style={meta}>{t('market.nino_meta')}</span>
          </div>
        )}
      </div>
      {farmgate && (farmgate.civ || farmgate.ghana) && (
        <div style={{ marginTop: 16 }}>
          <Eyebrow tone="subtle" size={9}>
            {t('market.fg_disclaimer')}
          </Eyebrow>
        </div>
      )}
    </div>
  );
}
