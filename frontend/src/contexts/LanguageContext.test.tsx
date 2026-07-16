import { describe, it, expect, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import {
  LanguageProvider,
  getStoredLanguage,
  LANGUAGE_STORAGE_KEY,
} from './LanguageContext';
import { useLanguage } from '@/hooks/useLanguage';

// The language plumbing defaults to 'fr' (existing French user). English is
// opt-in and persisted under the 'cc_language' localStorage key.

function wrapper({ children }: { children: ReactNode }) {
  return <LanguageProvider>{children}</LanguageProvider>;
}

describe('LanguageContext', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('defaults to fr when localStorage is empty', () => {
    const { result } = renderHook(() => useLanguage(), { wrapper });
    expect(result.current.language).toBe('fr');
  });

  it('setLanguage persists to localStorage (cc_language) and updates the value', () => {
    const { result } = renderHook(() => useLanguage(), { wrapper });

    act(() => {
      result.current.setLanguage('en');
    });

    expect(result.current.language).toBe('en');
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('en');
  });

  it('reads a previously stored valid value on init', () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
    const { result } = renderHook(() => useLanguage(), { wrapper });
    expect(result.current.language).toBe('en');
  });

  it('getStoredLanguage reads a valid stored value', () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
    expect(getStoredLanguage()).toBe('en');
  });

  it('getStoredLanguage ignores garbage and falls back to fr', () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, 'de');
    expect(getStoredLanguage()).toBe('fr');
  });
});
