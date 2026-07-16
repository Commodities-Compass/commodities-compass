import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNews } from '@/hooks/useDashboard';
import { formatFinancialText } from '@/utils/format-financial-text';
import SentimentGauges from '@/components/sentiment-gauges';
import EditorialTabs from '@/components/editorial-tabs';
import SectionHeader from '@/components/section-header';
import { Eyebrow } from '@/components/editorial';

interface NewsCardProps {
  targetDate?: string;
  className?: string;
}

interface ParsedSections {
  technicals: string;
  fundamentals: string;
  overall: string;
}

function parseSections(content: string): ParsedSections {
  const sections: ParsedSections = { technicals: '', fundamentals: '', overall: '' };
  const PRE = String.raw`^#{0,3}\s*\**`;
  const POST = String.raw`\**\s*[.:;]?\s*$`;

  // Section headers are language-agnostic: FR (OFFRE / FONDAMENTAUX / MARCHÉ /
  // SENTIMENT MARCHÉ) and EN (SUPPLY / FUNDAMENTALS / MARKET / MARKET SENTIMENT).
  // The two-word "… SENTIMENT" variants MUST precede the bare MARKET/MARCHÉ so
  // the more specific header wins.
  const sectionMap: { pattern: RegExp; target: keyof ParsedSections }[] = [
    { pattern: new RegExp(`${PRE}(?:SENTIMENT\\s+MARCH[EÉ]|MARKET\\s+SENTIMENT)${POST}`, 'im'), target: 'overall' },
    { pattern: new RegExp(`${PRE}(?:MARCH[EÉ]|MARKET)${POST}`, 'im'), target: 'technicals' },
    { pattern: new RegExp(`${PRE}(?:FONDAMENTAUX|FUNDAMENTALS)${POST}`, 'im'), target: 'fundamentals' },
    { pattern: new RegExp(`${PRE}(?:OFFRE|SUPPLY)${POST}`, 'im'), target: 'fundamentals' },
  ];

  const headerLine = new RegExp(
    `${PRE}(?:SENTIMENT\\s+MARCH[EÉ]|MARKET\\s+SENTIMENT|MARCH[EÉ]|MARKET|FONDAMENTAUX|FUNDAMENTALS|OFFRE|SUPPLY)${POST}`,
    'gim',
  );

  const parts = content.split(headerLine).filter((p) => p.trim());
  const headers = [...content.matchAll(headerLine)].map((m) => m[0].trim());

  if (parts.length > headers.length) sections.technicals = parts[0].trim();

  for (let i = 0; i < headers.length; i++) {
    const header = headers[i];
    const body = (parts[i + (parts.length > headers.length ? 1 : 0)] ?? '').trim();
    const matched = sectionMap.find((s) => s.pattern.test(header));
    const target = matched?.target ?? 'technicals';
    sections[target] += (sections[target] ? '\n\n' : '') + body;
  }

  if (!sections.technicals && !sections.fundamentals && !sections.overall) {
    sections.technicals = content;
  }

  return sections;
}

function normalizeTerm(text: string): string {
  return text.replace(/\bpâtes?\b/gi, 'masse');
}

function parseKeywords(raw: string | null): string[] {
  if (!raw) return [];
  return raw.split(';').map((k) => normalizeTerm(k.trim())).filter(Boolean).slice(0, 10);
}

function ArticleBody({ body, attribution }: { body: string; attribution?: string }) {
  const { t } = useTranslation();
  if (!body) {
    return (
      <p style={{ color: 'var(--ink-light)', fontStyle: 'italic', fontSize: 14 }}>
        {t('common.empty_section')}
      </p>
    );
  }
  const paragraphs = normalizeTerm(body).split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  return (
    <article>
      <div style={{ position: 'relative', paddingLeft: 32 }}>
        <span
          aria-hidden
          style={{
            position: 'absolute',
            left: 0,
            top: 6,
            fontFamily: 'var(--font-display)',
            fontSize: 'clamp(36px, 6vw, 64px)',
            fontWeight: 900,
            color: 'var(--rule)',
            lineHeight: 0.6,
            userSelect: 'none',
          }}
        >
          “
        </span>
        {paragraphs.map((p, i) => (
          <p
            key={i}
            style={{
              fontFamily: 'var(--font-editorial)',
              fontStyle: 'italic',
              fontSize: 16,
              lineHeight: 1.7,
              color: 'var(--ink-dark)',
              marginBottom: 14,
              textAlign: 'justify',
              hyphens: 'auto',
              WebkitHyphens: 'auto',
            }}
          >
            {formatFinancialText(p)}
          </p>
        ))}
        {attribution && (
          <div
            className="uppercase"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.18em',
              color: 'var(--ink-light)',
              marginTop: 8,
              paddingTop: 8,
              borderTop: '1px dotted var(--rule)',
            }}
          >
            — {attribution}
          </div>
        )}
      </div>
    </article>
  );
}

export default function NewsCard({ targetDate, className }: NewsCardProps) {
  const { t } = useTranslation();
  const { data: news, isLoading, error } = useNews(targetDate);

  if (isLoading) {
    return (
      <section className={className} style={{ padding: '24px 0' }}>
        <SectionHeader numeral="IV" title="Press Review" />
        <div className="flex items-center justify-center py-16" style={{ color: 'var(--ink-light)' }}>
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          <span className="text-sm">{t('loading.news_review')}</span>
        </div>
      </section>
    );
  }

  if (error || !news) {
    return (
      <section className={className} style={{ padding: '24px 0' }}>
        <SectionHeader numeral="IV" title="Press Review" />
        <p style={{ color: 'var(--ink-light)', textAlign: 'center', fontSize: 14 }}>
          {t('news.empty_state')}
        </p>
      </section>
    );
  }

  const sections = parseSections(news.content || '');
  const keywords = parseKeywords(news.keywords);
  const attribution = `Compass Press Desk · ${news.date}${news.source_count != null && news.total_sources != null ? ` · ${news.source_count}/${news.total_sources} sources` : ''}`;

  return (
    <section className={className} style={{ padding: '24px 0' }}>
      <SectionHeader numeral="IV" title="Press Review" />

      {/* Horizon disclaimer — forward-looking risk/sentiment, distinct from the
          current-conditions Weather section (avoids the "drought vs normal" read). */}
      <Eyebrow
        as="p"
        tone="subtle"
        size={9}
        tracking="0.18em"
        style={{ marginTop: -10, marginBottom: 22 }}
      >
        {t('news.horizon_subtitle')}
      </Eyebrow>

      {/* Sentiment thematic gauges */}
      <div style={{ marginBottom: 28 }}>
        <div
          className="uppercase mb-4"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: '0.18em',
            color: 'var(--ink-mid)',
          }}
        >
          {t('news.thematic_sentiment_title')}
        </div>
        <SentimentGauges targetDate={targetDate} />
      </div>

      <EditorialTabs
        tabs={[
          { id: 'technicals', label: t('news.tab_technicals') },
          { id: 'fundamentals', label: t('news.tab_fundamentals') },
          { id: 'overall', label: t('news.tab_overall') },
        ]}
        panels={{
          technicals: <ArticleBody body={sections.technicals} attribution={attribution} />,
          fundamentals: <ArticleBody body={sections.fundamentals} />,
          overall: <ArticleBody body={sections.overall} />,
        }}
      />

      {/* Impact synthesis (titre/synthèse) */}
      {news.title && (
        <div
          style={{
            marginTop: 12,
            padding: '14px 18px',
            background: 'var(--paper-off)',
            borderLeft: '3px solid var(--ink)',
          }}
        >
          <div
            className="uppercase mb-2"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.2em',
              color: 'var(--ink-mid)',
            }}
          >
            {t('news.impact_label')}
          </div>
          <p
            style={{
              fontFamily: 'var(--font-editorial)',
              fontSize: 15,
              lineHeight: 1.6,
              color: 'var(--ink-dark)',
            }}
          >
            {formatFinancialText(normalizeTerm(news.title))}
          </p>
        </div>
      )}

      {/* Keywords */}
      {keywords.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-4">
          {keywords.map((kw) => (
            <span
              key={kw}
              className="uppercase"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                fontWeight: 500,
                letterSpacing: '0.1em',
                color: 'var(--ink-mid)',
                padding: '4px 8px',
                border: '1px solid var(--rule)',
                background: 'var(--paper)',
              }}
            >
              {kw}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
