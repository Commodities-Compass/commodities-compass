import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import en from './locales/en.json';
import fr from './locales/fr.json';

// Initial language: mirror the LanguageProvider's localStorage key ('cc_language').
// Default is French — English is opt-in (US-0/US-2). The <I18nSync> component
// keeps i18next in sync with the LanguageProvider afterwards.
const stored = typeof localStorage !== 'undefined' ? localStorage.getItem('cc_language') : null;
const initialLng = stored === 'en' || stored === 'fr' ? stored : 'fr';

void i18n.use(initReactI18next).init({
  resources: {
    fr: { translation: fr },
    en: { translation: en },
  },
  lng: initialLng,
  fallbackLng: 'fr',
  interpolation: { escapeValue: false }, // React already escapes
  returnNull: false,
});

export default i18n;
