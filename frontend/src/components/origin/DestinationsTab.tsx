import { useTranslation } from 'react-i18next';
import { Eyebrow } from '@/components/editorial';
import { useLanguage } from '@/hooks/useLanguage';
import type { BreakdownLine, OriginDestinationsResponse } from '@/types/origin';
import HelpTip from './HelpTip';
import {
  formatPercent,
  formatSignedPercent,
  formatTonnes,
  numberLocale,
  tdLabelStyle,
  tdStyle,
  thStyle,
  trendGlyph,
  windowParts,
} from './shared';

/** Block header — same construction as the campaign and market tabs. */
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

/**
 * Share rendered as a rule rather than a number alone.
 *
 * The table already prints the percentage; the bar exists so the *shape* of the
 * market is readable without arithmetic — that one buyer takes a quarter and the
 * tail is long. Decorative, hence `aria-hidden`: the figure beside it is the
 * accessible value.
 */
function ShareBar({ pct }: { pct: number | null }) {
  return (
    <span
      aria-hidden
      style={{
        display: 'block',
        height: 4,
        width: '100%',
        background: 'var(--paper-off)',
        marginTop: 5,
      }}
    >
      <span
        style={{
          display: 'block',
          height: '100%',
          width: `${Math.max(0, Math.min(100, pct ?? 0))}%`,
          background: 'var(--ink)',
        }}
      />
    </span>
  );
}

function BreakdownTable({
  lines,
  labelHead,
  locale,
}: {
  lines: BreakdownLine[];
  labelHead: string;
  locale: string;
}) {
  const { t } = useTranslation();
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 520 }}>
        <thead>
          <tr style={{ borderBottom: '2px solid var(--ink)' }}>
            <th scope="col" style={thStyle('left')}>
              {labelHead}
            </th>
            <th scope="col" style={thStyle()}>
              {t('origin.col_tonnes')}
            </th>
            <th scope="col" style={{ ...thStyle(), minWidth: 130 }}>
              {t('origin.col_share')}
            </th>
            <th scope="col" style={thStyle()}>
              {t('origin.col_previous')}
            </th>
            <th scope="col" style={thStyle()}>
              {t('origin.col_delta')}
            </th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => {
            const trend = trendGlyph(line.delta_pct);
            return (
              <tr key={line.label} style={{ borderBottom: '1px dotted var(--rule)' }}>
                <td style={tdLabelStyle()}>{line.label}</td>
                <td style={tdStyle()}>{formatTonnes(line.export_tonnes, locale)}</td>
                <td style={{ ...tdStyle(), paddingBottom: 8 }}>
                  {formatPercent(line.share_pct, locale)}
                  <ShareBar pct={line.share_pct} />
                </td>
                <td style={{ ...tdStyle(), color: 'var(--ink-light)' }}>
                  {formatTonnes(line.previous_tonnes, locale)}
                </td>
                <td style={tdStyle()}>
                  <span style={{ color: trend.color, marginRight: 5 }}>{trend.glyph}</span>
                  {formatSignedPercent(line.delta_pct, locale)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Destinations & ports tab — matrix block ② row 3, Export Essentiel and up.
 *
 * Carries **no exporter**: the cube holds one on the very same rows this view
 * aggregates, and naming it is `read:watchai:nominative`, a key Export Essentiel
 * does not buy. The collapse happens in the query, not here.
 *
 * Every line states the window it covers, because they are not all the same: a
 * destination that stopped shipping mid-season is compared over the months it
 * shipped, not over the season's full span.
 */
export default function DestinationsTab({ data }: { data: OriginDestinationsResponse }) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const locale = numberLocale(language);
  const { destinations, ports, concentration, season, previous_season } = data;

  const span = destinations[0]
    ? windowParts(
        destinations[0].window.from,
        destinations[0].window.to,
        destinations[0].window.months,
        locale
      )
    : null;

  return (
    <div>
      <BlockHeader
        title={t('origin.destinations_title', { season })}
        aside={span ? t('origin.window', span) : undefined}
        help={
          <HelpTip
            title={t('origin.destinations_help_title')}
            body={t('origin.destinations_help_body', { previous: previous_season })}
          />
        }
      />

      {/* The one sentence an exporter reads first: how few buyers the origin
          depends on. Served by the API so two consumers cannot disagree on it. */}
      <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2 mb-6">
        {[
          {
            key: 'origin.concentration_top1',
            value: formatPercent(concentration.top1_share_pct, locale),
          },
          {
            key: 'origin.concentration_top3',
            value: formatPercent(concentration.top3_share_pct, locale),
          },
          {
            key: 'origin.concentration_count',
            value: String(concentration.count),
          },
        ].map((item) => (
          <div key={item.key}>
            <Eyebrow tone="subtle" size={9} tracking="0.18em">
              {t(item.key)}
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
              {item.value}
            </div>
          </div>
        ))}
      </div>

      <BreakdownTable
        lines={destinations}
        labelHead={t('origin.col_destination')}
        locale={locale}
      />

      <div style={{ marginTop: 30 }}>
        <BlockHeader title={t('origin.ports_title')} aside={t('origin.ports_aside')} />
        <BreakdownTable lines={ports} labelHead={t('origin.col_port')} locale={locale} />
      </div>
    </div>
  );
}
