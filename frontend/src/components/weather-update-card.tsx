import { useState } from "react";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  CloudRainIcon,
  Loader2,
  CalendarIcon,
  ChevronDown,
  BotIcon,
} from "lucide-react";
import { useWeather } from "@/hooks/useDashboard";
import { cn } from "@/utils";
import { formatFinancialText } from "@/utils/format-financial-text";
import type {
  SeasonStatus,
  LocationStressHistory,
} from "@/types/dashboard";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function scoreColor(score: number | null | undefined): string {
  if (score == null) return "bg-muted text-muted-foreground";
  if (score >= 3.5) return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300";
  if (score >= 2.5) return "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300";
  return "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300";
}

function statusDotColor(status: string): string {
  if (status === "normal") return "bg-emerald-500";
  if (status === "degraded") return "bg-amber-500";
  return "bg-red-500";
}

function statusLabel(status: string): string {
  if (status === "normal") return "normal";
  if (status === "degraded") return "dégradé";
  return "stress";
}

function scoreBarColor(score: number | null | undefined): string {
  if (score == null) return "bg-muted-foreground";
  if (score >= 3.5) return "bg-emerald-500";
  if (score >= 2.5) return "bg-amber-500";
  return "bg-red-500";
}

function seasonStatusIcon(status: string): string {
  if (status === "completed") return "bg-foreground/20";
  if (status === "in_progress") return "bg-primary";
  return "bg-muted";
}

function countryFlag(country: string): string {
  return country === "CIV" ? "\u{1F1E8}\u{1F1EE}" : "\u{1F1EC}\u{1F1ED}";
}

function timelineDotColor(status: string): string {
  if (status === "normal") return "bg-emerald-500";
  if (status === "degraded") return "bg-amber-500";
  return "bg-red-500";
}

// ---------------------------------------------------------------------------
// InfoHint — discreet contextual note
// ---------------------------------------------------------------------------

function InfoHint({ children }: { children: string }) {
  return (
    <p className="text-[10px] text-muted-foreground/50 italic mt-0.5">
      {children}
    </p>
  );
}

// ---------------------------------------------------------------------------
// MiniTimeline — 7-dot history per zone
// ---------------------------------------------------------------------------

function MiniTimeline({ history }: { history: string[] }) {
  return (
    <div className="flex items-center gap-0.5">
      {history.map((status, i) => (
        <div
          key={i}
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            timelineDotColor(status),
          )}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ZoneList — per-location rows with timeline + streak
// ---------------------------------------------------------------------------

function ZoneRow({
  zone,
  harmattanDays,
}: {
  zone: LocationStressHistory;
  harmattanDays?: number | null;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex items-center gap-2 py-1 text-xs">
          <div
            className={cn(
              "h-2 w-2 rounded-full shrink-0",
              statusDotColor(zone.current_status),
            )}
          />
          <span className="w-[72px] shrink-0 font-medium">
            {zone.location_name}
          </span>
          <span
            className={cn(
              "w-[52px] shrink-0",
              zone.current_status === "normal"
                ? "text-muted-foreground"
                : "font-medium",
            )}
          >
            {statusLabel(zone.current_status)}
          </span>
          <MiniTimeline history={zone.history} />
          {harmattanDays != null && harmattanDays > 0 && (
            <span className="shrink-0 rounded px-1 py-0 text-[10px] font-semibold tabular-nums bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400 ml-auto">
              {harmattanDays}j
            </span>
          )}
        </div>
      </TooltipTrigger>
      <TooltipContent side="top">
        <p>
          {zone.location_name} ({zone.country}) — {statusLabel(zone.current_status)}
          {zone.streak_days > 1 && ` depuis ${zone.streak_days} jours`}
          {zone.trend !== "stable" &&
            ` (${zone.trend === "worsening" ? "en dégradation" : "en amélioration"})`}
          {harmattanDays != null && harmattanDays > 0 &&
            ` — Harmattan: ${harmattanDays}j`}
        </p>
      </TooltipContent>
    </Tooltip>
  );
}

function ZoneList({
  history,
  harmattanByLocation,
}: {
  history: LocationStressHistory[];
  harmattanByLocation: Record<string, number>;
}) {
  const civZones = history.filter((z) => z.country === "CIV");
  const ghaZones = history.filter((z) => z.country === "GHA");

  return (
    <TooltipProvider delayDuration={200}>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3 md:gap-y-0">
        <div className="min-w-0">
          <p className="text-[10px] font-medium text-muted-foreground/50 uppercase tracking-wider mb-1">
            {countryFlag("CIV")} Côte d&apos;Ivoire
          </p>
          {civZones.map((zone) => (
            <ZoneRow
              key={zone.location_name}
              zone={zone}
              harmattanDays={harmattanByLocation[zone.location_name]}
            />
          ))}
        </div>
        <div className="min-w-0">
          <p className="text-[10px] font-medium text-muted-foreground/50 uppercase tracking-wider mb-1">
            {countryFlag("GHA")} Ghana
          </p>
          {ghaZones.map((zone) => (
            <ZoneRow
              key={zone.location_name}
              zone={zone}
              harmattanDays={harmattanByLocation[zone.location_name]}
            />
          ))}
        </div>
      </div>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// CampaignSection — seasonal progress bars (rolling data)
// ---------------------------------------------------------------------------

function CampaignSection({
  campaign,
  campaignHealth,
  seasons,
}: {
  campaign: string;
  campaignHealth: number | null | undefined;
  seasons: SeasonStatus[];
}) {
  return (
    <div className="space-y-3">
      <InfoHint>
        {`Bilan saisonnier cumulé depuis oct. ${campaign.split("-")[0]}`}
      </InfoHint>
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-muted-foreground">
          Campagne {campaign}
        </span>
        {campaignHealth != null && (
          <Badge className={cn("text-xs font-semibold", scoreColor(campaignHealth))}>
            Santé {campaignHealth}/5
          </Badge>
        )}
      </div>

      {seasons.length > 0 && (
        <TooltipProvider delayDuration={200}>
          <div className="space-y-1.5">
            {seasons.map((season) => (
              <Tooltip key={season.season_name}>
                <TooltipTrigger asChild>
                  <div className="flex items-center gap-2 text-xs">
                    <span className="w-[140px] truncate text-muted-foreground">
                      {season.label}
                    </span>
                    <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                      {season.score != null ? (
                        <div
                          className={cn(
                            "h-full rounded-full transition-all duration-700",
                            season.status === "in_progress"
                              ? "bg-primary animate-pulse"
                              : scoreBarColor(season.score),
                          )}
                          style={{ width: `${(season.score / 5) * 100}%` }}
                        />
                      ) : (
                        <div
                          className={cn(
                            "h-full rounded-full",
                            seasonStatusIcon(season.status),
                          )}
                          style={{ width: season.status === "upcoming" ? "0%" : "100%" }}
                        />
                      )}
                    </div>
                    <span className="w-[40px] text-right tabular-nums font-medium">
                      {season.score != null ? `${season.score}` : "—"}
                    </span>
                  </div>
                </TooltipTrigger>
                <TooltipContent side="top">
                  <p>
                    {season.label} ({season.months_covered})
                    {season.score != null && ` — ${season.score}/5`}
                    {season.status !== "in_progress" &&
                      ` — ${season.status === "completed" ? "Terminée" : "À venir"}`}
                  </p>
                </TooltipContent>
              </Tooltip>
            ))}
          </div>
        </TooltipProvider>
      )}

    </div>
  );
}

// ---------------------------------------------------------------------------
// ZonePlaceholder — shown when no stress history data exists yet
// ---------------------------------------------------------------------------

const PLACEHOLDER_LOCATIONS = [
  { name: "Daloa", country: "CIV" },
  { name: "San-Pédro", country: "CIV" },
  { name: "Soubré", country: "CIV" },
  { name: "Kumasi", country: "GHA" },
  { name: "Takoradi", country: "GHA" },
  { name: "Goaso", country: "GHA" },
] as const;

function ZonePlaceholder() {
  return (
    <div className="space-y-1">
      {PLACEHOLDER_LOCATIONS.map((loc) => (
        <div key={loc.name} className="flex items-center gap-2 py-1 text-xs">
          <div className="h-2 w-2 rounded-full bg-muted-foreground/20 shrink-0" />
          <span className="w-[80px] shrink-0 font-medium text-muted-foreground/60">
            {countryFlag(loc.country)} {loc.name}
          </span>
          <span className="text-muted-foreground/40 italic">—</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

interface WeatherUpdateCardProps {
  targetDate?: string;
  className?: string;
}

export default function WeatherUpdateCard({
  targetDate,
  className,
}: WeatherUpdateCardProps) {
  const { data: weather, isLoading, error } = useWeather(targetDate);
  const hasEnrichedData = !!(
    weather?.campaign &&
    weather.seasons &&
    weather.seasons.length > 0
  );
  const hasStressHistory = !!(
    weather?.stress_history && weather.stress_history.length > 0
  );
  const [analysisOpen, setAnalysisOpen] = useState(true);

  if (isLoading) {
    return (
      <Card className={cn("flex items-center justify-center h-[200px]", className)}>
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Chargement du rapport météo...</span>
        </div>
      </Card>
    );
  }

  if (error || !weather) {
    return (
      <Card className={cn("flex items-center justify-center h-[200px]", className)}>
        <div className="text-center space-y-1">
          <CloudRainIcon className="h-6 w-6 text-muted-foreground/40 mx-auto" />
          <p className="text-sm text-muted-foreground">
            Aucun rapport météo pour cette date
          </p>
        </div>
      </Card>
    );
  }

  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <CardTitle className="text-lg font-semibold tracking-tight">
          Agro-Météo Intelligence
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Section 1: Zone List with timeline */}
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Zones productrices</h3>
          <span className="text-[10px] text-muted-foreground/60">
            {hasStressHistory ? "7 derniers jours" : "en attente de données"}
          </span>
        </div>
        <InfoHint>Diagnostic basé sur l&apos;analyse météo du jour</InfoHint>
        {hasStressHistory ? (
          <ZoneList
            history={weather.stress_history!}
            harmattanByLocation={
              (weather.diagnostics ?? []).reduce<Record<string, number>>((acc, d) => {
                if (d.harmattan_days != null && d.harmattan_days > 0) {
                  acc[d.location_name] = d.harmattan_days;
                }
                return acc;
              }, {})
            }
          />
        ) : (
          <ZonePlaceholder />
        )}

        {/* Section 2: Daily Analysis (collapsible) */}
        <div className="border-t border-border/50 pt-3">
          <Collapsible open={analysisOpen} onOpenChange={setAnalysisOpen}>
            <CollapsibleTrigger className="flex items-center justify-between w-full">
              <h3 className="text-sm font-semibold">Analyse du jour</h3>
              <ChevronDown
                className={cn(
                  "h-4 w-4 text-muted-foreground transition-transform duration-200",
                  analysisOpen && "rotate-180",
                )}
              />
            </CollapsibleTrigger>
            <CollapsibleContent>
              <InfoHint>Bulletin généré par le modèle météo</InfoHint>
              <div className="mt-2 space-y-2">
                {weather.description
                  .split(/\n{2,}/)
                  .filter(Boolean)
                  .map((p, i) => (
                    <p
                      key={i}
                      className="text-sm text-foreground/85 leading-relaxed"
                    >
                      {formatFinancialText(p.trim())}
                    </p>
                  ))}
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>

        {/* Section 4: Campaign Context (rolling) */}
        {hasEnrichedData && (
          <div className="border-t border-dashed border-border/60 pt-3">
            <CampaignSection
              campaign={weather.campaign!}
              campaignHealth={weather.campaign_health}
              seasons={weather.seasons!}
            />
          </div>
        )}
      </CardContent>

      <CardFooter className="pt-0 flex flex-wrap gap-3 items-center">
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <CalendarIcon className="h-3.5 w-3.5" />
          <span>{weather.date}</span>
        </div>
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <BotIcon className="h-3.5 w-3.5" />
          <span>meteo-agent</span>
        </div>
      </CardFooter>
    </Card>
  );
}
