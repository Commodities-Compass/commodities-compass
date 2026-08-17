import { useTranslation } from 'react-i18next';
import { Eyebrow } from '@/components/editorial';
import { useLanguage } from '@/hooks/useLanguage';
import type { ExporterMover, OriginExportersResponse } from '@/types/origin';
import HelpTip from './HelpTip';
import {
  formatPercent,
  formatSignedPercent,
  formatTonnes,
  numberLocale,
  pillStyle,
  tdLabelStyle,
  tdStyle,
  thStyle,
  trendGlyph,
} from './shared';

function BlockHeader({
  title,
  aside,
  help,
}: {
  title: string;
  aside?: string;
  help?: React.ReactNode;
}) {
  return (
    <div
      className="flex items-baseline justify-between mb-4 pb-2.5"
      style={{ borderBottom: '1px solid var(--ink)' }}
    >
      <span className="flex items-center gap-0.5">
        <Eyebrow as="h3" tone="primary" size={11} tracking="0.22em" style={{ fontWeight: 700 }}>
          {title}
        </Eyebrow>
        {help}
      </span>
      {aside && (
        <Eyebrow tone="subtle" size={9} tracking="0.18em">
          {aside}
        </Eyebrow>
      )}
    </div>
  );
}

/** One podium column. Growth is always printed with its two absolute volumes —
 *  a percentage alone invites the reader to imagine the base. */
function MoversColumn({
  title,
  movers,
  locale,
}: {
  title: string;
  movers: ExporterMover[];
  locale: string;
}) {
  return (
    <div style={{ flex: '1 1 260px' }}>
      <Eyebrow tone="subtle" size={9} tracking="0.2em">
        {title}
      </Eyebrow>
      {movers.map((mover) => {
        const trend = trendGlyph(mover.growth_pct);
        return (
          <div
            key={mover.exporter}
            className="flex items-baseline gap-2"
            style={{ padding: '9px 0', borderBottom: '1px dotted var(--rule)' }}
          >
            <span
              style={{
                fontFamily: 'var(--font-editorial)',
                fontSize: 13.5,
                fontWeight: 600,
                color: 'var(--ink)',
              }}
            >
              {mover.exporter}
            </span>
            <span
              className="tabular-nums ml-auto"
              style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-light)' }}
            >
              {formatTonnes(mover.previous_exports_t, locale)} →{' '}
              {formatTonnes(mover.exports_total_t, locale)}
            </span>
            <span style={{ color: trend.color, fontSize: 13 }}>{trend.glyph}</span>
            <span
              className="tabular-nums"
              style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, fontWeight: 600 }}
            >
              {formatSignedPercent(mover.growth_pct, locale)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Nominative exporter flows — matrix block ② row 5, Export Premium and up.
 *
 * The only tab in Section VI that names an operator, which is why it sits behind
 * its own key: a tier can buy the destination breakdown and still never learn who
 * shipped there.
 *
 * A negative balance is rendered as information, not as an error. On the current
 * batch **58 of 102 exporters** show one, because the purchase master covers
 * fewer operators than the customs declarations and stock carries across seasons.
 * Treating it as an anomaly would flag more than half the market.
 */
export default function ExportersTab({ data }: { data: OriginExportersResponse }) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const locale = numberLocale(language);
  const { exporters, movers, season, growth_floor_tonnes } = data;

  return (
    <div>
      <BlockHeader
        title={t('origin.exporters_title', { season })}
        aside={t('origin.exporters_aside')}
        help={
          <HelpTip
            title={t('origin.exporters_help_title')}
            body={t('origin.exporters_help_body')}
          />
        }
      />

      <div className="flex flex-wrap gap-x-12 gap-y-6 mb-8">
        <MoversColumn title={t('origin.movers_up')} movers={movers.up} locale={locale} />
        <MoversColumn title={t('origin.movers_down')} movers={movers.down} locale={locale} />
      </div>
      <Eyebrow tone="subtle" size={9} tracking="0.14em" style={{ display: 'block', marginBottom: 22 }}>
        {t('origin.movers_floor', { floor: formatTonnes(growth_floor_tonnes, locale) })}
      </Eyebrow>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 640 }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--ink)' }}>
              <th scope="col" style={thStyle('left')}>
                {t('origin.col_exporter')}
              </th>
              <th scope="col" style={thStyle()}>
                {t('origin.col_exports')}
              </th>
              <th scope="col" style={thStyle()}>
                {t('origin.col_purchases_short')}
              </th>
              <th scope="col" style={thStyle()}>
                {t('origin.col_transfo_share')}
              </th>
              <th scope="col" style={thStyle()}>
                {t('origin.col_growth')}
              </th>
              <th scope="col" style={thStyle()}>
                {t('origin.col_balance')}
              </th>
            </tr>
          </thead>
          <tbody>
            {exporters.map((row) => (
              <tr key={row.exporter} style={{ borderBottom: '1px dotted var(--rule)' }}>
                <td style={tdLabelStyle()}>
                  <span className="inline-flex items-baseline gap-2">
                    {row.exporter}
                    {/* GEPEX membership is what makes a transformation share
                        readable at all — the 11 members are the grinders. */}
                    {row.is_gepex_member && (
                      <span style={pillStyle('mute')}>{t('origin.gepex_member')}</span>
                    )}
                  </span>
                </td>
                <td style={tdStyle()}>{formatTonnes(row.exports_total_t, locale)}</td>
                <td style={tdStyle()}>{formatTonnes(row.purchases_t, locale)}</td>
                <td style={tdStyle()}>
                  {formatPercent(row.transformation_share_pct, locale, 0)}
                </td>
                <td style={tdStyle()}>{formatSignedPercent(row.growth_pct, locale)}</td>
                <td style={{ ...tdStyle(), textAlign: 'right' }}>
                  <span style={pillStyle(row.outflow_exceeds_purchases ? 'hedge' : 'open')}>
                    {row.balance_t >= 0 ? '+' : '−'}
                    {formatTonnes(Math.abs(row.balance_t), locale)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
