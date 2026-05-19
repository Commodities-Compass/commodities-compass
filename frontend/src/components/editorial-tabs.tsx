import { useId, useState, type ReactNode, type KeyboardEvent } from 'react';

export interface EditorialTab {
  id: string;
  label: string;
  badge?: string;
  disabled?: boolean;
}

interface EditorialTabsProps {
  tabs: EditorialTab[];
  defaultActiveId?: string;
  activeId?: string;
  onChange?: (id: string) => void;
  className?: string;
  panels: Record<string, ReactNode>;
  /**
   * Density of the tab strip.
   * - 'lg' : larger uppercase labels, used as primary section nav (default)
   * - 'sm' : tighter for nested sub-tabs
   */
  density?: 'lg' | 'sm';
}

export default function EditorialTabs({
  tabs,
  defaultActiveId,
  activeId: controlledActiveId,
  onChange,
  className,
  panels,
  density = 'lg',
}: EditorialTabsProps) {
  const baseId = useId();
  const initial = defaultActiveId ?? tabs[0]?.id;
  const [internalActive, setInternalActive] = useState<string>(initial ?? '');

  const activeId = controlledActiveId ?? internalActive;

  const select = (id: string) => {
    if (!controlledActiveId) setInternalActive(id);
    onChange?.(id);
  };

  const onKey = (e: KeyboardEvent<HTMLButtonElement>, idx: number) => {
    const enabled = tabs.map((t, i) => (t.disabled ? -1 : i)).filter((i) => i >= 0);
    const cur = enabled.indexOf(idx);
    if (e.key === 'ArrowRight') {
      e.preventDefault();
      const next = enabled[(cur + 1) % enabled.length];
      select(tabs[next].id);
      document.getElementById(`${baseId}-tab-${tabs[next].id}`)?.focus();
    }
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      const prev = enabled[(cur - 1 + enabled.length) % enabled.length];
      select(tabs[prev].id);
      document.getElementById(`${baseId}-tab-${tabs[prev].id}`)?.focus();
    }
  };

  const labelSize = density === 'sm' ? 14 : 17;
  const gap = density === 'sm' ? 20 : 32;
  const padY = density === 'sm' ? 8 : 12;
  const underline = 2;

  return (
    <div className={className}>
      <style>{`
        .editorial-tab:focus-visible {
          outline: 1px dashed var(--ink-mid);
          outline-offset: 2px;
        }
        .editorial-tab[data-active="false"]:not(:disabled):hover {
          color: var(--ink-mid) !important;
        }
      `}</style>
      <div
        role="tablist"
        aria-orientation="horizontal"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap,
          borderBottom: '1px solid var(--rule)',
        }}
      >
        {tabs.map((t, idx) => {
          const isActive = t.id === activeId;
          return (
            <button
              key={t.id}
              id={`${baseId}-tab-${t.id}`}
              role="tab"
              type="button"
              aria-selected={isActive}
              aria-controls={`${baseId}-panel-${t.id}`}
              disabled={t.disabled}
              tabIndex={isActive ? 0 : -1}
              onClick={() => !t.disabled && select(t.id)}
              onKeyDown={(e) => onKey(e, idx)}
              className="editorial-tab inline-flex items-baseline gap-2"
              data-active={isActive ? 'true' : 'false'}
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: labelSize,
                fontWeight: 600,
                fontStyle: 'italic',
                letterSpacing: '0.005em',
                color: t.disabled
                  ? 'var(--ink-light)'
                  : isActive
                    ? 'var(--ink)'
                    : 'var(--ink-light)',
                background: 'transparent',
                border: 'none',
                cursor: t.disabled ? 'not-allowed' : 'pointer',
                padding: `${padY}px 0`,
                borderBottom: isActive ? `${underline}px solid var(--ink)` : `${underline}px solid transparent`,
                marginBottom: -1,
                transition: 'color 150ms ease, border-color 150ms ease',
              }}
            >
              {t.label}
              {t.badge && (
                <span
                  className="tabular-nums"
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: density === 'sm' ? 8 : 9,
                    fontWeight: 500,
                    letterSpacing: '0.05em',
                    color: isActive ? 'var(--ink-mid)' : 'var(--ink-light)',
                    padding: 0,
                    background: 'transparent',
                    border: 'none',
                  }}
                >
                  ({t.badge})
                </span>
              )}
            </button>
          );
        })}
      </div>

      {tabs.map((t) => {
        const isActive = t.id === activeId;
        return (
          <div
            key={t.id}
            id={`${baseId}-panel-${t.id}`}
            role="tabpanel"
            aria-labelledby={`${baseId}-tab-${t.id}`}
            hidden={!isActive}
            style={{ paddingTop: 20 }}
          >
            {panels[t.id]}
          </div>
        );
      })}
    </div>
  );
}
