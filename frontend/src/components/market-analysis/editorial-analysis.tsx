import EditorialTabs from '@/components/editorial-tabs';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { formatRecoText } from '@/utils/recommendation-parser';

interface EditorialAnalysisProps {
  isLoading: boolean;
  bucketReco: string[];
  bucketSupply: string[];
  bucketTechnical: string[];
  watchlist: string[];
}

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
  const { t } = useTranslation();
  if (items.length === 0) {
    return (
      <p style={{ color: 'var(--ink-light)', fontStyle: 'italic', fontSize: 14 }}>
        {t('common.empty_section')}
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
  const { t } = useTranslation();
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
        {t('market.watchlist_title')}
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

export default function EditorialAnalysis({
  isLoading,
  bucketReco,
  bucketSupply,
  bucketTechnical,
  watchlist,
}: EditorialAnalysisProps) {
  const { t } = useTranslation();
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16" style={{ color: 'var(--ink-light)' }}>
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        <span className="text-sm">{t('loading.editorial_analysis')}</span>
      </div>
    );
  }

  const tabs = [
    { id: 'reco', label: t('market.tab_recommendation'), badge: bucketReco.length > 0 ? String(bucketReco.length) : undefined },
    { id: 'supply', label: t('market.tab_supply'), badge: bucketSupply.length > 0 ? String(bucketSupply.length) : undefined },
    { id: 'technical', label: t('market.tab_technical'), badge: bucketTechnical.length > 0 ? String(bucketTechnical.length) : undefined },
  ];

  return (
    <div
      className="market-grid"
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)',
        gap: 40,
      }}
    >
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
      <Watchlist items={watchlist} />
    </div>
  );
}
