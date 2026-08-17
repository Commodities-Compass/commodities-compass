import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Eyebrow } from '@/components/editorial';
import HelpTip from './HelpTip';
import { useLanguage } from '@/hooks/useLanguage';
import type { OriginCampaignResponse, YtdComparison } from '@/types/origin';
import {
  formatMillions,
  formatMonthLong,
  formatMonthShort,
  formatSignedPercent,
  formatTonnes,
  numberLocale,
  pillStyle,
  tdLabelStyle,
  tdStyle,
  thStyle,
  trendGlyph,
  windowParts,
} from './shared';

const SOURCE_KEY: Record<YtdComparison['source'], string> = {
  exports: 'origin.source_exports',
  purchases: 'origin.source_purchases',
  grinding: 'origin.source_grinding',
};

/** Block header: flex baseline over a 1px ink rule, same as the weather blocks. */
function BlockHeader({
  title,
  aside,
  help,
}: {
  title: string;
  aside?: string;
  help?: ReactNode;
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

/**
 * Campaign tab — the row every tier holds.
 *
 * Carries **no exporter, destination or port**: those are separate entitlement
 * keys that the tiers reaching this tab do not necessarily own. That rules out any
 * "top movers" ranking, which would name operators.
 *
 * The per-row balance comes from the payload (`balance_t`), not from arithmetic
 * repeated here: it is the same bean-equivalent computation as the season balance,
 * and a second implementation would be free to drift. A single month may
 * legitimately be negative — off-season shipments draw on stock bought earlier —
 * so a red pill is information, not an error.
 */
export default function CampaignTab({ data }: { data: OriginCampaignResponse }) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const locale = numberLocale(language);
  const { monthly, ytd, month, season } = data;

  const totals = (
    ['purchases_t', 'exports_total_t', 'exports_beans_t', 'exports_transformed_t'] as const
  ).map((key) => monthly.reduce((sum, r) => sum + r[key], 0));

  return (
    <div>
      <BlockHeader
        title={t('origin.campaign_block_title', { season })}
        aside={t('origin.all_operators_tonnes')}
      />

      {month && (
        <div className="flex items-end justify-between flex-wrap gap-4 mb-6">
          <div>
            <Eyebrow tone="subtle" size={9} tracking="0.2em">
              {t('origin.last_published_month')}
            </Eyebrow>
            <div
              style={{
                fontFamily: 'var(--font-display)',
                fontStyle: 'italic',
                fontWeight: 400,
                fontSize: 22,
                lineHeight: 1.1,
                color: 'var(--ink)',
              }}
            >
              {formatMonthLong(month.period, locale)}
            </div>
          </div>
          <div className="flex flex-wrap gap-x-8 gap-y-2">
            {[
              { key: 'origin.col_exports', value: `${formatTonnes(month.exports_t, locale)} t` },
              {
                key: 'origin.col_purchases',
                value: `${formatTonnes(month.purchases_t, locale)} t`,
              },
              { key: 'origin.valcaf', value: `${formatMillions(month.valcaf_fcfa, locale)} M` },
              {
                key: 'origin.taxes',
                value: `${formatMillions(month.duties_taxes_fcfa, locale)} M`,
              },
            ].map((k) => (
              <div key={k.key}>
                <Eyebrow tone="subtle" size={9} tracking="0.18em">
                  {t(k.key)}
                </Eyebrow>
                <div
                  className="tabular-nums"
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 15,
                    fontWeight: 600,
                    color: 'var(--ink)',
                  }}
                >
                  {k.value}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 560 }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--ink)' }}>
              <th scope="col" style={thStyle('left')}>
                {t('origin.col_month')}
              </th>
              <th scope="col" style={thStyle()}>
                {t('origin.col_purchases')}
              </th>
              <th scope="col" style={thStyle()}>
                {t('origin.col_exports')}
              </th>
              <th scope="col" style={thStyle()}>
                {t('origin.col_beans')}
              </th>
              <th scope="col" style={thStyle()}>
                {t('origin.col_transformed')}
              </th>
              <th scope="col" style={thStyle()}>
                {t('origin.col_grinding')}
              </th>
              <th scope="col" style={thStyle()}>
                {t('origin.col_balance')}
              </th>
            </tr>
          </thead>
          <tbody>
            {monthly.map((row) => {
              // STATSER trails the other sources; those months are shown quietly
              // rather than hidden, so the reader sees the publication lag.
              const pending = row.grinding_declared_t == null;
              return (
                <tr key={row.period} style={{ borderBottom: '1px dotted var(--rule)' }}>
                  <td style={tdLabelStyle(pending)}>{formatMonthShort(row.period, locale)}</td>
                  <td style={tdStyle(pending)}>{formatTonnes(row.purchases_t, locale)}</td>
                  <td style={tdStyle(pending)}>{formatTonnes(row.exports_total_t, locale)}</td>
                  <td style={tdStyle(pending)}>{formatTonnes(row.exports_beans_t, locale)}</td>
                  <td style={tdStyle(pending)}>
                    {formatTonnes(row.exports_transformed_t, locale)}
                  </td>
                  <td style={tdStyle(pending)}>
                    {formatTonnes(row.grinding_declared_t, locale)}
                  </td>
                  <td style={{ ...tdStyle(), textAlign: 'right' }}>
                    <span style={pillStyle(row.balance_t >= 0 ? 'open' : 'hedge')}>
                      {row.balance_t >= 0 ? '+' : '−'}
                      {formatTonnes(Math.abs(row.balance_t), locale)}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr style={{ borderTop: '2px solid var(--ink)' }}>
              <td style={{ ...tdLabelStyle(), paddingTop: 12, fontWeight: 700 }}>
                {t('origin.total')}
              </td>
              {totals.map((value, i) => (
                <td
                  key={i}
                  style={{ ...tdStyle(), paddingTop: 12, color: 'var(--ink)', fontWeight: 600 }}
                >
                  {formatTonnes(value, locale)}
                </td>
              ))}
              <td style={{ ...tdStyle(), paddingTop: 12, color: 'var(--ink)', fontWeight: 600 }}>
                {formatTonnes(
                  monthly.reduce((sum, r) => sum + (r.grinding_declared_t ?? 0), 0),
                  locale
                )}
              </td>
              <td style={{ ...tdStyle(), paddingTop: 12, textAlign: 'right' }}>
                <span style={pillStyle('mute')}>{t('origin.cumulative')}</span>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      <div style={{ marginTop: 30 }}>
        <BlockHeader
          title={t('origin.ytd_title')}
          aside={t('origin.ytd_aside')}
          help={<HelpTip title={t('origin.ytd_help_title')} body={t('origin.ytd_help_body')} />}
        />
        {ytd.map((block) => {
          const trend = trendGlyph(block.delta_pct);
          const win = windowParts(
            block.window.from,
            block.window.to,
            block.window.months,
            locale
          );
          return (
            <div
              key={block.source}
              className="flex flex-wrap items-baseline gap-x-3.5 gap-y-1"
              style={{ padding: '13px 0', borderBottom: '1px dotted var(--rule)' }}
            >
              <span
                style={{
                  fontFamily: 'var(--font-editorial)',
                  fontSize: 14,
                  fontWeight: 600,
                  color: 'var(--ink)',
                  minWidth: 92,
                }}
              >
                {t(SOURCE_KEY[block.source])}
              </span>
              {/* The window is the point: grinding shows 7 months where exports
                  show 10, and comparing across them would invent a collapse. */}
              <Eyebrow tone="subtle" size={9} tracking="0.14em">
                {win ? t('origin.window', win) : '—'}
              </Eyebrow>
              <span
                className="tabular-nums ml-auto"
                style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 600 }}
              >
                {formatTonnes(block.current_t, locale)} t
              </span>
              <span
                className="tabular-nums"
                style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-mid)' }}
              >
                {t('origin.vs', { value: formatTonnes(block.previous_t, locale) })}
              </span>
              <span style={{ color: trend.color, fontSize: 14, fontWeight: 600 }}>
                {trend.glyph}
              </span>
              <span
                className="tabular-nums"
                style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, fontWeight: 500 }}
              >
                {formatSignedPercent(block.delta_pct, locale)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
