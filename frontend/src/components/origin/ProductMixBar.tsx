import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Eyebrow } from '@/components/editorial';
import { useLanguage } from '@/hooks/useLanguage';
import type { ProductMixLine } from '@/types/origin';
import { formatPercent, formatTonnes, mixShade, numberLocale } from './shared';

/**
 * Product-mix bar for the Market tab.
 *
 * Six segments in a greyscale brand is the hard case: a flat opacity ramp made
 * neighbours indistinguishable and, worse, the legend carried no swatches — so
 * even a perfectly contrasted bar could not be mapped back to a product name.
 * Three things fix it, in order of how much they carry:
 *
 *  1. **Swatches in the legend.** The static reading works with no interaction
 *     at all, which is the only reading a printed PDF or a screenshot has.
 *  2. **A per-family lightness ramp + paper separators** so adjacent segments
 *     are separated both tonally and by a hard edge.
 *  3. **Hover/focus** for the precise figure, dimming the rest of the bar.
 *
 * The bar is `aria-hidden`: it restates the legend, which is real text. The
 * legend entries carry `tabIndex` so a keyboard reader reaches the same detail
 * line a mouse reader gets — they are not buttons, because nothing is actioned.
 */
export default function ProductMixBar({ lines }: { lines: ProductMixLine[] }) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const locale = numberLocale(language);
  const [active, setActive] = useState<string | null>(null);

  // Shade is assigned per family, so the two halves of the bar stay legible as
  // halves however many products each one holds.
  const rank = new Map<string, { shade: string }>();
  for (const isBean of [true, false]) {
    const family = lines.filter((l) => l.is_bean_equivalent === isBean);
    family.forEach((l, i) =>
      rank.set(l.product_code, { shade: mixShade(i, family.length, isBean) })
    );
  }

  const shown = active ? lines.find((l) => l.product_code === active) : null;
  const label = (code: string) => code.replace(/_/g, ' ');

  return (
    <div onMouseLeave={() => setActive(null)}>
      <div
        aria-hidden
        style={{ display: 'flex', height: 30, background: 'var(--paper-off)' }}
      >
        {lines.map((line) => {
          const on = active === line.product_code;
          return (
            <span
              key={line.product_code}
              onMouseEnter={() => setActive(line.product_code)}
              style={{
                width: `${line.share_pct ?? 0}%`,
                background: rank.get(line.product_code)?.shade,
                // A hard paper edge, so two adjacent shades never bleed into
                // one another at small widths.
                boxShadow: 'inset -1.5px 0 0 var(--paper)',
                opacity: active && !on ? 0.28 : 1,
                transform: on ? 'scaleY(1.18)' : 'none',
                transition: 'opacity 140ms ease, transform 140ms ease',
              }}
            />
          );
        })}
      </div>

      <div className="flex flex-wrap gap-x-5 gap-y-1.5" style={{ marginTop: 11 }}>
        {lines.map((line) => {
          const on = active === line.product_code;
          return (
            <span
              key={line.product_code}
              tabIndex={0}
              onMouseEnter={() => setActive(line.product_code)}
              onFocus={() => setActive(line.product_code)}
              onBlur={() => setActive(null)}
              className="flex items-center gap-1.5 outline-none"
              style={{
                cursor: 'default',
                opacity: active && !on ? 0.4 : 1,
                transition: 'opacity 140ms ease',
                borderBottom: `1px solid ${on ? 'var(--ink)' : 'transparent'}`,
                paddingBottom: 2,
              }}
            >
              <span
                aria-hidden
                style={{
                  width: 10,
                  height: 10,
                  flexShrink: 0,
                  background: rank.get(line.product_code)?.shade,
                  outline: '1px solid var(--rule)',
                }}
              />
              <Eyebrow tone="muted" size={9} tracking="0.12em">
                {label(line.product_code)} {formatPercent(line.share_pct, locale)}
              </Eyebrow>
            </span>
          );
        })}
      </div>

      {/* Reserved height: the line appears on hover, and a row that grows would
          push the note below it down on every pointer move. */}
      <div style={{ minHeight: 20, marginTop: 8 }}>
        {shown ? (
          <span
            className="tabular-nums"
            style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--ink)' }}
          >
            <strong style={{ letterSpacing: '0.1em' }}>{label(shown.product_code)}</strong>
            {' · '}
            {formatTonnes(shown.export_tonnes, locale)} t
            {' · '}
            {formatPercent(shown.share_pct, locale)}
          </span>
        ) : (
          <Eyebrow tone="subtle" size={9} tracking="0.14em">
            {t('origin.mix_hover_hint')}
          </Eyebrow>
        )}
      </div>
    </div>
  );
}
