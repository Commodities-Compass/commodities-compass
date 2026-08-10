import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import GroupHeader from './group-header';
import { useRail } from './use-rail';

export interface RailPanel {
  id: string;
  /** Stratum name, e.g. "Technique" — also the folio's "next up" label. */
  name: string;
  /** Data cadence, e.g. "Quotidien". */
  cadence: string;
  content: ReactNode;
}

interface StrataRailProps {
  panels: RailPanel[];
}

const NUMERALS = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII'];

/**
 * Paged presentation of the Section II strata — one stratum at a time.
 *
 * Native CSS scroll-snap, no animation runtime. Panels are full width and never
 * truncate: the "there is more" signal is the folio bar below (roman rail,
 * next-up label, chevrons), not a half-cut gauge.
 *
 * Layout notes:
 * - Panels are flex children in one row, so the track height is the TALLEST
 *   panel for free. No measured min-height, no layout shift between slides.
 * - `overscroll-behavior-x: contain` stops a horizontal trackpad swipe from
 *   triggering browser back-navigation.
 * - `scroll-snap-stop: always` keeps a fast flick from skipping a stratum the
 *   live region never announced.
 * - Gauges are not focusable (Radix `TooltipTrigger asChild` over a div), so
 *   the track itself carries the tab stop and Tab never wanders into an
 *   off-screen panel.
 */
export default function StrataRail({ panels }: StrataRailProps) {
  const { t } = useTranslation();
  const { trackRef, activeIndex, goTo, onKeyDown } = useRail(panels.length);

  const active = panels[activeIndex];
  const next = panels[activeIndex + 1];

  return (
    <div className="strata-rail">
      <div
        ref={trackRef}
        className="strata-rail__track"
        tabIndex={0}
        role="group"
        aria-roledescription={t('market.rail_carousel')}
        aria-label={t('market.rail_label')}
        onKeyDown={onKeyDown}
      >
        {panels.map((panel, i) => (
          <div
            key={panel.id}
            className="strata-rail__panel"
            role="group"
            aria-roledescription={t('market.rail_slide')}
            aria-label={`${i + 1}/${panels.length} — ${panel.name}`}
          >
            <div className="strata-rail__panel-inner">
              <GroupHeader name={panel.name} cadence={panel.cadence} />
              {panel.content}
            </div>
          </div>
        ))}
      </div>

      <div className="strata-rail__folio">
        <div className="strata-rail__numerals">
          {panels.map((panel, i) => (
            <button
              key={panel.id}
              type="button"
              className="strata-rail__numeral"
              aria-current={i === activeIndex ? 'true' : 'false'}
              aria-label={panel.name}
              onClick={() => goTo(i)}
            >
              {NUMERALS[i] ?? String(i + 1)}
            </button>
          ))}
        </div>

        <div className="strata-rail__next-up">
          {next ? (
            <>
              {t('market.rail_next_up')} ›{' '}
              <b>
                {next.name} · {next.cadence}
              </b>
            </>
          ) : (
            <b>{t('market.rail_end')}</b>
          )}
        </div>

        <div className="strata-rail__nav">
          <button
            type="button"
            aria-label={t('market.rail_prev')}
            disabled={activeIndex === 0}
            onClick={() => goTo(activeIndex - 1)}
          >
            ←
          </button>
          <button
            type="button"
            aria-label={t('market.rail_next')}
            disabled={activeIndex === panels.length - 1}
            onClick={() => goTo(activeIndex + 1)}
          >
            →
          </button>
        </div>

        <span className="strata-rail__sr" aria-live="polite">
          {active
            ? t('market.rail_position', {
                name: active.name,
                index: activeIndex + 1,
                total: panels.length,
              })
            : ''}
        </span>
      </div>

      <style>{`
        .strata-rail__track {
          display: flex;
          align-items: stretch;
          overflow-x: auto;
          scroll-snap-type: x mandatory;
          overscroll-behavior-x: contain;
          scroll-behavior: smooth;
          scrollbar-width: none;
        }
        .strata-rail__track::-webkit-scrollbar { display: none; }
        .strata-rail__track:focus-visible {
          outline: 2px solid var(--ink);
          outline-offset: 4px;
        }
        .strata-rail__panel {
          flex: 0 0 100%;
          min-width: 0;
          scroll-snap-align: start;
          scroll-snap-stop: always;
        }
        /* keeps a focus ring on the last gauge from being clipped by overflow */
        .strata-rail__panel-inner { padding-right: 2px; }

        .strata-rail__folio {
          display: flex;
          align-items: center;
          gap: var(--sp-4);
          margin-top: var(--sp-5);
          padding-top: var(--sp-3);
          border-top: 1px solid var(--rule);
        }
        .strata-rail__numerals { display: flex; }
        .strata-rail__numeral {
          min-width: var(--touch-min);
          min-height: var(--touch-min);
          padding: 0;
          background: transparent;
          border: 0;
          border-bottom: 2px solid transparent;
          cursor: pointer;
          line-height: 1;
          font-family: var(--font-display);
          font-size: 12px;
          color: var(--ink-light);
          transition:
            color var(--motion-instant) var(--ease-editorial),
            border-color var(--motion-instant) var(--ease-editorial);
        }
        .strata-rail__numeral[aria-current='true'] {
          color: var(--ink);
          border-bottom-color: var(--ink);
        }
        .strata-rail__numeral:hover { color: var(--ink-dark); }
        .strata-rail__numeral:focus-visible {
          outline: 2px solid var(--ink);
          outline-offset: -3px;
        }

        .strata-rail__next-up {
          flex: 1;
          text-align: right;
          font-family: var(--font-mono);
          font-size: 9.5px;
          line-height: 1.5;
          letter-spacing: 0.18em;
          text-transform: uppercase;
          color: var(--ink-light);
        }
        .strata-rail__next-up b { font-weight: 400; color: var(--ink-mid); }

        .strata-rail__nav { display: flex; gap: var(--sp-1); }
        .strata-rail__nav button {
          width: var(--touch-min);
          height: var(--touch-min);
          background: transparent;
          border: 1px solid var(--rule);
          cursor: pointer;
          line-height: 1;
          font-size: 14px;
          color: var(--ink);
          transition: background var(--motion-instant) var(--ease-editorial);
        }
        .strata-rail__nav button:hover:not(:disabled) { background: var(--paper-off); }
        .strata-rail__nav button:disabled { color: var(--ink-light); cursor: not-allowed; }
        .strata-rail__nav button:focus-visible {
          outline: 2px solid var(--ink);
          outline-offset: 2px;
        }

        .strata-rail__sr {
          position: absolute;
          width: 1px;
          height: 1px;
          overflow: hidden;
          clip-path: inset(50%);
          white-space: nowrap;
        }

        /* Phone density pass. Scoped to the rail so the Press Review sentiment
           gauges keep the desktop rhythm. Saves ~14px per gauge + 10px per row
           gap, which is what lets a stratum plus its folio fit one screen.
           --gauge-ruler-top only gives back 2px: below 26px the marker triangle
           collides with the value label stacked above it. */
        @media (max-width: 767px) {
          .strata-rail__panel {
            --gauge-label-gap: 8px;
            --gauge-ruler-top: 26px;
            --gauge-zone-gap: 4px;
            --field-gap: 14px;
          }
        }

        @media (max-width: 767px) {
          .strata-rail__folio { flex-wrap: wrap; gap: var(--sp-2) var(--sp-3); }
          .strata-rail__next-up {
            order: 3;
            flex-basis: 100%;
            text-align: left;
            /* On a phone the label owns its own row, and the longest stratum
               name ("Positionnement & offre · Hebdomadaire") wraps to two
               lines. Reserve both so the folio does not grow by a line as the
               user pages — measured at 15px of shift before this. */
            min-height: 29px;
            min-height: 2lh;
          }
        }

        @media (prefers-reduced-motion: reduce) {
          .strata-rail__track { scroll-behavior: auto; }
          .strata-rail__numeral,
          .strata-rail__nav button { transition-duration: 0.001ms; }
        }
      `}</style>
    </div>
  );
}
