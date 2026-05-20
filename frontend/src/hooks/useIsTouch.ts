import { useEffect, useState } from 'react';

/**
 * Returns `true` when the device has no hover capability and uses a coarse
 * pointer (i.e. touch screens). Listens to media-query changes (e.g. iPad with
 * an attached mouse/trackpad flipping between modes).
 *
 * Used to drop hover-only affordances (gauge tooltips, ticker pause-on-hover)
 * in favor of touch-friendly behaviors.
 */
export function useIsTouch(): boolean {
  const QUERY = '(hover: none) and (pointer: coarse)';
  const getInitial = () =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(QUERY).matches
      : false;

  const [isTouch, setIsTouch] = useState<boolean>(getInitial);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const mql = window.matchMedia(QUERY);
    const handler = (e: MediaQueryListEvent) => setIsTouch(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, []);

  return isTouch;
}
