import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import { Loader2 } from 'lucide-react';
import { useState, useMemo } from 'react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { METRIC_OPTIONS } from '@/data/commodities-data';
import { useChartData } from '@/hooks/useDashboard';
import { cn } from '@/utils';

interface PriceChartProps {
  title?: string;
  selectedMetric?: string;
  onMetricChange?: (metric: string) => void;
  targetDate?: string;
  className?: string;
}

export default function PriceChart({
  title = 'Évolution des Prix',
  selectedMetric = 'close',
  onMetricChange,
  targetDate,
  className,
}: PriceChartProps) {
  const [days, setDays] = useState(30);

  // Fetch chart data from API
  const { data: chartResponse, isLoading, error } = useChartData(days, targetDate);

  // Find the selected metric configuration - must be called before any conditional returns
  const metricConfig = useMemo(() => {
    return (
      METRIC_OPTIONS.find((option) => option.value === selectedMetric) ||
      METRIC_OPTIONS[0]
    );
  }, [selectedMetric]);

  const visibleData = chartResponse?.data ?? [];

  // Tight Y-axis domain for CLOSE and STOCK US to make variations visible
  const yAxisDomain = useMemo<[number | string, number | string]>(() => {
    const tightMetrics = ['close', 'stock_us'];
    if (!tightMetrics.includes(selectedMetric) || visibleData.length === 0) {
      return [0, 'auto'];
    }
    const values = visibleData
      .map((d) => d[metricConfig.dataKey as keyof typeof d] as number)
      .filter((v) => v != null);
    if (values.length === 0) return [0, 'auto'];
    const min = Math.min(...values);
    const max = Math.max(...values);
    const padding = (max - min) * 0.1 || max * 0.01;
    return [Math.floor(min - padding), Math.ceil(max + padding)];
  }, [selectedMetric, visibleData, metricConfig.dataKey]);

  if (isLoading) {
    return (
      <Card className={cn("flex items-center justify-center h-[400px]", className)}>
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Chargement du graphique...</span>
        </div>
      </Card>
    );
  }

  if (error || !chartResponse?.data) {
    return (
      <Card className={cn("flex items-center justify-center h-[400px]", className)}>
        <div className="text-center space-y-1">
          <p className="text-sm text-muted-foreground">Aucune donnée de prix disponible</p>
          <p className="text-xs text-muted-foreground/60">
            Les données de marché n'ont peut-être pas encore été importées
          </p>
        </div>
      </Card>
    );
  }

  // Format date for display
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  // Handle metric change
  const handleMetricChange = (value: string) => {
    if (onMetricChange) {
      onMetricChange(value);
    }
  };

  // Handle days change
  const handleDaysChange = (value: string) => {
    setDays(parseInt(value));
  };

  return (
    <Card className={cn("w-full", className)}>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-lg font-medium">{title}</CardTitle>

        <div className="flex items-center gap-4">
          <Select
            value={selectedMetric}
            onValueChange={handleMetricChange}
            defaultValue="close"
          >
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="Métrique" />
            </SelectTrigger>
            <SelectContent>
              {METRIC_OPTIONS.map((metric) => (
                <SelectItem key={metric.value} value={metric.value}>
                  {metric.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={days.toString()}
            onValueChange={handleDaysChange}
          >
            <SelectTrigger className="w-[120px]">
              <SelectValue placeholder="Période" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">7 jours</SelectItem>
              <SelectItem value="30">30 jours</SelectItem>
              <SelectItem value="90">90 jours</SelectItem>
              <SelectItem value="180">180 jours</SelectItem>
              <SelectItem value="365">1 an</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </CardHeader>

      <CardContent>
        <ChartContainer config={{}} className="aspect-[none] h-[300px]">
          <AreaChart data={visibleData}>
            <ChartTooltip content={<ChartTooltipContent />} />

            <defs>
              <linearGradient id="colorMetric" x1="0" y1="0" x2="0" y2="1">
                <stop
                  offset="5%"
                  stopColor={metricConfig.color}
                  stopOpacity={0.8}
                />

                <stop
                  offset="95%"
                  stopColor={metricConfig.color}
                  stopOpacity={0.1}
                />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />

            <XAxis
              dataKey="date"
              tickFormatter={formatDate}
              tickLine={false}
              axisLine={false}
              tick={{ fontSize: 12 }}
              minTickGap={30}
            />

            <YAxis
              domain={yAxisDomain}
              hide
            />

            <Area
              type="monotone"
              dataKey={metricConfig.dataKey}
              stroke={metricConfig.color}
              fillOpacity={1}
              fill="url(#colorMetric)"
              strokeWidth={2}
              name={metricConfig.label}
            />
          </AreaChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}