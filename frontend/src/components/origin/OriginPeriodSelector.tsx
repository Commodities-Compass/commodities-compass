import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
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
 * Built as the same Popover + listbox as `MetricDropdown` in Section III rather
 * than a native `<select>`. The native control was the first cut — correct for
 * free on keyboard and screen readers, and an OS picker on a phone — but it
 * renders as the **system** menu: system font, system highlight, none of the
 * magazine vocabulary. In a page whose whole premise is that it reads like a
 * printed briefing, that one control broke the illusion. Matching the shipped
 * dropdown was the cheaper fix than inventing a third look.
 *
 * Deliberately **not** `DateSelector` and **not** wired to
 * `DashboardDateContext`. Origin data is monthly; the rest of the dashboard is
 * daily. Folding a monthly dimension into the daily context is the collision the
 * timeseries-uniqueness rule exists to prevent, and it would refetch this data on
 * every click of the daily picker.
 *
 * What the native element gave away and is restored here by hand: arrow-key
 * navigation, Home/End, and focusing the active option on open. 13 seasons is
 * long enough that stepping through them with Tab alone would be a regression.
 */
export default function OriginPeriodSelector({
  seasons,
  value,
  onChange,
  dataAsOf,
}: OriginPeriodSelectorProps) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const [open, setOpen] = useState(false);
  const listRef = useRef<HTMLUListElement>(null);

  // Open onto the current season rather than the top of a 13-item list.
  useEffect(() => {
    if (!open) return;
    const active = listRef.current?.querySelector<HTMLButtonElement>('[data-active="true"]');
    active?.focus();
  }, [open]);

  const move = (from: number, delta: number | 'first' | 'last') => {
    const items = listRef.current?.querySelectorAll<HTMLButtonElement>('[role="option"]');
    if (!items?.length) return;
    const next =
      delta === 'first'
        ? 0
        : delta === 'last'
          ? items.length - 1
          : Math.min(items.length - 1, Math.max(0, from + delta));
    items[next]?.focus();
  };

  return (
    <div className="flex flex-col items-end gap-1.5" style={{ alignSelf: 'flex-end' }}>
      <style>{`
        .origin-season-trigger:hover { color: var(--ink-mid) !important; }
        .origin-season-option:hover {
          background: var(--paper-off) !important;
          color: var(--ink) !important;
        }
      `}</style>

      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-label={t('origin.campaign_selector_aria')}
            className="origin-season-trigger uppercase inline-flex items-center gap-2"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.2em',
              color: 'var(--ink)',
              background: 'transparent',
              border: 'none',
              borderBottom: '1px solid var(--ink)',
              padding: '8px 0',
              cursor: 'pointer',
              transition: 'color 120ms',
            }}
          >
            <Eyebrow tone="subtle" size={9} tracking="0.18em" style={{ marginRight: 2 }}>
              {t('origin.campaign_selector_label')}
            </Eyebrow>
            {value}
            <ChevronDown style={{ width: 11, height: 11, opacity: 0.65 }} />
          </button>
        </PopoverTrigger>

        <PopoverContent
          align="end"
          sideOffset={4}
          collisionPadding={16}
          className="p-0"
          style={{
            background: 'var(--paper)',
            border: '1px solid var(--ink)',
            borderRadius: 0,
            boxShadow: 'none',
            minWidth: 160,
          }}
        >
          {/* 13 seasons and growing by one a year — the list scrolls inside the
              panel instead of running off the viewport. */}
          <ul
            ref={listRef}
            role="listbox"
            aria-label={t('origin.campaign_selector_aria')}
            style={{
              listStyle: 'none',
              margin: 0,
              padding: 0,
              maxHeight: 264,
              overflowY: 'auto',
            }}
          >
            {seasons.map((s, i) => {
              const isActive = s === value;
              return (
                <li key={s}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={isActive}
                    data-active={isActive ? 'true' : 'false'}
                    onClick={() => {
                      onChange(s);
                      setOpen(false);
                    }}
                    onKeyDown={(e) => {
                      const map = { ArrowDown: 1, ArrowUp: -1 } as const;
                      if (e.key in map) {
                        e.preventDefault();
                        move(i, map[e.key as keyof typeof map]);
                      } else if (e.key === 'Home' || e.key === 'End') {
                        e.preventDefault();
                        move(i, e.key === 'Home' ? 'first' : 'last');
                      }
                    }}
                    className="origin-season-option uppercase w-full text-left"
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 10,
                      fontWeight: isActive ? 700 : 500,
                      letterSpacing: '0.18em',
                      color: isActive ? 'var(--ink)' : 'var(--ink-mid)',
                      background: isActive ? 'var(--paper-off)' : 'transparent',
                      border: 'none',
                      borderBottom: '1px dotted var(--rule)',
                      padding: '10px 14px',
                      cursor: 'pointer',
                      transition: 'background 120ms, color 120ms',
                    }}
                  >
                    {s}
                  </button>
                </li>
              );
            })}
          </ul>
        </PopoverContent>
      </Popover>

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
