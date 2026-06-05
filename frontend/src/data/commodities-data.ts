export interface CommodityIndicator {
  value: number;
  min: number;
  max: number;
  label: string;
  color?: string; // Optional color override
}

export interface DailyRecommendation {
  id: number;
  text: string;
}

export interface MarketNews {
  id: number;
  date: string;
  author: string;
  title: string;
  content: string;
}

export interface WeatherUpdate {
  id: number;
  date: string;
  region: string;
  description: string;
  impact: string;
}

export interface HistoricalData {
  date: string;
  price: number;
  volume: number;
  rsi: number;
  stockUs: number;
  stockEu: number;
  atr: number;
  openInterest: number;
  macd: number;
  pivot: number;
}

export interface DashboardData {
  date: string;
  positionOfDay: "OPEN" | "CLOSED";
  ytdPerformance: number;
  indicators: {
    dayIndicator: CommodityIndicator;
    macroeco: CommodityIndicator;
    rsi: CommodityIndicator;
    macd: CommodityIndicator;
    percentK: CommodityIndicator;
    atr: CommodityIndicator;
    volOi: CommodityIndicator;
  };
  recommendations: DailyRecommendation[];
  chartData: HistoricalData[];
  lastPress: MarketNews;
  weatherUpdates: WeatherUpdate[];
}

export const MOCK_DASHBOARD_DATA: DashboardData = {
  date: "May 9, 2024",
  positionOfDay: "OPEN",
  ytdPerformance: 72.12,
  indicators: {
    dayIndicator: {
      value: 2.22,
      min: 0,
      max: 3,
      label: "DAY INDICATOR",
    },
    macroeco: {
      value: 1.1,
      min: 0,
      max: 3,
      label: "DAY MACROECO",
    },
    rsi: {
      value: 0.59,
      min: 0,
      max: 3,
      label: "DAY RSI",
    },
    macd: {
      value: 1.11,
      min: 0,
      max: 3,
      label: "DAY MACD",
    },
    percentK: {
      value: 0.08,
      min: 0,
      max: 3,
      label: "DAY %K",
    },
    atr: {
      value: -0.39,
      min: -3,
      max: 3,
      label: "DAY ATR",
    },
    volOi: {
      value: 0.11,
      min: 0,
      max: 3,
      label: "DAY VOL/OI",
    },
  },
  recommendations: [
    {
      id: 1,
      text: "CLOSE aujourd'hui en hausse à 6593 comparé à 6576 hier, indiquant une légère tendance haussière.",
    },
    {
      id: 2,
      text: "VOLUME en baisse significative à 5267 contre 9517 hier, suggérant une diminution de l'engagement du marché.",
    },
    {
      id: 3,
      text: "OPEN INTEREST a également diminué de 32725 à 34565, indiquant un désengagement potentiel ou une consolidation.",
    },
    {
      id: 4,
      text: "RSI est à 72.93, suggérant une condition de surachat qui pourrait prévoir une correction à court terme.",
    },
    {
      id: 5,
      text: "MACD à -187.46, amélioré par rapport à -212 hier, montre une réduction de la pression baissière.",
    },
    {
      id: 6,
      text: "ATR a diminué de 372 à 438, indiquant une volatilité moindre et potentiellement moins de mouvements brusques.",
    },
    {
      id: 7,
      text: "STOCK EU a augmenté à 147868 contre 147203, ce qui pourrait augmenter la pression baissière si la tendance se poursuit.",
    },
    {
      id: 8,
      text: "Pivot actuel à 6625, avec le CLOSE proche de ce niveau, indique une zone de décision importante.",
    },
  ],

  chartData: [
    {
      date: "Sep 16, 2023",
      price: 4000,
      volume: 3200,
      rsi: 45.2,
      stockUs: 125000,
      stockEu: 132000,
      atr: 280,
      openInterest: 28500,
      macd: -250,
      pivot: 4050,
    },
    {
      date: "Oct 1, 2023",
      price: 4200,
      volume: 4100,
      rsi: 52.8,
      stockUs: 124500,
      stockEu: 133500,
      atr: 295,
      openInterest: 29200,
      macd: -220,
      pivot: 4180,
    },
    {
      date: "Oct 15, 2023",
      price: 4500,
      volume: 5300,
      rsi: 58.6,
      stockUs: 123800,
      stockEu: 135000,
      atr: 310,
      openInterest: 30100,
      macd: -180,
      pivot: 4450,
    },
    {
      date: "Nov 1, 2023",
      price: 5000,
      volume: 7200,
      rsi: 65.3,
      stockUs: 122500,
      stockEu: 136200,
      atr: 325,
      openInterest: 31500,
      macd: -150,
      pivot: 4950,
    },
    {
      date: "Nov 15, 2023",
      price: 5200,
      volume: 6800,
      rsi: 68.7,
      stockUs: 121000,
      stockEu: 137500,
      atr: 340,
      openInterest: 32200,
      macd: -120,
      pivot: 5180,
    },
    {
      date: "Dec 1, 2023",
      price: 6000,
      volume: 8500,
      rsi: 74.2,
      stockUs: 119500,
      stockEu: 139000,
      atr: 365,
      openInterest: 33800,
      macd: -90,
      pivot: 5950,
    },
    {
      date: "Dec 15, 2023",
      price: 7000,
      volume: 9800,
      rsi: 78.5,
      stockUs: 118000,
      stockEu: 140500,
      atr: 390,
      openInterest: 35200,
      macd: -60,
      pivot: 6950,
    },
    {
      date: "Jan 1, 2024",
      price: 8000,
      volume: 11200,
      rsi: 82.1,
      stockUs: 116500,
      stockEu: 142000,
      atr: 415,
      openInterest: 36500,
      macd: -30,
      pivot: 7950,
    },
    {
      date: "Jan 15, 2024",
      price: 9000,
      volume: 12500,
      rsi: 85.4,
      stockUs: 115000,
      stockEu: 143500,
      atr: 440,
      openInterest: 37800,
      macd: 0,
      pivot: 8950,
    },
    {
      date: "Feb 1, 2024",
      price: 9500,
      volume: 11800,
      rsi: 83.2,
      stockUs: 116800,
      stockEu: 144800,
      atr: 425,
      openInterest: 37200,
      macd: -20,
      pivot: 9450,
    },
    {
      date: "Feb 15, 2024",
      price: 8000,
      volume: 10200,
      rsi: 76.5,
      stockUs: 118500,
      stockEu: 145500,
      atr: 410,
      openInterest: 36500,
      macd: -50,
      pivot: 8050,
    },
    {
      date: "Mar 1, 2024",
      price: 7500,
      volume: 9500,
      rsi: 72.8,
      stockUs: 120200,
      stockEu: 146200,
      atr: 395,
      openInterest: 35800,
      macd: -80,
      pivot: 7550,
    },
    {
      date: "Mar 15, 2024",
      price: 7000,
      volume: 8800,
      rsi: 70.5,
      stockUs: 122000,
      stockEu: 146800,
      atr: 385,
      openInterest: 35000,
      macd: -110,
      pivot: 7050,
    },
    {
      date: "Apr 1, 2024",
      price: 6500,
      volume: 7500,
      rsi: 68.2,
      stockUs: 123500,
      stockEu: 147200,
      atr: 375,
      openInterest: 34200,
      macd: -140,
      pivot: 6550,
    },
    {
      date: "Apr 15, 2024",
      price: 6000,
      volume: 6200,
      rsi: 65.8,
      stockUs: 125000,
      stockEu: 147500,
      atr: 365,
      openInterest: 33500,
      macd: -170,
      pivot: 6050,
    },
    {
      date: "May 1, 2024",
      price: 6200,
      volume: 7800,
      rsi: 68.5,
      stockUs: 126200,
      stockEu: 147700,
      atr: 370,
      openInterest: 33800,
      macd: -200,
      pivot: 6250,
    },
    {
      date: "May 9, 2024",
      price: 6593,
      volume: 5267,
      rsi: 72.93,
      stockUs: 127500,
      stockEu: 147868,
      atr: 372,
      openInterest: 32725,
      macd: -187.46,
      pivot: 6625,
    },
  ],

  lastPress: {
    id: 1,
    date: "May 8, 2024",
    author: "Mark Bowman",
    title:
      "Les conditions météorologiques favorables en Afrique de l'Ouest boostent la production de cacao",
    content:
      "Les arrivées cumulatives de cacao en Côte d'Ivoire ont significativement augmenté comparé à l'année dernière. Les stocks globaux continuent de croître, posant un risque potentiel de baisse des prix.",
  },
  weatherUpdates: [
    {
      id: 1,
      date: "May 9, 2024",
      region: "Côte d'Ivoire et Ghana",
      description:
        "Les dernières données météo montrent des précipitations au-dessus de la moyenne en Côte d'Ivoire et au Ghana, avec une forte humidité des sols. Cela pourrait stresser les cacaoyers en floraison et affecter la fixation des fruits. Les variations régionales de rendement pourraient influencer les prix du marché.",
      impact:
        "Les variations de qualité et de quantité de production dues aux conditions météorologiques pourraient entraîner des fluctuations significatives des prix du cacao.",
    },
  ],
};

// Historical data for the past week
export const HISTORICAL_DATA: DashboardData[] = [
  {
    ...MOCK_DASHBOARD_DATA,
    date: "May 9, 2024",
  },
  {
    ...MOCK_DASHBOARD_DATA,
    date: "May 8, 2024",
    ytdPerformance: 71.85,
    indicators: {
      ...MOCK_DASHBOARD_DATA.indicators,
      dayIndicator: {
        ...MOCK_DASHBOARD_DATA.indicators.dayIndicator,
        value: 2.15,
      },
      rsi: { ...MOCK_DASHBOARD_DATA.indicators.rsi, value: 0.62 },
      macd: { ...MOCK_DASHBOARD_DATA.indicators.macd, value: 1.05 },
    },
    chartData: MOCK_DASHBOARD_DATA.chartData.slice(0, -1).map((item) => ({
      ...item,
      price: item.price * 0.998,
      volume: item.volume * 1.02,
      rsi: item.rsi * 0.99,
      stockUs: item.stockUs * 0.997,
    })),
  },
  {
    ...MOCK_DASHBOARD_DATA,
    date: "May 7, 2024",
    ytdPerformance: 71.23,
    indicators: {
      ...MOCK_DASHBOARD_DATA.indicators,
      dayIndicator: {
        ...MOCK_DASHBOARD_DATA.indicators.dayIndicator,
        value: 2.05,
      },
      macroeco: { ...MOCK_DASHBOARD_DATA.indicators.macroeco, value: 1.2 },
      rsi: { ...MOCK_DASHBOARD_DATA.indicators.rsi, value: 0.7 },
    },
    chartData: MOCK_DASHBOARD_DATA.chartData.slice(0, -2).map((item) => ({
      ...item,
      price: item.price * 0.995,
      volume: item.volume * 1.05,
      rsi: item.rsi * 0.98,
      stockUs: item.stockUs * 0.994,
    })),
  },
  {
    ...MOCK_DASHBOARD_DATA,
    date: "May 6, 2024",
    ytdPerformance: 70.89,
    indicators: {
      ...MOCK_DASHBOARD_DATA.indicators,
      dayIndicator: {
        ...MOCK_DASHBOARD_DATA.indicators.dayIndicator,
        value: 1.95,
      },
      rsi: { ...MOCK_DASHBOARD_DATA.indicators.rsi, value: 0.75 },
      atr: { ...MOCK_DASHBOARD_DATA.indicators.atr, value: -0.25 },
    },
    chartData: MOCK_DASHBOARD_DATA.chartData.slice(0, -3).map((item) => ({
      ...item,
      price: item.price * 0.992,
      volume: item.volume * 1.08,
      rsi: item.rsi * 0.97,
      stockUs: item.stockUs * 0.991,
    })),
  },
  {
    ...MOCK_DASHBOARD_DATA,
    date: "May 5, 2024",
    ytdPerformance: 70.45,
    indicators: {
      ...MOCK_DASHBOARD_DATA.indicators,
      dayIndicator: {
        ...MOCK_DASHBOARD_DATA.indicators.dayIndicator,
        value: 1.85,
      },
      macroeco: { ...MOCK_DASHBOARD_DATA.indicators.macroeco, value: 0.95 },
      volOi: { ...MOCK_DASHBOARD_DATA.indicators.volOi, value: 0.18 },
    },
    chartData: MOCK_DASHBOARD_DATA.chartData.slice(0, -4).map((item) => ({
      ...item,
      price: item.price * 0.99,
      volume: item.volume * 1.1,
      rsi: item.rsi * 0.96,
      stockUs: item.stockUs * 0.988,
    })),
  },
];

// Define metric options and their display configurations
export const METRIC_OPTIONS = [
  {
    value: "close",
    label: "CLOSE",
    dataKey: "close",
    color: "hsl(var(--chart-1))",
  },
  {
    value: "volume",
    label: "VOLUME",
    dataKey: "volume",
    color: "hsl(var(--chart-2))",
  },
  { 
    value: "rsi_14d", 
    label: "RSI", 
    dataKey: "rsi_14d", 
    color: "hsl(var(--chart-3))" 
  },
  {
    value: "stock_eu",
    label: "STOCK EU",
    dataKey: "stock_eu",
    color: "hsl(var(--chart-4))",
  },
  {
    value: "open_interest",
    label: "OPEN INTEREST",
    dataKey: "open_interest",
    color: "hsl(var(--chart-5))",
  },
  {
    value: "macd",
    label: "MACD",
    dataKey: "macd",
    color: "hsl(var(--chart-1))",
  },
  {
    value: "com_net_eu",
    label: "COM NET EU",
    dataKey: "com_net_eu",
    color: "hsl(var(--chart-2))",
  },
];
