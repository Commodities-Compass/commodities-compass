import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import {
  CalendarIcon,
  NewspaperIcon,
  UserIcon,
  Loader2,
} from "lucide-react";
import { useNews } from "@/hooks/useDashboard";
import { cn } from "@/utils";
import type { ReactNode } from "react";

interface NewsCardProps {
  targetDate?: string;
  className?: string;
}

interface ParsedSections {
  technicals: string;
  fundamentals: string;
  overall: string;
}

// ---------------------------------------------------------------------------
// Inline formatter — regex-based styling for financial text
// ---------------------------------------------------------------------------

interface FormatRule {
  pattern: RegExp;
  render: (match: string, ...groups: string[]) => ReactNode;
}

const FORMAT_RULES: FormatRule[] = [
  // Percentages with sign: +2,30%, -0,06%, (-0,30%)
  {
    pattern: /[(\s]?[+-]\s?\d[\d\s]*,?\d*\s?%\s?\)?/g,
    render: (m) => {
      const isNeg = m.includes("-");
      return (
        <span
          className={cn(
            "font-semibold tabular-nums",
            isNeg && "text-amber-500/80 dark:text-amber-400/70",
          )}
        >
          {m}
        </span>
      );
    },
  },
  // Prices with units: 2 358 GBP/t, 10 $, 3 160 $/t
  {
    pattern: /\d[\d\s]*(?:,\d+)?\s?(?:GBP|USD|\$|€|£)(?:\/t(?:onne)?)?/g,
    render: (m) => <span className="font-semibold tabular-nums">{m}</span>,
  },
  // Standalone numbers with thousands separator or decimals (e.g. 6 757, 100)
  // Only when followed by a unit-like word (contrats, tonnes, mm, jours, bags, pts)
  {
    pattern: /\d[\d\s]*(?:,\d+)?\s?(?:contrats?|tonnes?|pts?|points?|mm|jours?|bags?|lots?)/gi,
    render: (m) => <span className="font-semibold tabular-nums">{m}</span>,
  },
  // Contract codes: CAK26, CCK26, CAN26, etc.
  {
    pattern: /\b(?:CA|CC)[HKNUZ]\d{2}\b/g,
    render: (m) => (
      <span className="font-mono font-semibold text-primary/90">{m}</span>
    ),
  },
  // Market venues / institutions
  {
    pattern: /\b(?:ICE|CFTC|CRA|ICCO|NYSE|CME)\b/g,
    render: (m) => <span className="font-semibold">{m}</span>,
  },
  // Directional signals (bearish + bullish) — bold only, no color
  {
    pattern:
      /\b(?:en repli|baissière?s?|recul|chute|pression vendeuse|liquidation|décote|vulnérable|en hausse|haussière?s?|rebond|reprise|soutien|support)\b/gi,
    render: (m) => <span className="font-semibold">{m}</span>,
  },
  // Temporal markers: À court terme, À moyen terme
  {
    pattern: /[ÀA]\s(?:court|moyen|long)\s+terme/gi,
    render: (m) => <span className="font-semibold italic">{m}</span>,
  },
];

/**
 * Apply formatting rules to a plain-text string.
 * Rules are matched left-to-right, first-match-wins (no overlaps).
 */
function formatText(text: string): ReactNode[] {
  // Collect all matches with their positions and rule
  const allMatches: { start: number; end: number; match: string; rule: FormatRule }[] =
    [];

  for (const rule of FORMAT_RULES) {
    // Reset lastIndex for global regexes
    rule.pattern.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = rule.pattern.exec(text)) !== null) {
      allMatches.push({
        start: m.index,
        end: m.index + m[0].length,
        match: m[0],
        rule,
      });
    }
  }

  // Sort by start position, longer matches first for ties
  allMatches.sort((a, b) => a.start - b.start || b.match.length - a.match.length);

  // Remove overlaps (first-match-wins)
  const filtered: typeof allMatches = [];
  let lastEnd = 0;
  for (const m of allMatches) {
    if (m.start >= lastEnd) {
      filtered.push(m);
      lastEnd = m.end;
    }
  }

  // Build React nodes
  const nodes: ReactNode[] = [];
  let cursor = 0;

  for (let i = 0; i < filtered.length; i++) {
    const { start, end, match, rule } = filtered[i];
    if (start > cursor) {
      nodes.push(text.slice(cursor, start));
    }
    nodes.push(<span key={`fmt-${i}`}>{rule.render(match)}</span>);
    cursor = end;
  }

  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }

  return nodes;
}

function parseSections(content: string, synthesis: string | null): ParsedSections {
  const sections: ParsedSections = {
    technicals: "",
    fundamentals: "",
    overall: "",
  };

  // Section headers — must be on their own line (^) or at string start.
  // SENTIMENT MARCHE must be checked BEFORE bare MARCHE to avoid partial match.
  const sectionMap: { pattern: RegExp; target: keyof ParsedSections }[] = [
    { pattern: /^#{0,3}\s*\**SENTIMENT\s+MARCH[EÉ]\**\.?\s*$/im, target: "overall" },
    { pattern: /^#{0,3}\s*\**MARCH[EÉ]\**\.?\s*$/im, target: "technicals" },
    { pattern: /^#{0,3}\s*\**FONDAMENTAUX\**\.?\s*$/im, target: "fundamentals" },
    { pattern: /^#{0,3}\s*\**OFFRE\**\.?\s*$/im, target: "fundamentals" },
  ];

  // Build a single multiline regex that matches any header line.
  // SENTIMENT MARCHÉ must come first so it's not eaten by bare MARCHÉ.
  const headerLine =
    /^#{0,3}\s*\**(?:SENTIMENT\s+MARCH[EÉ]|MARCH[EÉ]|FONDAMENTAUX|OFFRE)\**\.?\s*$/gim;

  const parts = content.split(headerLine).filter((p) => p.trim());

  // Also extract the headers in order so we can pair them with parts
  const headers = [...content.matchAll(headerLine)].map((m) => m[0].trim());

  // parts[0] is text before the first header (if any), then parts[i+1] follows headers[i]
  if (parts.length > headers.length) {
    // Text before the first header → technicals
    sections.technicals = parts[0].trim();
  }

  for (let i = 0; i < headers.length; i++) {
    const header = headers[i];
    const body = (parts[i + (parts.length > headers.length ? 1 : 0)] ?? "").trim();
    const matched = sectionMap.find((s) => s.pattern.test(header));
    const target = matched?.target ?? "technicals";
    sections[target] += (sections[target] ? "\n\n" : "") + body;
  }

  // Append impact_synthesis to the overall tab
  if (synthesis) {
    sections.overall += (sections.overall ? "\n\n" : "") + synthesis;
  }

  // Fallback: if parsing found nothing, dump everything in technicals
  if (!sections.technicals && !sections.fundamentals && !sections.overall) {
    sections.technicals = content;
    if (synthesis) {
      sections.overall = synthesis;
    }
  }

  return sections;
}

function normalizeTerm(text: string): string {
  return text.replace(/\bpâtes?\b/gi, "masse");
}

function parseKeywords(raw: string | null): string[] {
  if (!raw) return [];
  return raw
    .split(";")
    .map((k) => normalizeTerm(k.trim()))
    .filter(Boolean)
    .slice(0, 8);
}

function SectionContent({ text }: { text: string }) {
  if (!text) {
    return (
      <p className="text-sm text-muted-foreground italic py-4">
        Pas d'information disponible pour cette section.
      </p>
    );
  }

  const paragraphs = normalizeTerm(text)
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);

  return (
    <div className="space-y-3">
      {paragraphs.map((paragraph, i) => (
        <p
          key={i}
          className="text-sm leading-relaxed text-foreground/85"
        >
          {formatText(paragraph)}
        </p>
      ))}
    </div>
  );
}

const TAB_CONFIG = [
  { value: "technicals", label: "Technique", accent: "bg-amber-500/80" },
  { value: "fundamentals", label: "Fondamentaux", accent: "bg-emerald-500/80" },
  { value: "overall", label: "Synthèse", accent: "bg-blue-500/80" },
] as const;

export default function NewsCard({ targetDate, className }: NewsCardProps) {
  const { data: news, isLoading, error } = useNews(targetDate);

  if (isLoading) {
    return (
      <Card className={cn("flex items-center justify-center h-[200px]", className)}>
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Chargement de la revue de presse...</span>
        </div>
      </Card>
    );
  }

  if (error || !news) {
    return (
      <Card className={cn("flex items-center justify-center h-[200px]", className)}>
        <div className="text-center space-y-1">
          <NewspaperIcon className="h-6 w-6 text-muted-foreground/40 mx-auto" />
          <p className="text-sm text-muted-foreground">Aucune revue de presse pour cette date</p>
        </div>
      </Card>
    );
  }

  const sections = parseSections(news.content || "", news.title);
  const keywords = parseKeywords(news.keywords);

  return (
    <Card className={cn("overflow-hidden", className)}>
      {/* Header */}
      <CardHeader className="pb-3">
        <h2 className="text-lg font-semibold tracking-tight">Revue de Presse</h2>
      </CardHeader>

      {/* Tabbed content */}
      <CardContent className="pt-0">
        <Tabs defaultValue="technicals" className="w-full">
          <TabsList className="w-full grid grid-cols-3 mb-4">
            {TAB_CONFIG.map((tab) => (
              <TabsTrigger
                key={tab.value}
                value={tab.value}
                className="text-xs sm:text-sm"
              >
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>

          {TAB_CONFIG.map((tab) => (
            <TabsContent key={tab.value} value={tab.value} className="mt-0">
              {/* Colored accent bar */}
              <div className={cn("h-0.5 rounded-full mb-4", tab.accent)} />
              <div className="max-h-[400px] overflow-y-auto pr-3">
                <SectionContent
                  text={sections[tab.value as keyof ParsedSections]}
                />
              </div>
            </TabsContent>
          ))}
        </Tabs>
      </CardContent>

      {/* Footer: keywords + metadata */}
      <CardFooter className="flex flex-col items-start gap-3 pt-2 border-t">
        {keywords.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {keywords.map((kw) => (
              <Badge
                key={kw}
                variant="secondary"
                className="text-[10px] font-normal px-2 py-0.5"
              >
                {kw}
              </Badge>
            ))}
          </div>
        )}
        <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
          <div className="flex items-center gap-1">
            <CalendarIcon className="h-3.5 w-3.5" />
            <span>{news.date}</span>
          </div>
          {news.author && (
            <div className="flex items-center gap-1">
              <UserIcon className="h-3.5 w-3.5" />
              <span>{news.author}</span>
            </div>
          )}
        </div>
      </CardFooter>
    </Card>
  );
}
