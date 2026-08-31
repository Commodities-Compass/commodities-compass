/**
 * Bilingual copy registry — sourced from the validated mockup
 * `mockup/landing/option-D-editorial-glass.html` and translated for /en.
 *
 * Single source of truth: every visible string lives here. Components
 * import `t(locale)` and reach into the section keys.
 *
 * Hero H1 stays universal English ("Decide before *the bell.*") per
 * brand decision — only the lede swaps FR/EN.
 */
export type Locale = 'fr' | 'en';

export const LOCALES: Locale[] = ['fr', 'en'];
export const DEFAULT_LOCALE: Locale = 'fr';

const strings = {
  fr: {
    masthead: {
      pubName: 'COMPASS CC',
      tagline: 'Le brief quotidien du cacao ICE',
      navWhat: 'Lecture',
      navMethod: 'Méthodologie',
      navBrief: 'Distribution',
      navContact: 'Accès',
      signIn: 'Se connecter',
      cta: 'Demander un accès',
      langSwitchAria: 'Passer en anglais',
    },
    hero: {
      title: 'Decide before',
      titleAccent: 'the',
      titleAccentEm: 'bell.',
      lede: "Compass CC est la rédaction quotidienne du marché du cacao ICE. Une conviction publiée chaque nuit, lue par les desks avant la première cloche de LIFFE. Quatre minutes pour rattraper la séance.",
      ctaPrimary: 'Demander un accès',
      ctaSecondary: 'Voir la méthodologie',
      signalAside: 'Aperçu du signal du jour',
      signalLabel: 'Signal du jour · Exemple',
      signalPill: 'OPEN',
      signalHeading: 'Signal OPEN —',
      signalHeadingEm: 'Pression haussière sur le cacao',
      statContract: 'CAZ26',
      statContractValue: '£2 998',
      statDay: 'J/J',
      statDayValue: '+0,77 %',
      statHorizon: 'Horizon',
      statHorizonValue: 'J+1',
      mini1Label: 'Une seule conviction',
      mini1ValuePrefix: 'OPEN, MONITOR',
      mini1ValueMiddle: 'ou',
      mini1ValueEm: 'HEDGE.',
      mini2Label: 'Dispo dès 00:00 UTC',
      mini2ValuePrefix: 'Avant',
      mini2ValueRest: 'la cloche.',
      mini3Label: 'Audio · 4 min',
      mini3ValuePrefix: 'Sur',
      mini3ValueRest: 'le chemin du bureau.',
    },
    bento: {
      sectionRoman: 'II',
      sectionTitle: 'Lecture',
      sectionMeta: '5 cellules · 1 conviction',
      lede: 'Une seule page,',
      ledeEm: 'plusieurs lectures.',
      deck: "Pas de fil infini. Pas d'appel d'analyste. Un écran, ouvert une fois par jour, quatre minutes à lire ou à écouter.",
      cell1Eyebrow: 'Signal du jour',
      cell1Heading: 'Lecture',
      cell1HeadingEm: 'Compass',
      cell1Signal: 'OPEN',
      cell1Horizon: 'Horizon ~4 J',
      cell1Edition: 'Édition № 312 · Semaine 24',
      cell2Eyebrow: 'Le brief',
      cell2Heading: 'Une',
      cell2HeadingEm: 'page,',
      cell2HeadingRest: 'en français.',
      cell2Body: "Technique, météo des origines, presse, offre & demande — une page éditoriale rédigée chaque jour par la rédaction.",
      cell3Eyebrow: 'Audio',
      cell3Heading: '4',
      cell3HeadingEm: 'minutes,',
      cell3HeadingRest: 'chaque jour.',
      cell3Body: 'Format podcast quotidien. À écouter sur le chemin du bureau, ou en streaming pendant que le tableau de bord charge.',
    },
    method: {
      sectionRoman: 'III',
      sectionTitle: 'Discipline éditoriale',
      fullLink: 'Méthodologie complète et transparence',
      sectionMeta: 'Quatre principes · Auditable',
      lede: 'La discipline contre',
      ledeEm: 'le bruit.',
      deck: "Le marché du cacao reste l'un des plus opaques de la finance moderne. Compass y répond par une discipline éditoriale claire — quatre principes simples, tenus chaque jour ouvré depuis 2025.",
      p1Roman: 'i',
      p1Title: 'Une seule',
      p1TitleEm: 'conviction.',
      p1Body: "Compass ne publie qu'une lecture par jour : <strong>OPEN</strong>, <strong>MONITOR</strong> ou <strong>HEDGE</strong>. Pas de scénarios parallèles, pas de mode prudent, pas d'options à la carte. Une décision, signée et datée, qu'on peut comparer à la prochaine cloche.",
      p1Pills: ['Une décision/jour', 'Signée & datée', 'Vérifiable'],
      p2Roman: 'ii',
      p2Title: 'Sources',
      p2TitleEm: 'croisées.',
      p2Body: "Compass croise quotidiennement des dizaines de signaux : prix officiels, positions commerciales, stocks certifiés, météo des origines, macro-finance. Toutes les sources sont publiques ou réglementaires. Aucune donnée propriétaire dont vous n'avez pas la traçabilité.",
      p2Pills: ['Sources publiques', 'Multi-domaines', 'Auditable'],
      p3Roman: 'iii',
      p3Title: 'Écrit pour',
      p3TitleEm: 'être lu.',
      p3Body: "Chaque brief est rédigé en une page de prose française, pas généré à la chaîne. Le verdict numérique devient un texte qu'un trader peut lire en quatre minutes ou écouter en quatre minutes vingt — dans la voiture, en marchant, en attendant l'ouverture.",
      p3Pills: ['Une page', 'FR natif', 'Audio inclus'],
      p4Roman: 'iv',
      p4Title: 'À heure',
      p4TitleEm: 'fixe.',
      p4Body: "Compilé chaque veille à <strong>19:30 UTC</strong>, disponible dès <strong>00:00 UTC</strong> le jour J. Lundi à vendredi, sans interruption depuis 2025. La discipline du même rendez-vous, chaque matin, avant que vous n'ouvriez le tableau de bord.",
      p4Pills: ['Compilé 19:30 UTC J-1', 'Dispo 00:00 UTC J', 'Depuis 2025'],
    },
    brief: {
      sectionRoman: 'IV',
      sectionTitle: 'Distribution',
      sectionMeta: 'Audio + texte + dashboard',
      lede: 'Disponible dès',
      ledeEm: 'minuit UTC.',
      deck: "Compilé la veille à 19:30 UTC. Disponible le jour J dès 00:00 UTC. Trois formats vous attendent — choisissez celui qui s'adapte à votre matinée.",
      briefKicker: '2026-06-12 · Brief · Semaine 24',
      briefBadge: 'HEDGE',
      briefHeading: 'Signal',
      briefHeadingEm: 'HEDGE',
      briefHeadingTail: '— Pression baissière sur le cacao',
      briefP1: "Lecture Compass alignée sur la position HEDGE, conviction nette (<em>forte</em>). Le CLOSE recule de 2 975 à 2 964 (−0,37 %), le VOLUME s'effondre de 11 241 à 5 697 (−49,3 %) — désengagement marqué des commerciaux.",
      briefP2: "<strong>Technique.</strong> CAZ26 dans la moitié basse du range hebdo. %K Stochastique sous 30, MACD négatif en pente descendante, ATR Wilder en hausse. Le ratio Volume/OI se contracte vers 0,14 — épuisement de l'élan haussier de mai.",
      briefP3: "<strong>Fondamental.</strong> Arrivages ports ivoiriens +8,2 % sur la semaine, au-dessus de la médiane 5-ans. ICCO révise la production à 4,72 Mt (vs 4,55 Mt). Grindings ECA Q1 2026 stables à −1,1 % YoY.",
      briefP4: "<strong>Météo & macro.</strong> Côte d'Ivoire + Ghana sortent d'une semaine sèche favorable au séchage, fenêtre de pluies J+5–J+8 sur la Sassandra-Marahoué. GBP/USD sous 1,26 après l'inflation UK. Pas d'alerte ENSO.",
      briefMore: '— suite · 1 page · FR natif · 4 min de lecture · exemple éditorial',
      chartEyebrow: 'CAU26 · 30 séances',
      chartScaleLabel: 'Échelle',
      chartCaption: 'Closes officiels CAU26 · ICE Europe',
      audioKicker: 'Extrait · brief audio · 30 s',
      audioHeading: 'À écouter sur le chemin',
      audioHeadingEm: 'du bureau.',
      audioPlayLabel: "Lire l'extrait",
      audioPauseLabel: 'Mettre en pause',
      audioSeekLabel: 'Position de lecture',
    },
    contact: {
      sectionEyebrow: 'V · Accès',
      heading: 'Le lirez-vous',
      headingEm: 'demain ?',
      body: "Compass est sur invitation uniquement. Dites-nous qui vous êtes, ce que vous tradez, et à quelle heure la cloche sonne pour vous. Réponse sous un jour ouvré. Accès d'essai possible pour les desks qualifiés.",
      ctaPrimary: 'Contacter le Pôle commercial',
      email: 'contact@com-compass.com',
    },
    footer: {
      deck: "La rédaction quotidienne d'intelligence sur le cacao ICE.",
      schedule: 'Compilé 19:30 UTC J-1 · Dispo dès 00:00 UTC J · Lun–Ven · Depuis 2025',
      colReadHeading: 'Sommaire',
      colRead1: 'Lecture',
      colRead2: 'Méthodologie',
      colRead3: 'Distribution',
      colContactHeading: 'Contact',
      colContact1: 'Accès',
      colContact2: 'Email',
      colLegalHeading: 'Informations légales',
      colLegal1: 'Mentions légales',
      colLegal2: 'Conditions générales',
      colLegal3: 'Politique de confidentialité',
      colLegal4: 'Tarifs et conditions',
      colLegal5: 'Méthodologie et transparence',
      microLegal: 'Mentions légales',
      // A3 — the MAR qualification opens the notice, and the last sentence
      // now uses the French category (CIF), not the US "registered investment
      // adviser" it was translating. Counsel's note to the CTO, § A3.
      disclaimerLead: "Les lectures techniques publiées constituent des <strong>recommandations d'investissement</strong> au sens du règlement (UE) n° 596/2014. Elles sont générales et identiques pour tous les abonnés.",
      disclaimerLeadLink: 'Méthodologie et transparence',
      disclaimer: "<strong>Avertissement.</strong> Compass CC publie de l'intelligence de marché et un support à la décision pour les futures sur le cacao ICE. Cela ne constitue ni un conseil en investissement, ni une sollicitation. Le trading de futures comporte un risque substantiel de perte. Les performances passées ne préjugent pas des performances futures. Compass CC n'est ni prestataire de services d'investissement, ni conseiller en investissements financiers, ni courtier, ni plateforme de négociation.",
      copyright: '© 2026 Commodities Compass · ICE Cocoa #7',
    },
    meta: {
      title: 'Compass CC — Le brief quotidien du cacao ICE',
      description: "Un signal, un brief, chaque matin avant la cloche. La rédaction éditoriale qui décode le marché du cacao ICE pour les desks institutionnels.",
    },
    notFound: {
      pageTitle: '404 · Page introuvable — Compass CC',
      eyebrow: 'Erreur 404',
      title: 'Page introuvable.',
      deck: "Cette URL n'existe pas, plus, ou a peut-être été déplacée. Pas de signal à cette adresse — retour à l'édition du jour.",
      ctaHome: "Retour à l'accueil",
      ctaContact: 'Signaler un lien cassé',
    },
    // The standalone /disclaimer/ page was retired: it competed with the
    // published legal notice on the same subject, and two documents that
    // disagree is a contradiction handed to whoever looks for one.
    // Its notice now lives in the footer and in /mentions-legales.
    legalPage: { backToHome: "Retour à la page d'accueil" },
  },
  en: {
    masthead: {
      pubName: 'COMPASS CC',
      tagline: "The daily ICE cocoa briefing",
      navWhat: 'Reading',
      navMethod: 'Methodology',
      navBrief: 'Distribution',
      navContact: 'Access',
      signIn: 'Sign in',
      cta: 'Request access',
      langSwitchAria: 'Switch to French',
    },
    hero: {
      title: 'Decide before',
      titleAccent: 'the',
      titleAccentEm: 'bell.',
      lede: "Compass CC is the daily editorial reading of the ICE cocoa market. One conviction published every night, read by trading desks before LIFFE's opening bell. Four minutes to catch up before the session opens.",
      ctaPrimary: 'Request access',
      ctaSecondary: 'See the methodology',
      signalAside: "Today's signal preview",
      signalLabel: "Today's signal · Example",
      signalPill: 'OPEN',
      signalHeading: 'Signal OPEN —',
      signalHeadingEm: 'Bullish pressure on cocoa',
      statContract: 'CAZ26',
      statContractValue: '£2,998',
      statDay: 'D/D',
      statDayValue: '+0.77%',
      statHorizon: 'Horizon',
      statHorizonValue: 'D+1',
      mini1Label: 'One single conviction',
      mini1ValuePrefix: 'OPEN, MONITOR',
      mini1ValueMiddle: 'or',
      mini1ValueEm: 'HEDGE.',
      mini2Label: 'Live from 00:00 UTC',
      mini2ValuePrefix: 'Before',
      mini2ValueRest: 'the bell.',
      mini3Label: 'Audio · 4 min',
      mini3ValuePrefix: 'On',
      mini3ValueRest: 'your way to the desk.',
    },
    bento: {
      sectionRoman: 'II',
      sectionTitle: 'Reading',
      sectionMeta: '5 cells · 1 conviction',
      lede: 'One page,',
      ledeEm: 'several readings.',
      deck: "No infinite feed. No analyst call. One screen, opened once a day, four minutes to read or to listen.",
      cell1Eyebrow: "Today's signal",
      cell1Heading: 'A',
      cell1HeadingEm: 'Compass',
      cell1Signal: 'OPEN',
      cell1Horizon: 'Horizon ~4 d',
      cell1Edition: 'Edition No. 312 · Week 24',
      cell2Eyebrow: 'The brief',
      cell2Heading: 'One',
      cell2HeadingEm: 'page,',
      cell2HeadingRest: 'in plain prose.',
      cell2Body: "Technicals, origins weather, press, supply & demand — one editorial page written every day by the desk.",
      cell3Eyebrow: 'Audio',
      cell3Heading: '4',
      cell3HeadingEm: 'minutes,',
      cell3HeadingRest: 'every day.',
      cell3Body: 'Daily podcast format. Listen on your way to the desk, or while the dashboard loads in the background.',
    },
    method: {
      sectionRoman: 'III',
      sectionTitle: 'Editorial discipline',
      fullLink: 'Full methodology and transparency',
      sectionMeta: 'Four principles · Auditable',
      lede: 'Discipline against',
      ledeEm: 'the noise.',
      deck: "The cocoa market remains one of the most opaque in modern finance. Compass responds with a clear editorial discipline — four simple principles, held every trading day since 2025.",
      p1Roman: 'i',
      p1Title: 'One single',
      p1TitleEm: 'conviction.',
      p1Body: "Compass publishes one reading per day: <strong>OPEN</strong>, <strong>MONITOR</strong> or <strong>HEDGE</strong>. No parallel scenarios, no cautious middle, no à-la-carte options. One decision, signed and dated, that can be checked against the next bell.",
      p1Pills: ['One decision/day', 'Signed & dated', 'Verifiable'],
      p2Roman: 'ii',
      p2Title: 'Cross-checked',
      p2TitleEm: 'sources.',
      p2Body: "Compass cross-checks dozens of signals every day: official prices, commercial positioning, certified stocks, origins weather, macro-finance. Every source is public or regulatory. No proprietary data whose lineage you can't trace.",
      p2Pills: ['Public sources', 'Multi-domain', 'Auditable'],
      p3Roman: 'iii',
      p3Title: 'Written to',
      p3TitleEm: 'be read.',
      p3Body: "Each brief is written as one page of prose, not template-stamped output. The numeric verdict becomes a text a trader can read in four minutes or hear in four minutes twenty — in the car, walking, waiting for the open.",
      p3Pills: ['One page', 'Native FR/EN', 'Audio included'],
      p4Roman: 'iv',
      p4Title: 'On a fixed',
      p4TitleEm: 'schedule.',
      p4Body: "Compiled at <strong>19:30 UTC</strong> the night before, live from <strong>00:00 UTC</strong> on the day. Monday to Friday, uninterrupted since 2025. The same appointment, every morning, before you open the dashboard.",
      p4Pills: ['Compiled 19:30 UTC D-1', 'Live 00:00 UTC D', 'Since 2025'],
    },
    brief: {
      sectionRoman: 'IV',
      sectionTitle: 'Distribution',
      sectionMeta: 'Audio + text + dashboard',
      lede: 'Live from',
      ledeEm: 'midnight UTC.',
      deck: "Compiled the night before at 19:30 UTC. Live on the day from 00:00 UTC. Three formats are waiting — pick the one that fits your morning.",
      briefKicker: '2026-06-12 · Brief · Week 24',
      briefBadge: 'HEDGE',
      briefHeading: 'Signal',
      briefHeadingEm: 'HEDGE',
      briefHeadingTail: '— Bearish pressure on cocoa',
      briefP1: "Compass reading aligned on the HEDGE position, net conviction (<em>strong</em>). CLOSE drops from 2,975 to 2,964 (−0.37%), VOLUME collapses from 11,241 to 5,697 (−49.3%) — sharp commercial disengagement.",
      briefP2: "<strong>Technicals.</strong> CAZ26 in the lower half of the weekly range. Stochastic %K below 30, MACD negative and sloping down, Wilder ATR rising. Volume/OI ratio contracting to 0.14 — exhaustion of May's bullish momentum.",
      briefP3: "<strong>Fundamentals.</strong> Ivorian port arrivals +8.2% on the week, above the 5-year median. ICCO revises production to 4.72 Mt (vs 4.55 Mt). ECA Q1 2026 grindings stable at −1.1% YoY.",
      briefP4: "<strong>Weather & macro.</strong> Côte d'Ivoire + Ghana exit a dry week favourable to drying, rain window expected D+5 to D+8 on the Sassandra-Marahoué. GBP/USD below 1.26 after UK inflation. No ENSO alert.",
      briefMore: '— continued · 1 page · native EN · 4 min read · editorial sample',
      chartEyebrow: 'CAU26 · 30 sessions',
      chartScaleLabel: 'Range',
      chartCaption: 'Official CAU26 closes · ICE Europe',
      audioKicker: 'Sample · audio brief · 30 s',
      audioHeading: 'Listen on your way',
      audioHeadingEm: 'to the desk.',
      audioPlayLabel: 'Play sample',
      audioPauseLabel: 'Pause',
      audioSeekLabel: 'Playback position',
    },
    contact: {
      sectionEyebrow: 'V · Access',
      heading: 'Will you read it',
      headingEm: 'tomorrow?',
      body: "Compass is invite-only. Tell us who you are, what you trade, and what time the bell rings for you. Reply within one business day. Trial access possible for qualified desks.",
      ctaPrimary: 'Contact our sales team',
      email: 'contact@com-compass.com',
    },
    footer: {
      deck: "The daily intelligence desk for ICE cocoa.",
      schedule: 'Compiled 19:30 UTC D-1 · Live from 00:00 UTC D · Mon–Fri · Since 2025',
      colReadHeading: 'Contents',
      colRead1: 'Reading',
      colRead2: 'Methodology',
      colRead3: 'Distribution',
      colContactHeading: 'Contact',
      colContact1: 'Access',
      colContact2: 'Email',
      colLegalHeading: 'Legal information',
      colLegal1: 'Legal notice',
      colLegal2: 'Terms and conditions',
      colLegal3: 'Privacy policy',
      colLegal4: 'Pricing and terms',
      colLegal5: 'Methodology and transparency',
      microLegal: 'Legal notice',
      disclaimerLead: "The technical readings we publish are <strong>investment recommendations</strong> within the meaning of Regulation (EU) No 596/2014. They are general and identical for all subscribers.",
      disclaimerLeadLink: 'Methodology and transparency',
      disclaimer: "<strong>Disclaimer.</strong> Compass CC publishes market intelligence and decision support for ICE cocoa futures. It does not constitute investment advice or a solicitation. Trading futures carries a substantial risk of loss. Past performance is no guarantee of future results. Compass CC is neither an investment services provider, nor a financial investment adviser, nor a broker, nor a trading venue.",
      copyright: '© 2026 Commodities Compass · ICE Cocoa #7',
    },
    meta: {
      title: 'Compass CC — The daily ICE cocoa briefing',
      description: "One signal, one brief, every morning before the bell. Compass CC: the editorial desk decoding the ICE cocoa market for institutional traders.",
    },
    notFound: {
      pageTitle: '404 · Page not found — Compass CC',
      eyebrow: 'Error 404',
      title: 'Page not found.',
      deck: "This URL does not exist, no longer exists, or may have moved. No signal at this address — back to today's edition.",
      ctaHome: 'Back to home',
      ctaContact: 'Report a broken link',
    },
    // The standalone /disclaimer/ page was retired: it competed with the
    // published legal notice on the same subject, and two documents that
    // disagree is a contradiction handed to whoever looks for one.
    // Its notice now lives in the footer and in /mentions-legales.
    legalPage: { backToHome: 'Back to home' },
  },
} as const;

export function t(locale: Locale): (typeof strings)[Locale] {
  return strings[locale];
}

/**
 * The five published legal pages, and their slug in each locale.
 *
 * One map so a slug is declared once: the page file, the footer link, the
 * hreflang alternate and the language switcher all read from here. Changing a
 * URL in one place and not the others is how a legal page becomes unreachable
 * in one language while still being linked in the other.
 *
 * Source of the text: `.local/Juridique Compass/` (counsel's delivery,
 * 28 August 2026), cut at the `⛔` line.
 */
export const LEGAL_PAGES = {
  legalNotice: { fr: 'mentions-legales', en: 'legal-notice' },
  terms: { fr: 'cgv', en: 'terms' },
  privacy: { fr: 'confidentialite', en: 'privacy' },
  pricing: { fr: 'tarifs', en: 'pricing' },
  methodology: { fr: 'methodologie', en: 'methodology' },
} as const;

export type LegalPageKey = keyof typeof LEGAL_PAGES;

/** Absolute path of a legal page in one locale. */
export function legalPath(locale: Locale, key: LegalPageKey): string {
  return pathFor(locale, LEGAL_PAGES[key][locale]);
}

/**
 * The `{ fr, en }` counterpart paths of a page — what `hreflang` and the
 * language switcher need. Defaults to the two home pages for every page that
 * does not declare a key.
 */
export function alternatesFor(key?: LegalPageKey): Record<Locale, string> {
  if (!key) return { fr: pathFor('fr'), en: pathFor('en') };
  return { fr: legalPath('fr', key), en: legalPath('en', key) };
}

export function pathFor(locale: Locale, path: string = ''): string {
  // Always emit trailing slash — aligns with astro.config trailingSlash:'always'
  // and GCS website config which auto-redirects /foo → /foo/ (or /foo/index.html)
  // when there's no exact file match. Keeping this in one place avoids drift
  // between component links, canonicals, and hreflang alternates.
  const clean = path.replace(/^\/+|\/+$/g, '');
  if (locale === DEFAULT_LOCALE) return clean ? `/${clean}/` : '/';
  return clean ? `/${locale}/${clean}/` : `/${locale}/`;
}
