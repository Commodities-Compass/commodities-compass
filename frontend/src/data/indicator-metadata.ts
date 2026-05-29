export interface IndicatorMeta {
  fullName: string;
  description: string;
  zones: { RED: string; ORANGE: string; GREEN: string };
}

export const INDICATOR_META: Record<string, IndicatorMeta> = {
  MACROECO: {
    fullName: 'Macro-Économique',
    description: "Score macro issu de l'analyse LLM (météo, fondamentaux, contexte global)",
    zones: { RED: 'Contexte défavorable', ORANGE: 'Contexte neutre', GREEN: 'Contexte porteur' },
  },
  RSI: {
    fullName: 'Relative Strength Index',
    description: 'Vitesse et amplitude des mouvements de prix sur 14 jours',
    zones: { RED: 'Survendu — pression vendeuse', ORANGE: 'Zone neutre', GREEN: 'Momentum haussier' },
  },
  MACD: {
    fullName: 'MACD',
    description: 'Changements de tendance via croisement de moyennes mobiles',
    zones: { RED: 'Signal baissier', ORANGE: 'Pas de signal clair', GREEN: 'Signal haussier' },
  },
  '%K': {
    fullName: 'Stochastique %K',
    description: 'Cours de clôture vs fourchette haute-basse',
    zones: { RED: 'Survendu (<20%)', ORANGE: 'Zone neutre', GREEN: 'Momentum fort (>80%)' },
  },
  ATR: {
    fullName: 'Average True Range',
    description: 'Volatilité moyenne du marché (Wilder, 14j)',
    zones: { RED: 'Volatilité faible', ORANGE: 'Volatilité normale', GREEN: 'Volatilité élevée' },
  },
  'VOL/OI': {
    fullName: 'Volume / Open Interest',
    description: 'Ratio volume de trading / positions ouvertes',
    zones: { RED: 'Activité faible', ORANGE: 'Activité normale', GREEN: 'Conviction forte' },
  },
  // Macro & FX
  'FX DXY': {
    fullName: 'Dollar Index proxy',
    description: 'Force du dollar (1 / EURUSD). Un USD fort pèse sur les commodités cotées en USD.',
    zones: {
      RED: 'USD fort — pression baissière',
      ORANGE: 'USD neutre',
      GREEN: 'USD faible — soutien commodités',
    },
  },
  GBPUSD: {
    fullName: 'Livre / Dollar',
    description: 'Devise de cotation du cocoa Londres. Une livre forte renchérit le contrat en USD.',
    zones: {
      RED: 'GBP faible — discount London',
      ORANGE: 'Zone neutre',
      GREEN: 'GBP forte — premium London',
    },
  },
  'ENSO ONI': {
    fullName: 'Oceanic Niño Index',
    description: 'Anomalie de température de surface Pacifique équatorial (moyenne 3 mois).',
    zones: {
      RED: 'La Niña — risque sec Afrique',
      ORANGE: 'Phase ENSO neutre',
      GREEN: 'El Niño — humidité Afrique',
    },
  },
  'NIÑO 3.4': {
    fullName: 'Anomalie Niño 3.4',
    description: 'Anomalie SST zone Niño 3.4 — signal climatique mensuel, lag 14 jours.',
    zones: {
      RED: 'Refroidissement (La Niña)',
      ORANGE: 'Anomalie neutre',
      GREEN: 'Réchauffement (El Niño)',
    },
  },
  // Positioning & Supply
  'COT MM NET EU': {
    fullName: 'Managed Money — net (ICE Europe)',
    description:
      'Position nette des Managed Money sur le contrat cacao ICE Europe (London #7), publiée hebdomadairement (long − short).',
    zones: {
      RED: 'Net short — sentiment baissier',
      ORANGE: 'Net léger — pas de conviction',
      GREEN: 'Net long — sentiment haussier',
    },
  },
  'COT MM NET US': {
    fullName: 'Managed Money — net (CFTC US)',
    description:
      'Position nette des Managed Money sur le contrat cacao NY (CFTC Disaggregated Cocoa, ICE US Futures), publiée hebdomadairement (long − short).',
    zones: {
      RED: 'Net short — sentiment baissier',
      ORANGE: 'Net léger — pas de conviction',
      GREEN: 'Net long — sentiment haussier',
    },
  },
  'STOCK EU': {
    fullName: 'Stocks certifiés ICE Europe',
    description: 'Stocks de fèves certifiés en entrepôts ICE Europe (sacs 60 kg). Stocks élevés = pression baissière.',
    zones: {
      RED: 'Stocks élevés — pression vendeuse',
      ORANGE: 'Stocks moyens',
      GREEN: 'Stocks bas — tension offre',
    },
  },
  'STOCK US': {
    fullName: 'Stocks certifiés ICE US',
    description: 'Stocks de fèves certifiés en entrepôts ICE US (tonnes). Stocks élevés = pression baissière.',
    zones: {
      RED: 'Stocks élevés — pression vendeuse',
      ORANGE: 'Stocks moyens',
      GREEN: 'Stocks bas — tension offre',
    },
  },
  PRODUCTION: {
    fullName: 'Sentiment Production',
    description: 'Ton de la presse sur la production cacao',
    zones: { RED: "Récit baissier — tensions sur l'offre", ORANGE: 'Ton neutre', GREEN: 'Récit haussier' },
  },
  CHOCOLAT: {
    fullName: 'Sentiment Chocolat',
    description: 'Ton de la presse sur la demande chocolat',
    zones: { RED: 'Demande en repli', ORANGE: 'Demande stable', GREEN: 'Demande soutenue' },
  },
  'TRANSF.': {
    fullName: 'Sentiment Transformation',
    description: 'Ton de la presse sur la transformation',
    zones: { RED: 'Activité en baisse', ORANGE: 'Activité stable', GREEN: 'Activité en hausse' },
  },
  'ÉCONOMIE': {
    fullName: 'Sentiment Économie',
    description: 'Ton de la presse macro-économique',
    zones: { RED: 'Contexte défavorable', ORANGE: 'Contexte neutre', GREEN: 'Contexte porteur' },
  },
};
