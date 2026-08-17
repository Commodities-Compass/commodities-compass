import { useTranslation } from 'react-i18next';
import { Eyebrow } from '@/components/editorial';
import { useLanguage } from '@/hooks/useLanguage';
import type { OriginBenchmarkResponse } from '@/types/origin';
import {
  formatPercent,
  formatTonnes,
  numberLocale,
  tdLabelStyle,
  tdStyle,
  thStyle,
} from './shared';

function BlockHeader({ title, aside }: { title: string; aside?: string }) {
  return (
    <div
      className="flex items-baseline justify-between mb-4 pb-2.5"
      style={{ borderBottom: '1px solid var(--ink)' }}
    >
      <Eyebrow as="h3" tone="primary" size={11} tracking="0.22em" style={{ fontWeight: 700 }}>
        {title}
      </Eyebrow>
      {aside && (
        <Eyebrow tone="subtle" size={9} tracking="0.18em">
          {aside}
        </Eyebrow>
      )}
    </div>
  );
}

/**
 * "Vos flux vs marché" — matrix block ② row 4, Export Premium / Pro.
 *
 * The identity is resolved server-side from the authenticated principal. There is
 * no exporter parameter to pass and no exporter picker to render: a client-chosen
 * identity would let any Export Premium account read a competitor's book.
 *
 * `applicable: false` gets a written explanation rather than an empty table.
 * Zeroes here would say "you shipped nothing", which is a different and false
 * claim from "we do not know who you are".
 */
export default function BenchmarkTab({ data }: { data: OriginBenchmarkResponse }) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const locale = numberLocale(language);

  if (!data.applicable || !data.position) {
    return (
      <div>
        <BlockHeader title={t('origin.benchmark_na_title')} />
        <p
          style={{
            fontFamily: 'var(--font-editorial)',
            fontSize: 14.5,
            lineHeight: 1.7,
            color: 'var(--ink-mid)',
            maxWidth: '62ch',
            margin: 0,
          }}
        >
          {t('origin.benchmark_na_body')}
        </p>
      </div>
    );
  }

  const { position, exporter, season } = data;

  return (
    <div>
      <BlockHeader title={t('origin.benchmark_title', { season })} aside={exporter ?? undefined} />

      <div className="flex flex-wrap gap-x-12 gap-y-5 mb-8">
        <div>
          <Eyebrow tone="subtle" size={9} tracking="0.2em">
            {t('origin.benchmark_share')}
          </Eyebrow>
          <div
            className="tabular-nums"
            style={{
              fontFamily: 'var(--font-display)',
              fontWeight: 700,
              fontSize: 44,
              lineHeight: 1.05,
              color: 'var(--ink)',
            }}
          >
            {formatPercent(position.market_share_pct, locale)}
          </div>
        </div>
        <div>
          <Eyebrow tone="subtle" size={9} tracking="0.2em">
            {t('origin.benchmark_rank')}
          </Eyebrow>
          <div
            className="tabular-nums"
            style={{
              fontFamily: 'var(--font-display)',
              fontWeight: 700,
              fontSize: 44,
              lineHeight: 1.05,
              color: 'var(--ink)',
            }}
          >
            {position.rank ?? '—'}
          </div>
          {/* The denominator is the point: 23rd of 102 is a different sentence
              from 23rd of 25. */}
          <Eyebrow tone="subtle" size={9} tracking="0.14em">
            {t('origin.benchmark_rank_of', { total: position.exporters_ranked })}
          </Eyebrow>
        </div>
        {[
          {
            key: 'origin.benchmark_own_volume',
            value: `${formatTonnes(position.exports_total_t, locale)} t`,
          },
          {
            key: 'origin.benchmark_market_volume',
            value: `${formatTonnes(position.market_total_t, locale)} t`,
          },
        ].map((item) => (
          <div key={item.key} style={{ alignSelf: 'flex-end' }}>
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

      <BlockHeader title={t('origin.benchmark_destinations')} />
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 420 }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--ink)' }}>
              <th scope="col" style={thStyle('left')}>
                {t('origin.col_destination')}
              </th>
              <th scope="col" style={thStyle()}>
                {t('origin.col_tonnes')}
              </th>
              <th scope="col" style={thStyle()}>
                {t('origin.col_share')}
              </th>
            </tr>
          </thead>
          <tbody>
            {position.own_destinations.map((line) => (
              <tr key={line.label} style={{ borderBottom: '1px dotted var(--rule)' }}>
                <td style={tdLabelStyle()}>{line.label}</td>
                <td style={tdStyle()}>{formatTonnes(line.export_tonnes, locale)}</td>
                <td style={tdStyle()}>{formatPercent(line.share_pct, locale)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
