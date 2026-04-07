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
import type { SeasonStatus, LocationDiagnostic } from "@/types/dashboard";

// --- Helpers ---

function scoreColor(score: number | null | undefined): string {
  if (score == null) return "bg-muted text-muted-foreground";
  if (score >= 3.5) return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300";
  if (score >= 2.5) return "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300";
  return "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300";
}

function diagnosticDot(status: string): string {
  if (status === "normal") return "bg-emerald-500";
  if (status === "degraded") return "bg-amber-500";
  return "bg-red-500";
}

function diagnosticLabel(status: string): string {
  if (status === "normal") return "Normal";
  if (status === "degraded") return "Dégradé";
  return "Stress";
}

function impactBarColor(score: number): string {
  if (score <= 3) return "bg-emerald-500";
  if (score <= 6) return "bg-amber-500";
  return "bg-red-500";
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

// --- Sub-components ---

function CampaignHeader({
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
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-muted-foreground">
          Campagne {campaign}
        </span>
        {campaignHealth != null && (
          <Badge className={cn("text-xs font-semibold", scoreColor(campaignHealth))}>
            {"Santé"} {campaignHealth}/5
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
                              : scoreBarColor(season.score)
                          )}
                          style={{ width: `${(season.score / 5) * 100}%` }}
                        />
                      ) : (
                        <div
                          className={cn(
                            "h-full rounded-full",
                            seasonStatusIcon(season.status)
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
                    {season.status !== "in_progress" && ` — ${season.status === "completed" ? "Terminée" : "À venir"}`}
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

function DiagnosticGrid({
  diagnostics,
}: {
  diagnostics: LocationDiagnostic[];
}) {
  const stressCount = diagnostics.filter((d) => d.status === "stress").length;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Diagnostic</h3>
        <span className="text-xs text-muted-foreground">
          {stressCount}/6 en stress
        </span>
      </div>

      <TooltipProvider delayDuration={200}>
        <div className="grid grid-cols-3 gap-2">
          {diagnostics.map((loc) => (
            <Tooltip key={loc.location_name}>
              <TooltipTrigger asChild>
                <div
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs",
                    "border border-border/50 bg-muted/30"
                  )}
                >
                  <div
                    className={cn(
                      "h-2 w-2 rounded-full shrink-0",
                      diagnosticDot(loc.status)
                    )}
                  />
                  <span className="truncate font-medium flex-1">
                    {countryFlag(loc.country)} {loc.location_name}
                  </span>
                  {loc.harmattan_days != null && loc.harmattan_days > 0 && (
                    <span className="shrink-0 rounded px-1 py-0.5 text-[10px] font-semibold tabular-nums bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400">
                      {loc.harmattan_days}j
                    </span>
                  )}
                </div>
              </TooltipTrigger>
              <TooltipContent side="top">
                <p>
                  {loc.location_name} ({loc.country}) {" — "}
                  {diagnosticLabel(loc.status)}
                  {loc.score != null && ` (${loc.score}/5)`}
                  {loc.harmattan_days != null && loc.harmattan_days > 0 && ` — Harmattan: ${loc.harmattan_days}j`}
                </p>
              </TooltipContent>
            </Tooltip>
          ))}
        </div>
      </TooltipProvider>
    </div>
  );
}

function ImpactBar({
  score,
  text,
}: {
  score: number;
  text: string;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Impact Marché</h3>
        <span className="text-sm font-bold tabular-nums">{score}/10</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-1000",
            impactBarColor(score)
          )}
          style={{ width: `${score * 10}%` }}
        />
      </div>
      <p className="text-sm text-muted-foreground">{text}</p>
    </div>
  );
}

// --- Main Component ---

interface WeatherUpdateCardProps {
  targetDate?: string;
  className?: string;
}

export default function WeatherUpdateCard({
  targetDate,
  className,
}: WeatherUpdateCardProps) {
  const { data: weather, isLoading, error } = useWeather(targetDate);
  const hasEnrichedData = !!(weather?.campaign && weather.seasons && weather.seasons.length > 0);
  const [analysisOpen, setAnalysisOpen] = useState(!hasEnrichedData);

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
          <p className="text-sm text-muted-foreground">Aucun rapport météo pour cette date</p>
        </div>
      </Card>
    );
  }

  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2 mb-2">
          <CloudRainIcon className="h-5 w-5 text-primary" />
          <CardTitle className="text-lg font-medium">
            Agro-Météo Intelligence
          </CardTitle>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Section 1: Campaign Header */}
        {hasEnrichedData && (
          <CampaignHeader
            campaign={weather.campaign!}
            campaignHealth={weather.campaign_health}
            seasons={weather.seasons!}
          />
        )}

        {/* Section 2: Daily Analysis (collapsible when enriched data present) */}
        {hasEnrichedData ? (
          <Collapsible open={analysisOpen} onOpenChange={setAnalysisOpen}>
            <CollapsibleTrigger className="flex items-center justify-between w-full group">
              <h3 className="text-sm font-semibold">Analyse du jour</h3>
              <ChevronDown
                className={cn(
                  "h-4 w-4 text-muted-foreground transition-transform duration-200",
                  analysisOpen && "rotate-180"
                )}
              />
            </CollapsibleTrigger>
            <CollapsibleContent>
              <p className="text-sm text-muted-foreground mt-2 whitespace-pre-line leading-relaxed">
                {weather.description}
              </p>
            </CollapsibleContent>
          </Collapsible>
        ) : (
          <div>
            <h3 className="text-sm font-semibold mb-1">Conditions Météo</h3>
            <p className="text-sm text-muted-foreground whitespace-pre-line leading-relaxed">
              {weather.description}
            </p>
          </div>
        )}

        {/* Section 3: Location Diagnostics */}
        {weather.diagnostics && weather.diagnostics.length > 0 && (
          <>
            <div className="border-t border-border/50" />
            <DiagnosticGrid diagnostics={weather.diagnostics} />
          </>
        )}

        {/* Section 4: Impact Bar or plain text */}
        <div className="border-t border-border/50" />
        {weather.impact_score != null ? (
          <ImpactBar score={weather.impact_score} text={weather.impact} />
        ) : (
          <div>
            <h3 className="text-sm font-semibold mb-1">Impact Marché</h3>
            <p className="text-sm text-muted-foreground">{weather.impact}</p>
          </div>
        )}
      </CardContent>

      <CardFooter className="pt-0 flex flex-wrap gap-3 items-center">
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <CalendarIcon className="h-3.5 w-3.5" />
          <span>{weather.date}</span>
        </div>
        {hasEnrichedData && (
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <BotIcon className="h-3.5 w-3.5" />
            <span>meteo-agent</span>
          </div>
        )}
      </CardFooter>
    </Card>
  );
}
