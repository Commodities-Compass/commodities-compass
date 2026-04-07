import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { CheckCircleIcon, TrendingUpIcon, Loader2 } from "lucide-react";
import { useRecommendations } from "@/hooks/useDashboard";
import { cn } from "@/utils";

interface RecommendationsListProps {
  targetDate?: string;
  className?: string;
}

export default function RecommendationsList({
  targetDate,
  className,
}: RecommendationsListProps) {
  // Fetch recommendations from API
  const { data, isLoading, error } = useRecommendations(targetDate);

  if (isLoading) {
    return (
      <Card className={cn("flex items-center justify-center h-[400px]", className)}>
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Chargement des recommandations...</span>
        </div>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card className={cn("flex items-center justify-center h-[400px]", className)}>
        <div className="text-center space-y-1">
          <p className="text-sm text-muted-foreground">Aucune recommandation pour cette date</p>
          <p className="text-xs text-muted-foreground/60">
            Les signaux de trading sont générés après l'analyse quotidienne
          </p>
        </div>
      </Card>
    );
  }

  const { recommendations } = data;

  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <CardTitle className="text-lg font-medium flex items-center gap-2">
          <TrendingUpIcon className="h-5 w-5 text-primary" />
          Recommandations du Jour
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[300px] pr-4">
          {recommendations.length > 0 ? (
            <ul className="space-y-3">
              {recommendations.map((recommendation, index) => (
                <li key={index} className="flex items-start gap-2">
                  <CheckCircleIcon className="h-5 w-5 text-green-500 mt-0.5 flex-shrink-0" />
                  <span className="text-sm">{recommendation}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="flex items-center justify-center h-full">
              <p className="text-sm text-muted-foreground">Aucune recommandation disponible</p>
            </div>
          )}
        </ScrollArea>
      </CardContent>
    </Card>
  );
}