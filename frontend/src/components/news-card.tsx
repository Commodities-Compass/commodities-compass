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
  TrendingUpIcon,
} from "lucide-react";
import { useNews } from "@/hooks/useDashboard";
import SentimentGauges from "@/components/sentiment-gauges";
import { cn } from "@/utils";
import { formatFinancialText } from "@/utils/format-financial-text";

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
  const sections: ParsedSections = {
    technicals: "",
    fundamentals: "",
    overall: "",
  };

  // Section headers — standalone line, optional markdown/bold/trailing punctuation.
  // Tolerates: "MARCHE", "**MARCHÉ**", "## MARCHE :", "FONDAMENTAUX.", etc.
  // SENTIMENT MARCHÉ must be checked BEFORE bare MARCHÉ to avoid partial match.
  const PRE = String.raw`^#{0,3}\s*\**`;
  const POST = String.raw`\**\s*[.:;]?\s*$`;

  const sectionMap: { pattern: RegExp; target: keyof ParsedSections }[] = [
    { pattern: new RegExp(`${PRE}SENTIMENT\\s+MARCH[EÉ]${POST}`, "im"), target: "overall" },
    { pattern: new RegExp(`${PRE}MARCH[EÉ]${POST}`, "im"), target: "technicals" },
    { pattern: new RegExp(`${PRE}FONDAMENTAUX${POST}`, "im"), target: "fundamentals" },
    { pattern: new RegExp(`${PRE}OFFRE${POST}`, "im"), target: "fundamentals" },
  ];

  // Combined regex for splitting — order matters (SENTIMENT MARCHÉ before bare MARCHÉ).
  const headerLine = new RegExp(
    `${PRE}(?:SENTIMENT\\s+MARCH[EÉ]|MARCH[EÉ]|FONDAMENTAUX|OFFRE)${POST}`,
    "gim",
  );

  const parts = content.split(headerLine).filter((p) => p.trim());
  const headers = [...content.matchAll(headerLine)].map((m) => m[0].trim());

  if (parts.length > headers.length) {
    sections.technicals = parts[0].trim();
  }

  for (let i = 0; i < headers.length; i++) {
    const header = headers[i];
    const body = (parts[i + (parts.length > headers.length ? 1 : 0)] ?? "").trim();
    const matched = sectionMap.find((s) => s.pattern.test(header));
    const target = matched?.target ?? "technicals";
    sections[target] += (sections[target] ? "\n\n" : "") + body;
  }

  // Impact synthesis goes into overall — but NOT appended here.
  // It's rendered separately as a top banner in the card layout.

  // Fallback: if parsing found nothing, dump everything in technicals
  if (!sections.technicals && !sections.fundamentals && !sections.overall) {
    sections.technicals = content;
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

// ---------------------------------------------------------------------------
// Keyword chip — detects numeric data points and styles value vs. label
// ---------------------------------------------------------------------------

function KeywordChip({ text }: { text: string }) {
  // Try to find a leading numeric value (e.g. "2 750 GBP/t", "-7%", "surplus 287 kt")
  const numMatch = text.match(
    /^(.*?)(\d[\d\s]*(?:,\d+)?\s?(?:GBP|USD|\$|€|£|%|kt|Mt|t)(?:\/t(?:onne)?)?)(.*?)$/,
  );

  if (numMatch) {
    const [, before, value, after] = numMatch;
    return (
      <Badge
        variant="secondary"
        className="text-[10px] px-2 py-0.5 font-normal"
      >
        {before && <span className="text-muted-foreground">{before}</span>}
        <span className="font-semibold tabular-nums">{value}</span>
        {after && <span className="text-muted-foreground">{after}</span>}
      </Badge>
    );
  }

  return (
    <Badge
      variant="secondary"
      className="text-[10px] font-normal px-2 py-0.5"
    >
      {text}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Section content renderer
// ---------------------------------------------------------------------------

function SectionContent({ text }: { text: string }) {
  if (!text) {
    return (
      <p className="text-sm text-muted-foreground italic py-4">
        Pas d&apos;information disponible pour cette section.
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
          {formatFinancialText(paragraph)}
        </p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Impact synthesis banner — the most actionable piece, shown above tabs
// ---------------------------------------------------------------------------

function ImpactBanner({ text }: { text: string }) {
  if (!text) return null;

  const normalized = normalizeTerm(text);
  // Truncate to ~2 sentences for the banner preview
  const preview =
    normalized.length > 300
      ? normalized.slice(0, normalized.indexOf(".", 250) + 1) || normalized.slice(0, 300) + "…"
      : normalized;

  return (
    <div className="mx-6 mb-4 rounded-lg border border-blue-500/20 bg-blue-500/5 dark:bg-blue-500/10 px-4 py-3">
      <div className="flex items-start gap-2.5">
        <TrendingUpIcon className="h-4 w-4 text-blue-500/70 mt-0.5 shrink-0" />
        <div className="min-w-0">
          <p className="text-[10px] font-medium uppercase tracking-wider text-blue-500/70 mb-1">
            Impact marché
          </p>
          <p className="text-sm leading-relaxed text-foreground/85">
            {formatFinancialText(preview)}
          </p>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab configuration
// ---------------------------------------------------------------------------

const TAB_CONFIG = [
  { value: "technicals", label: "Marché", accent: "bg-amber-500/80" },
  { value: "fundamentals", label: "Fondamentaux", accent: "bg-emerald-500/80" },
  { value: "overall", label: "Sentiment", accent: "bg-violet-500/80" },
] as const;

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

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

  const sections = parseSections(news.content || "");
  const keywords = parseKeywords(news.keywords);

  return (
    <Card className={cn("overflow-hidden", className)}>
      {/* Header */}
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold tracking-tight">Revue de Presse</h2>
          {news.source_count != null && news.total_sources != null && (
            <Badge variant="outline" className="text-[10px] font-normal px-1.5 py-0 h-5">
              {news.source_count}/{news.total_sources} sources
            </Badge>
          )}
        </div>
      </CardHeader>

      {/* Impact synthesis banner — always visible above tabs */}
      <ImpactBanner text={news.title || ""} />

      {/* Sentiment thematic gauges */}
      <div className="px-6 pb-2">
        <SentimentGauges targetDate={targetDate} />
      </div>

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
              <KeywordChip key={kw} text={kw} />
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
