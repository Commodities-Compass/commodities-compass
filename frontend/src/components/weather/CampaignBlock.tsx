import type { SeasonStatus } from '@/types/dashboard';
import { Eyebrow } from '@/components/editorial';
import { healthColor } from './shared';

function statusBadge(status: SeasonStatus['status']): { label: string; color: string } {
  if (status === 'completed') return { label: 'Clôturée', color: 'var(--ink-light)' };
  if (status === 'in_progress') return { label: 'En cours', color: 'var(--ink)' };
  return { label: 'À venir', color: 'var(--ink-light)' };
}

interface CampaignBlockProps {
  campaign: string;
  campaignHealth: number | null | undefined;
  seasons: SeasonStatus[];
}

export default function CampaignBlock({ campaign, campaignHealth, seasons }: CampaignBlockProps) {
  return (
    <div style={{ marginBottom: 40 }}>
      {/* Header: campaign title (left) + santé globale (right) */}
      <div
        className="flex items-end justify-between gap-6 mb-6 pb-3"
        style={{ borderBottom: '1px solid var(--ink)' }}
      >
        <div>
          <Eyebrow as="div" tracking="0.2em" style={{ marginBottom: 4 }}>
            Campagne {campaign}
          </Eyebrow>
          <div
            style={{
              fontFamily: 'var(--font-display)',
              fontStyle: 'italic',
              fontWeight: 400,
              fontSize: 22,
              color: 'var(--ink)',
              lineHeight: 1.1,
            }}
          >
            Bilan saisonnier cumulé
          </div>
        </div>
        <div className="text-right">
          <Eyebrow as="div" tone="subtle" size={9} tracking="0.22em" style={{ marginBottom: 2 }}>
            Santé globale
          </Eyebrow>
          <div
            className="tabular-nums"
            style={{
              fontFamily: 'var(--font-display)',
              fontWeight: 700,
              fontSize: 44,
              lineHeight: 1,
              color: healthColor(campaignHealth),
            }}
          >
            {campaignHealth != null ? campaignHealth.toFixed(1) : '—'}
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 14,
                fontWeight: 500,
                color: 'var(--ink-light)',
                marginLeft: 4,
              }}
            >
              /5
            </span>
          </div>
        </div>
      </div>

      {/* Methodology-grid style: one column per saison */}
      {seasons.length > 0 && (
        <div
          className="campaign-grid"
          style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${seasons.length}, minmax(0, 1fr))`,
            gap: 0,
          }}
        >
          {seasons.map((s, i) => {
            const badge = statusBadge(s.status);
            const isLast = i === seasons.length - 1;
            const isActive = s.status === 'in_progress';
            return (
              <div
                key={s.season_name}
                style={{
                  padding: '20px 18px',
                  borderRight: isLast ? 'none' : '1px solid var(--rule)',
                  borderTop: isActive ? `2px solid ${healthColor(s.score)}` : '2px solid transparent',
                  position: 'relative',
                  background: isActive ? 'var(--paper-off)' : 'transparent',
                }}
              >
                <div
                  style={{
                    fontFamily: 'var(--font-display)',
                    fontWeight: 300,
                    fontSize: 36,
                    color: 'var(--rule)',
                    lineHeight: 1,
                    marginBottom: 12,
                  }}
                >
                  {String(i + 1).padStart(2, '0')}
                </div>
                <Eyebrow
                  as="div"
                  tone="primary"
                  size={10}
                  tracking="0.15em"
                  style={{
                    fontFamily: 'var(--font-sans)',
                    fontWeight: 700,
                    marginBottom: 4,
                    lineHeight: 1.3,
                  }}
                >
                  {s.label}
                </Eyebrow>
                <Eyebrow as="div" tone="subtle" size={9} tracking="0.18em" style={{ marginBottom: 12 }}>
                  {s.months_covered}
                </Eyebrow>
                <div
                  className="tabular-nums"
                  style={{
                    fontFamily: 'var(--font-display)',
                    fontWeight: 700,
                    fontSize: 28,
                    lineHeight: 1,
                    color: s.score != null ? healthColor(s.score) : 'var(--ink-light)',
                    marginBottom: 2,
                  }}
                >
                  {s.score != null ? s.score.toFixed(1) : '—'}
                </div>
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10,
                    color: 'var(--ink-light)',
                    marginBottom: 10,
                  }}
                >
                  / 5
                </div>
                <Eyebrow as="div" size={9} tracking="0.18em" style={{ color: badge.color }}>
                  {badge.label}
                </Eyebrow>
              </div>
            );
          })}
        </div>
      )}

      <style>{`
        @media (max-width: 900px) {
          .campaign-grid { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
          .campaign-grid > div { border-right: none !important; border-bottom: 1px solid var(--rule); }
        }
      `}</style>
    </div>
  );
}
