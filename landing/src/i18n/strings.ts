/**
 * Bilingual copy registry.
 *
 * Source of truth for every visible string on the landing.
 * Keys are intentionally flat and prefixed by section to make
 * page-level imports trivial:
 *
 *   import { t } from '@/i18n/strings';
 *   const copy = t('fr');
 *   copy.hero.title  →  "Decide before the bell."
 *
 * Hero H1 stays universal English ("Decide before the bell.") per
 * brand decision — only the lede swaps FR/EN. Everything else is
 * fully translated.
 */
export type Locale = 'fr' | 'en';

export const LOCALES: Locale[] = ['fr', 'en'];

export const DEFAULT_LOCALE: Locale = 'fr';

const strings = {
  fr: {
    masthead: {
      pubName: 'Compass CC',
      tagline: 'Cocoa markets intelligence',
      navProduct: 'Produit',
      navMethod: 'Méthode',
      navSample: 'Brief du jour',
      navContact: 'Demande d\'accès',
      ctaShort: 'Accès',
    },
    hero: {
      eyebrow: 'Édition quotidienne · ICE Cocoa',
      title: 'Decide before',
      titleItalic: 'the bell.',
      lede: 'Un brief audio + un signal écrit, livrés chaque matin avant l\'ouverture. Une seule conviction sur le cacao, sourcée, datée, lisible en quatre minutes.',
      ctaPrimary: 'Demander un accès',
      ctaSecondary: 'Écouter un extrait',
    },
    signal: {
      eyebrow: 'Aujourd\'hui',
      label: 'Signal',
      open: 'OPEN',
      monitor: 'MONITOR',
      hedge: 'HEDGE',
      gauge: 'Compass Gauges',
      brief: 'Brief écrit',
      audio: 'Brief audio',
      ytd: 'YTD vs benchmark',
      hit: 'Hit rate',
    },
    method: {
      sectionTitle: 'Méthode',
      sectionRoman: 'III',
      sectionDeck: 'Quatre principes, tenus depuis le premier jour.',
      p1Number: '01',
      p1Title: 'Une seule conviction',
      p1Body: 'Pas de buffet d\'options. Chaque matin, une position, une raison, une fenêtre.',
      p2Number: '02',
      p2Title: 'Sources croisées',
      p2Body: 'Marché, presse spécialisée, météo cacaoyère. Rien n\'est repris sans recoupement.',
      p3Number: '03',
      p3Title: 'Écrit pour être lu',
      p3Body: 'Pas de dashboard à interpréter. Une phrase, des nuances, un texte signé.',
      p4Number: '04',
      p4Title: 'À heure fixe',
      p4Body: 'Publié chaque jour de séance avant l\'ouverture européenne. Sans exception.',
    },
    audio: {
      sectionTitle: 'Le brief du jour',
      sectionRoman: 'IV',
      sectionDeck: 'Trente secondes d\'extrait, généré chaque matin.',
      caption: 'Extrait — édition du 15 juin 2026',
      playLabel: 'Lecture',
      pauseLabel: 'Pause',
    },
    contact: {
      sectionTitle: 'Demander un accès',
      sectionRoman: 'V',
      sectionDeck: 'Accès sur invitation. Une réponse personnelle sous 48 h ouvrées.',
      email: 'issouf@com-compass.com',
      ctaMailto: 'Écrire à Issouf',
    },
    footer: {
      colophon: 'Compass CC — édition Paris',
      legal: 'Mentions légales',
      disclaimer: 'Avertissement',
      year: '© 2026 Compass CC',
      ledeDisclaimer: 'Les performances passées ne préjugent pas des performances futures.',
    },
  },
  en: {
    masthead: {
      pubName: 'Compass CC',
      tagline: 'Cocoa markets intelligence',
      navProduct: 'Product',
      navMethod: 'Method',
      navSample: 'Today\'s brief',
      navContact: 'Request access',
      ctaShort: 'Access',
    },
    hero: {
      eyebrow: 'Daily edition · ICE Cocoa',
      title: 'Decide before',
      titleItalic: 'the bell.',
      lede: 'A written signal and an audio brief, delivered every trading morning before the open. One conviction on cocoa, sourced, dated, and readable in four minutes.',
      ctaPrimary: 'Request access',
      ctaSecondary: 'Listen to a sample',
    },
    signal: {
      eyebrow: 'Today',
      label: 'Signal',
      open: 'OPEN',
      monitor: 'MONITOR',
      hedge: 'HEDGE',
      gauge: 'Compass Gauges',
      brief: 'Written brief',
      audio: 'Audio brief',
      ytd: 'YTD vs benchmark',
      hit: 'Hit rate',
    },
    method: {
      sectionTitle: 'Method',
      sectionRoman: 'III',
      sectionDeck: 'Four principles, held since day one.',
      p1Number: '01',
      p1Title: 'One conviction',
      p1Body: 'No buffet of options. Every morning, one position, one reason, one window.',
      p2Number: '02',
      p2Title: 'Cross-checked sources',
      p2Body: 'Markets, specialised press, cocoa-growing-region weather. Nothing is published without corroboration.',
      p3Number: '03',
      p3Title: 'Written to be read',
      p3Body: 'No dashboard to decipher. One sentence, the nuance, a signed text.',
      p4Number: '04',
      p4Title: 'On a fixed schedule',
      p4Body: 'Published every trading day before the European open. Without exception.',
    },
    audio: {
      sectionTitle: 'Today\'s brief',
      sectionRoman: 'IV',
      sectionDeck: 'A thirty-second sample, generated every morning.',
      caption: 'Sample — June 15, 2026 edition',
      playLabel: 'Play',
      pauseLabel: 'Pause',
    },
    contact: {
      sectionTitle: 'Request access',
      sectionRoman: 'V',
      sectionDeck: 'Invite-only. A personal reply within two business days.',
      email: 'issouf@com-compass.com',
      ctaMailto: 'Write to Issouf',
    },
    footer: {
      colophon: 'Compass CC — Paris edition',
      legal: 'Legal',
      disclaimer: 'Disclaimer',
      year: '© 2026 Compass CC',
      ledeDisclaimer: 'Past performance is no guarantee of future results.',
    },
  },
} as const;

export function t(locale: Locale): (typeof strings)[Locale] {
  return strings[locale];
}

export function pathFor(locale: Locale, path: string = ''): string {
  const clean = path.replace(/^\//, '');
  if (locale === DEFAULT_LOCALE) return `/${clean}`.replace(/\/$/, '') || '/';
  return `/${locale}/${clean}`.replace(/\/$/, '') || `/${locale}`;
}
