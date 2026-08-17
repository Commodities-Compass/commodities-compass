import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { Eyebrow } from '@/components/editorial';
import ProductMixBar from './ProductMixBar';
import { useLanguage } from '@/hooks/useLanguage';
import type { OriginMarketViewsResponse, TransformationBlock } from '@/types/origin';
import {
  formatPercent,
  formatTonnes,
  numberLocale,
  pillStyle,
  windowParts,
} from './shared';

const RENDEMENT_BROYAGE = 0.8;

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

interface Stage {
  label: string;
  /** Bar offset and width as percentages of purchases. */
  left: number;
  width: number;
  value: number;
  caption: string;
  kind: 'base' | 'minus' | 'total';
  negative?: boolean;
}

/**
 * One row of the cascade. Plain divs rather than Recharts: the four values are
 * printed beside the bars, so there is nothing for axes, ticks or tooltips to do,
 * and a 4-row bar does not justify a chart runtime in this block.
 */
function FallRow({
  stage,
  index,
  locale,
}: {
  stage: Stage;
  index: number;
  locale: string;
}) {
  return (
    <div className="origin-fall-row">
      <span
        style={{
          fontFamily: 'var(--font-editorial)',
          fontSize: 14,
          fontWeight: 600,
          color: 'var(--ink)',
        }}
      >
        {stage.label}
      </span>
      <span className="origin-fall-track">
        <span
          className={`origin-fall-bar origin-fall-${stage.kind}${
            stage.negative ? ' origin-fall-bad' : ''
          }`}
          style={{
            left: `${stage.left}%`,
            width: `${Math.max(stage.width, 0.6)}%`,
            animationDelay: `${index * 150}ms`,
          }}
        />
      </span>
      <span className="origin-fall-val tabular-nums">
        {stage.kind === 'total' && stage.value >= 0 ? '+' : ''}
        {stage.kind === 'total' && stage.value < 0 ? '−' : ''}
        {formatTonnes(Math.abs(stage.value), locale)}
        <small>{stage.caption}</small>
      </span>
    </div>
  );
}

function buildStages(
  block: TransformationBlock,
  t: TFunction,
  locale: string
): Stage[] {
  const base = block.purchases_t > 0 ? block.purchases_t : 1;
  const pct = (v: number) => (v / base) * 100;
  const beansPct = pct(block.exports_beans_t);
  const grindPct = pct(block.grinding_derived_t);
  const balancePct = pct(block.balance_t);

  return [
    {
      label: t('origin.stage_purchases'),
      left: 0,
      width: 100,
      value: block.purchases_t,
      caption: t('origin.caption_tonnes'),
      kind: 'base',
    },
    {
      label: t('origin.stage_beans'),
      left: Math.max(100 - beansPct, 0),
      width: beansPct,
      value: block.exports_beans_t,
      caption: t('origin.caption_beans'),
      kind: 'minus',
    },
    {
      label: t('origin.stage_grinding'),
      left: Math.max(100 - beansPct - grindPct, 0),
      width: grindPct,
      value: block.grinding_derived_t,
      caption: t('origin.caption_grinding', {
        value: formatTonnes(block.exports_transformed_t, locale),
        yield: locale.startsWith('fr')
          ? String(RENDEMENT_BROYAGE).replace('.', ',')
          : String(RENDEMENT_BROYAGE),
      }),
      kind: 'minus',
    },
    {
      label: t('origin.stage_balance'),
      left: 0,
      width: Math.abs(balancePct),
      value: block.balance_t,
      caption: t('origin.caption_balance', {
        pct: formatPercent(block.balance_pct, locale),
      }),
      kind: 'total',
      negative: block.balance_t < 0,
    },
  ];
}

/**
 * Market views tab — aggregated views + the material balance.
 *
 * The balance is bean-equivalent arithmetic: transformed exports are converted
 * back through `÷ 0.80` before they enter it. Adding them raw is the v1 bug that
 * showed a 124 % outflow rate. STATSER is **not** an input — it is confronted
 * against the derived figure, on its own window and its own GEPEX perimeter.
 *
 * Carries no destination, port or exporter: those are other entitlement keys.
 */
export default function MarketViewsTab({ data }: { data: OriginMarketViewsResponse }) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const locale = numberLocale(language);
  const { transformation, product_mix, season } = data;

  const win = (w: { from: string | null; to: string | null; months: number }) => {
    const parts = windowParts(w.from, w.to, w.months, locale);
    return parts ? t('origin.window', parts) : '—';
  };
  const beans = product_mix.filter((l) => l.is_bean_equivalent);
  const transformed = product_mix.filter((l) => !l.is_bean_equivalent);
  const transformedShare = transformed.reduce((s, l) => s + (l.share_pct ?? 0), 0);

  return (
    <div>
      <style>{`
        .origin-fall-row { display: grid; grid-template-columns: 150px 1fr 150px;
          gap: 14px; align-items: center; padding: 6px 0; }
        .origin-fall-track { position: relative; height: 28px; background: var(--paper-off); }
        .origin-fall-bar { position: absolute; top: 0; bottom: 0; background: var(--ink);
          transform-origin: left center;
          animation: origin-grow 640ms cubic-bezier(.22,.7,.3,1) backwards; }
        .origin-fall-minus { background:
          repeating-linear-gradient(135deg, var(--ink-mid) 0 2px, transparent 2px 5px),
          var(--ink-light); }
        .origin-fall-total { box-shadow: inset -5px 0 0 var(--color-signal-open); }
        .origin-fall-total.origin-fall-bad { box-shadow: inset -5px 0 0 var(--color-signal-hedge); }
        .origin-fall-val { text-align: right; font-family: var(--font-display);
          font-weight: 400; font-size: 21px; line-height: 1.1; }
        .origin-fall-val small { display: block; font-family: var(--font-mono);
          font-size: 9px; font-weight: 600; letter-spacing: .14em; text-transform: uppercase;
          color: var(--ink-light); margin-top: 3px; }
        .origin-gap-row { display: grid; grid-template-columns: 150px 1fr 150px;
          gap: 14px; align-items: center; padding: 5px 0; }
        @keyframes origin-grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
        @media (prefers-reduced-motion: reduce) {
          .origin-fall-bar { animation: none; }
        }
        @media (max-width: 640px) {
          .origin-fall-row, .origin-gap-row { grid-template-columns: 1fr; gap: 4px;
            padding: 10px 0; border-bottom: 1px dotted var(--rule); }
          .origin-fall-val { text-align: left; font-size: 26px; }
        }
      `}</style>

      {transformation ? (
        <>
          <BlockHeader
            title={t('origin.balance_title')}
            aside={`${
              transformation.perimeter === 'gepex'
                ? t('origin.perimeter_gepex')
                : t('origin.perimeter_all')
            } · ${win(transformation.window)}`}
          />
          <div>
            {buildStages(transformation, t, locale).map((stage, i) => (
              <FallRow key={stage.label} stage={stage} index={i} locale={locale} />
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2.5" style={{ marginTop: 12 }}>
            {/* Published with a flag, never suppressed: stock carries across
                seasons and the purchase master covers fewer operators than
                customs exports. That is what makes it a solde *apparent*. */}
            {transformation.outflow_exceeds_purchases ? (
              <>
                <span style={pillStyle('hedge')}>{t('origin.pill_outflow_exceeds')}</span>
                <Eyebrow tone="subtle" size={9} tracking="0.14em">
                  {t('origin.apparent_note')}
                </Eyebrow>
              </>
            ) : (
              <>
                <span style={pillStyle('open')}>{t('origin.pill_stock_built')}</span>
                <Eyebrow tone="subtle" size={9} tracking="0.14em">
                  {t('origin.rates', {
                    outflow: formatPercent(transformation.outflow_rate_pct, locale),
                    transfo: formatPercent(transformation.transformation_rate_pct, locale),
                  })}
                </Eyebrow>
              </>
            )}
          </div>

          {transformation.statser_confrontation && (
            <div style={{ marginTop: 30 }}>
              <BlockHeader
                title={t('origin.statser_title')}
                aside={`${t('origin.perimeter_gepex')} · ${win(
                  transformation.statser_confrontation.window
                )}`}
              />
              {(
                [
                  {
                    label: t('origin.statser_derived'),
                    value: transformation.statser_confrontation.derived_t,
                    solid: false,
                  },
                  {
                    label: t('origin.statser_declared'),
                    value: transformation.statser_confrontation.declared_t,
                    solid: true,
                  },
                ] as const
              ).map((row) => {
                const max = Math.max(
                  transformation.statser_confrontation!.derived_t,
                  transformation.statser_confrontation!.declared_t,
                  1
                );
                return (
                  <div key={row.label} className="origin-gap-row">
                    <span
                      style={{
                        fontFamily: 'var(--font-editorial)',
                        fontSize: 14,
                        fontWeight: 600,
                        color: 'var(--ink)',
                      }}
                    >
                      {row.label}
                    </span>
                    <span>
                      <span
                        style={{
                          display: 'block',
                          height: 18,
                          width: `${(row.value / max) * 100}%`,
                          background: row.solid ? 'var(--ink)' : 'var(--ink-light)',
                        }}
                      />
                    </span>
                    <span className="origin-fall-val tabular-nums" style={{ fontSize: 17 }}>
                      {formatTonnes(row.value, locale)}
                    </span>
                  </div>
                );
              })}
              <div className="origin-gap-row">
                <span
                  style={{
                    fontFamily: 'var(--font-editorial)',
                    fontSize: 14,
                    fontWeight: 600,
                    color: 'var(--ink)',
                  }}
                >
                  {t('origin.statser_gap')}
                </span>
                <span>
                  <span style={pillStyle('monitor')}>
                    {formatPercent(transformation.statser_confrontation.gap_pct, locale)}
                  </span>
                </span>
                <span className="origin-fall-val tabular-nums" style={{ fontSize: 17 }}>
                  {transformation.statser_confrontation.gap_t < 0 ? '−' : '+'}
                  {formatTonnes(Math.abs(transformation.statser_confrontation.gap_t), locale)}
                  <small>{t('origin.caption_tonnes')}</small>
                </span>
              </div>
            </div>
          )}
        </>
      ) : (
        // The purchase master starts 2020-10; earlier seasons have exports and a
        // mix but no balance. Zeros would read as a measurement that never happened.
        <div style={{ marginBottom: 8 }}>
          <BlockHeader
            title={t('origin.balance_title')}
            aside={t('origin.balance_unavailable_aside')}
          />
          <Eyebrow tone="subtle" size={10} tracking="0.14em">
            {t('origin.balance_unavailable', { season })}
          </Eyebrow>
        </div>
      )}

      <div style={{ marginTop: 30 }}>
        <BlockHeader title={t('origin.mix_title')} aside={t('origin.mix_aside', { season })} />
        <ProductMixBar lines={product_mix} />

        {/* The figure the commercial side will be asked about: the WatchAI report
            counts hors-grade as transformed and prints a higher rate. */}
        <Eyebrow tone="subtle" size={9} tracking="0.12em" style={{ display: 'block', marginTop: 8 }}>
          {t('origin.mix_note', {
            rate: formatPercent(transformedShare, locale),
            horsGrade: formatPercent(
              beans.find((l) => l.product_code === 'HORS_GRADE')?.share_pct,
              locale
            ),
          })}
        </Eyebrow>
      </div>
    </div>
  );
}
