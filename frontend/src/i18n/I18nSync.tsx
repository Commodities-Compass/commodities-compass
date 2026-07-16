import { useEffect } from 'react';

import { useLanguage } from '@/hooks/useLanguage';

import i18n from './index';

/**
 * Bridges the LanguageProvider (source of truth, persisted to localStorage)
 * to i18next so every `t()` re-renders when the user switches language.
 * Renders nothing; mount it once inside <LanguageProvider>.
 */
export function I18nSync() {
  const { language } = useLanguage();

  useEffect(() => {
    if (i18n.language !== language) {
      void i18n.changeLanguage(language);
    }
  }, [language]);

  return null;
}
