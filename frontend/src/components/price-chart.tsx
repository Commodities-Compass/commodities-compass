'use client';

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import { Button } from '@/components/ui/button';
import { ZoomInIcon, ZoomOutIcon, Loader2 } from 'lucide-react';
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
  className?: string;
}

export default function PriceChart({
  title = 'Price Chart',
  selectedMetric = 'close',
  onMetricChange,
  className,
}: PriceChartProps) {
  const [zoomLevel, setZoomLevel] = useState(1);
  const [days, setDays] = useState(30);

  // Fetch chart data from API
  const { data: chartResponse, isLoading, error } = useChartData(days);

  // Find the selected metric configuration - must be called before any conditional returns
  const metricConfig = useMemo(() => {
    return (
      METRIC_OPTIONS.find((option) => option.value === selectedMetric) ||
      METRIC_OPTIONS[0]
    );
  }, [selectedMetric]);

  // Adjust data points based on zoom level - must be called before any conditional returns
  const visibleData = useMemo(() => {
    if (!chartResponse?.data) return [];

    const data = chartResponse.data;
    if (zoomLevel === 1) return data;

    const dataLength = data.length;
    const visiblePoints = Math.ceil(dataLength / zoomLevel);
    const startIndex = Math.max(0, dataLength - visiblePoints);

    return data.slice(startIndex);
  }, [chartResponse?.data, zoomLevel]);

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

  // Show loading state
  if (isLoading) {
    return (
      <Card className={cn("flex items-center justify-center h-[400px]", className)}>
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </Card>
    );
  }

  // Show error state
  if (error || !chartResponse?.data) {
    return (
      <Card className={cn("flex items-center justify-center h-[400px]", className)}>
        <div className="text-center space-y-2">
          <p className="text-sm text-muted-foreground">Unable to load chart data</p>
          {error && (
            <p className="text-xs text-red-500">
              Error: {error.message || 'Unknown error'}
            </p>
          )}
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
              <SelectValue placeholder="Select metric" />
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
              <SelectValue placeholder="Days" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">7 days</SelectItem>
              <SelectItem value="30">30 days</SelectItem>
              <SelectItem value="90">90 days</SelectItem>
              <SelectItem value="180">180 days</SelectItem>
              <SelectItem value="365">1 year</SelectItem>
            </SelectContent>
          </Select>

          <div className="flex items-center gap-2">

            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="icon"
                onClick={() => setZoomLevel((prev) => Math.max(1, prev - 1))}
                disabled={zoomLevel === 1}
              >
                <ZoomOutIcon className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="icon"
                onClick={() => setZoomLevel((prev) => Math.min(4, prev + 1))}
                disabled={zoomLevel === 4}
              >
                <ZoomInIcon className="h-4 w-4" />
              </Button>
            </div>
          </div>
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