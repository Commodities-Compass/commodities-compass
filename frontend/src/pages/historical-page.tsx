import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DownloadIcon, FilterIcon } from "lucide-react";
import { Line, LineChart, CartesianGrid, XAxis } from "recharts";
import { HISTORICAL_DATA, DashboardData } from "@/data/commodities-data";
import { useState } from "react";
import GaugeIndicator from "@/components/gauge-indicator";
import { DatePickerWithRange } from "@/components/date-range-picker";

type IndicatorKey = keyof DashboardData['indicators'];

export default function HistoricalPage() {
  const [viewMode, setViewMode] = useState<"chart" | "table">("chart");
  const [selectedIndicator, setSelectedIndicator] = useState<IndicatorKey>("dayIndicator");

  // Prepare data for charts
  const chartData = HISTORICAL_DATA.map(data => ({
    date: data.date,
    value: data.indicators[selectedIndicator].value,
    ytdPerformance: data.ytdPerformance,
    position: data.positionOfDay
  })).reverse();

  // Get indicator details for the selected indicator
  const indicatorDetails = HISTORICAL_DATA[0].indicators[selectedIndicator];

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row gap-4 items-start md:items-center justify-between">
        <h1 className="text-2xl font-bold">Historical Data</h1>
        <div className="flex flex-col sm:flex-row gap-4 w-full md:w-auto">
          <DatePickerWithRange className="w-full sm:w-auto" />
          <Button variant="outline" className="flex items-center gap-2">
            <FilterIcon className="h-4 w-4" />
            Filter
          </Button>
          <Button variant="outline" className="flex items-center gap-2">
            <DownloadIcon className="h-4 w-4" />
            Export
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
            <CardTitle>Historical Indicators</CardTitle>
            <Tabs defaultValue="chart" onValueChange={(value) => setViewMode(value as "chart" | "table")}>
              <TabsList>
                <TabsTrigger value="chart">Chart</TabsTrigger>
                <TabsTrigger value="table">Table</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        </CardHeader>
        <CardContent>
          <div className="mb-6">
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-4 justify-items-center">
              {Object.entries(HISTORICAL_DATA[0].indicators).map(([key, indicator]) => (
                <Button
                  key={key}
                  variant={selectedIndicator === key ? "default" : "outline"}
                  className="w-full"
                  onClick={() => setSelectedIndicator(key as IndicatorKey)}
                >
                  {indicator.label}
                </Button>
              ))}
            </div>
          </div>

          {viewMode === "chart" ? (
            <div className="space-y-6">
              <div className="flex flex-col md:flex-row gap-6 items-center">
                <div className="w-full md:w-2/3">
                  <ChartContainer config={{}} className="aspect-[none] h-[300px]">
                    <LineChart data={chartData}>
                      <ChartTooltip content={<ChartTooltipContent />} />
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis
                        dataKey="date"
                        tickFormatter={(value) => {
                          const date = new Date(value);
                          return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                        }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke="hsl(var(--chart-1))"
                        strokeWidth={2}
                        dot={{ r: 4 }}
                        activeDot={{ r: 6 }}
                      />
                    </LineChart>
                  </ChartContainer>
                </div>
                <div className="w-full md:w-1/3 flex flex-col items-center">
                  <h3 className="text-lg font-medium mb-4">{indicatorDetails.label} - Latest Value</h3>
                  <GaugeIndicator
                    value={HISTORICAL_DATA[0].indicators[selectedIndicator].value}
                    min={indicatorDetails.min}
                    max={indicatorDetails.max}
                    label={indicatorDetails.label}
                    size="lg"
                  />
                </div>
              </div>

              <div>
                <h3 className="text-lg font-medium mb-4">YTD Performance</h3>
                <ChartContainer config={{}} className="aspect-[none] h-[200px]">
                  <LineChart data={chartData}>
                    <ChartTooltip content={<ChartTooltipContent />} />
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="date"
                      tickFormatter={(value) => {
                        const date = new Date(value);
                        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                      }}
                      tickLine={false}
                      axisLine={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="ytdPerformance"
                      stroke="hsl(var(--chart-2))"
                      strokeWidth={2}
                      dot={{ r: 4 }}
                      activeDot={{ r: 6 }}
                    />
                  </LineChart>
                </ChartContainer>
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Position</TableHead>
                    <TableHead>YTD Performance</TableHead>
                    {Object.entries(HISTORICAL_DATA[0].indicators).map(([key, indicator]) => (
                      <TableHead key={key}>{indicator.label}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {HISTORICAL_DATA.map((data) => (
                    <TableRow key={data.date}>
                      <TableCell>{data.date}</TableCell>
                      <TableCell>{data.positionOfDay}</TableCell>
                      <TableCell>{data.ytdPerformance.toFixed(2)}%</TableCell>
                      {Object.entries(data.indicators).map(([key, indicator]) => (
                        <TableCell key={key}>{indicator.value.toFixed(2)}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
