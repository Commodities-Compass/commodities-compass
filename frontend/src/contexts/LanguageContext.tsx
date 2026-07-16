import { createContext, useState, useMemo, useCallback } from 'react';
import type { ReactNode } from 'react';

export type Language = 'fr' | 'en';

export const DEFAULT_LANGUAGE: Language = 'fr';

export const LANGUAGE_STORAGE_KEY = 'cc_language';

/**
 * Reads the persisted language from localStorage.
 * Returns DEFAULT_LANGUAGE ('fr') when localStorage is unavailable (SSR / disabled)
 * or when the stored value is anything other than a known Language.
 */
export function getStoredLanguage(): Language {
  if (typeof localStorage === 'undefined') {
    return DEFAULT_LANGUAGE;
  }
  const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY);
  if (stored === 'fr' || stored === 'en') {
    return stored;
  }
  return DEFAULT_LANGUAGE;
}

export interface LanguageContextValue {
  language: Language;
  setLanguage: (language: Language) => void;
}

export const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(getStoredLanguage);

  const setLanguage = useCallback((next: Language) => {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, next);
    }
    setLanguageState(next);
  }, []);

  const value = useMemo(() => ({ language, setLanguage }), [language, setLanguage]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}
