import GaugeIndicator from '@/components/gauge-indicator';
import EditorialTabs from '@/components/editorial-tabs';
import SectionHeader from '@/components/section-header';
import { Loader2 } from 'lucide-react';
import { useIndicatorsGrid, useRecommendations } from '@/hooks/useDashboard';
import { parseConclusion, formatRecoText } from '@/utils/recommendation-parser';

interface MarketAnalysisProps {
  targetDate?: string;
  className?: string;
}

const INDICATOR_KEYS = ['macd', 'volOi', 'rsi', 'percentK', 'atr'] as const;

function EditorialParagraph({ children, dropcap = false }: { children: React.ReactNode; dropcap?: boolean }) {
  return (
    <p
      style={{
        fontFamily: 'var(--font-editorial)',
        fontSize: 15,
        lineHeight: 1.75,
        color: 'var(--ink-dark)',
        textAlign: 'justify',
        marginBottom: 14,
        hyphens: 'auto',
        WebkitHyphens: 'auto',
      }}
      className={dropcap ? 'has-dropcap' : undefined}
    >
      {children}
    </p>
  );
}

function ParagraphsList({ items }: { items: string[] }) {
  if (items.length === 0) {
    return (
      <p style={{ color: 'var(--ink-light)', fontStyle: 'italic', fontSize: 14 }}>
        Aucune information pour cette section.
      </p>
    );
  }
  return (
    <div>
      {items.map((p, i) => (
        <EditorialParagraph key={i} dropcap={i === 0}>
          {formatRecoText(p)}
        </EditorialParagraph>
      ))}
      <style>{`
        .has-dropcap::first-letter {
          font-family: var(--font-display);
          font-size: 56px;
          font-weight: 700;
          float: left;
          line-height: 0.85;
          padding-right: 8px;
          padding-top: 4px;
          color: var(--ink);
        }
      `}</style>
    </div>
  );
}

function Watchlist({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <aside
      style={{
        padding: '18px 18px 16px',
        background: 'var(--paper-off)',
        borderLeft: '2px solid var(--ink)',
      }}
    >
      <div
        className="uppercase"
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.22em',
          color: 'var(--ink-mid)',
          marginBottom: 12,
          paddingBottom: 8,
          borderBottom: '1px dotted var(--rule)',
        }}
      >
        À surveiller
      </div>
      <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {items.map((item, i) => (
          <li
            key={i}
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: 13,
              lineHeight: 1.55,
              color: 'var(--ink-dark)',
              marginBottom: 10,
              paddingLeft: 16,
              position: 'relative',
            }}
          >
            <span
              aria-hidden
              style={{
                position: 'absolute',
                left: 0,
                top: 9,
                width: 8,
                height: 1,
                background: 'var(--ink-mid)',
              }}
            />
            {formatRecoText(item)}
          </li>
        ))}
      </ul>
    </aside>
  );
}

export default function MarketAnalysis({ targetDate, className }: MarketAnalysisProps) {
  const { data: gridData, isLoading: gridLoading } = useIndicatorsGrid(targetDate);
  const { data: recoData, isLoading: recoLoading } = useRecommendations(targetDate);

  const isLoading = gridLoading || recoLoading;
  const indicators = gridData?.indicators;
  const recommendations = recoData?.recommendations;
  const parsed = recommendations ? parseConclusion(recommendations) : { analysis: [], watchlist: [] };

  // Split analysis into 3 buckets — same distribution as before
  const split3 = (arr: string[]): [string[], string[], string[]] => {
    if (arr.length === 0) return [[], [], []];
    const per = Math.ceil(arr.length / 3);
    return [arr.slice(0, per), arr.slice(per, per * 2), arr.slice(per * 2)];
  };
  const [bucketReco, bucketSupply, bucketTechnical] = split3(parsed.analysis);

  const tabs = [
    { id: 'reco', label: 'Recommandation', badge: bucketReco.length > 0 ? String(bucketReco.length) : undefined },
    { id: 'supply', label: 'Supply & Momentum', badge: bucketSupply.length > 0 ? String(bucketSupply.length) : undefined },
    { id: 'technical', label: 'Technical Outlook', badge: bucketTechnical.length > 0 ? String(bucketTechnical.length) : undefined },
  ];

  return (
    <div className={className}>
      {/* ===== SECTION II — Market Analysis ===== */}
      <section style={{ padding: '32px 0 24px' }}>
        <SectionHeader numeral="II" title="Market Analysis" />

        {/* Sub-block: Compass Gauges (snapshot) — comes first */}
        <div style={{ marginBottom: 32 }}>
          <div
            className="uppercase mb-4"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.22em',
              color: 'var(--ink-mid)',
            }}
          >
            Compass Gauges
          </div>
          {indicators ? (
            <div
              className="gauges-row"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(5, minmax(0, 1fr))',
                gap: 24,
                alignItems: 'start',
              }}
            >
              {INDICATOR_KEYS.map((key) =>
                indicators[key] ? (
                  <GaugeIndicator
                    key={key}
                    value={indicators[key].value}
                    min={indicators[key].min}
                    max={indicators[key].max}
                    label={indicators[key].label}
                    ranges={indicators[key].ranges}
                  />
                ) : null,
              )}
            </div>
          ) : (
            <p style={{ color: 'var(--ink-light)', fontSize: 14, textAlign: 'center' }}>
              Aucun indicateur disponible.
            </p>
          )}
        </div>

        {/* Dotted separator between gauges and editorial body */}
        <div
          aria-hidden
          style={{
            height: 1,
            borderTop: '1px dotted var(--rule)',
            marginBottom: 28,
          }}
        />

        {/* Sub-block: Analysis (tabs + sidebar) */}
        {isLoading ? (
          <div className="flex items-center justify-center py-16" style={{ color: 'var(--ink-light)' }}>
            <Loader2 className="h-5 w-5 animate-spin mr-2" />
            <span className="text-sm">Chargement de l'analyse...</span>
          </div>
        ) : (
          <div
            className="market-grid"
            style={{
              display: 'grid',
              gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)',
              gap: 40,
            }}
          >
            {/* Left: tabbed content */}
            <div>
              <EditorialTabs
                tabs={tabs}
                panels={{
                  reco: <ParagraphsList items={bucketReco} />,
                  supply: <ParagraphsList items={bucketSupply} />,
                  technical: <ParagraphsList items={bucketTechnical} />,
                }}
              />
            </div>

            {/* Right rail: À surveiller */}
            <Watchlist items={parsed.watchlist} />
          </div>
        )}
      </section>

      <style>{`
        @media (max-width: 1023px) {
          .market-grid { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 767px) {
          .gauges-row { grid-template-columns: repeat(3, minmax(0, 1fr)) !important; }
        }
        @media (max-width: 479px) {
          .gauges-row { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; gap: 16px !important; }
        }
      `}</style>
    </div>
  );
}
