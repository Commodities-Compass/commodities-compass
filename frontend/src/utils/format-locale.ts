import { format } from 'date-fns';
import { enGB, fr } from 'date-fns/locale';

import type { Language } from '@/contexts/LanguageContext';

// Ghana English → en-GB conventions (day-month order, like French), so the
// date layout stays consistent when switching languages.
const DATE_LOCALES = { fr, en: enGB } as const;
const NUMBER_LOCALES: Record<Language, string> = { fr: 'fr-FR', en: 'en-GB' };

/** Locale-aware date formatting — replaces the hardcoded French month arrays. */
export function formatDate(
  date: Date,
  language: Language,
  pattern = 'd MMM yyyy',
): string {
  return format(date, pattern, { locale: DATE_LOCALES[language] });
}

/** Locale-aware number formatting via Intl. */
export function formatNumber(
  value: number,
  language: Language,
  options?: Intl.NumberFormatOptions,
): string {
  return new Intl.NumberFormat(NUMBER_LOCALES[language], options).format(value);
}
