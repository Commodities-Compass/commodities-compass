import { useTranslation } from 'react-i18next';
import { ChevronDown } from 'lucide-react';
import { Eyebrow } from '@/components/editorial';
import { useLanguage } from '@/hooks/useLanguage';
import { numberLocale } from './shared';

interface OriginPeriodSelectorProps {
  seasons: string[];
  value: string;
  onChange: (season: string) => void;
  /** Stamped from `data_as_of` — always visible (decision #15). */
  dataAsOf: string;
}

/**
 * Season selector for Section VI, anchored top-right in the section rule.
 *
 * Deliberately **not** `DateSelector` and **not** wired to
 * `DashboardDateContext`. Origin data is monthly; the rest of the dashboard is
 * daily. Folding a monthly dimension into the daily context is the collision the
 * timeseries-uniqueness rule exists to prevent, and it would refetch this data on
 * every click of the daily picker.
 *
 * A native `<select>` rather than a Radix popover: 13 seasons is a plain list, it
 * is keyboard- and screen-reader-correct for free, and it renders as the OS
 * picker on the phone this section has to work on. It is dressed as a control —
 * boxed, with a chevron and an inverting hover — because an underlined value
 * alone read as a printed heading rather than something you could change.
 */
export default function OriginPeriodSelector({
  seasons,
  value,
  onChange,
  dataAsOf,
}: OriginPeriodSelectorProps) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  return (
    <div className="flex flex-col items-end gap-1.5" style={{ alignSelf: 'flex-end' }}>
      <style>{`
        .origin-season { position: relative; display: inline-flex; align-items: center; gap: 6px;
          border: 1px solid var(--ink); background: var(--paper-off); padding: 5px 9px 5px 11px;
          cursor: pointer; transition: background 140ms ease, color 140ms ease; color: var(--ink); }
        .origin-season:hover, .origin-season:focus-within { background: var(--ink); color: var(--paper); }
        .origin-season:focus-within { outline: 2px solid var(--ink); outline-offset: 2px; }
        .origin-season select { font-family: var(--font-mono); font-size: 12.5px; font-weight: 600;
          letter-spacing: .06em; color: inherit; background: transparent; border: none;
          padding: 0; margin: 0; cursor: pointer; appearance: none; outline: none; }
        /* The list itself is OS-rendered and never inherits the inverted colours. */
        .origin-season select option { color: var(--ink); background: var(--paper); }
      `}</style>

      <span className="origin-season">
        <Eyebrow tone="subtle" size={9} tracking="0.2em" style={{ color: 'inherit', opacity: 0.75 }}>
          {t('origin.campaign_selector_label')}
        </Eyebrow>
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-label={t('origin.campaign_selector_aria')}
        >
          {seasons.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <ChevronDown aria-hidden size={13} strokeWidth={2.2} style={{ flexShrink: 0 }} />
      </span>

      {/* Staleness is made visible to the reader rather than alerted to ops —
          ingestion is manual, so there is no execution log to watch. */}
      <Eyebrow tone="subtle" size={9} tracking="0.18em">
        {t('origin.data_as_of', {
          date: new Date(`${dataAsOf}T00:00:00`).toLocaleDateString(numberLocale(language), {
            day: 'numeric',
            month: 'short',
            year: 'numeric',
          }),
        })}
      </Eyebrow>
    </div>
  );
}
