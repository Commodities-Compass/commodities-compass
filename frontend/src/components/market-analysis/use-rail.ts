import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Returns true when the user has asked the OS to reduce motion.
 *
 * Read at call time rather than cached in state: `scrollTo({behavior})` is a
 * one-shot imperative call, so the value only matters at the moment we scroll.
 */
function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

interface UseRailResult {
  trackRef: React.RefObject<HTMLDivElement | null>;
  activeIndex: number;
  goTo: (index: number) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => void;
}

/**
 * Index state for a CSS scroll-snap track.
 *
 * The browser owns the scrolling (native snap + touch momentum); this hook only
 * mirrors *which* panel is settled, and drives programmatic navigation from the
 * folio controls.
 *
 * Two details that are easy to get wrong:
 * - `scrollTo({behavior: 'smooth'})` in JS OVERRIDES the CSS `scroll-behavior`
 *   rule, so the reduced-motion branch has to live here too — a media query in
 *   the stylesheet alone would be silently ignored. It must resolve to
 *   `'instant'`, not `'auto'` (see `goTo`).
 * - `scrollend` is the correct settle signal, but the debounced `scroll`
 *   fallback is kept for engines that don't ship it yet.
 */
export function useRail(panelCount: number): UseRailResult {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  const goTo = useCallback(
    (index: number) => {
      const track = trackRef.current;
      if (!track) return;
      const clamped = Math.max(0, Math.min(panelCount - 1, index));
      const panel = track.children[clamped] as HTMLElement | undefined;
      const first = track.children[0] as HTMLElement | undefined;
      if (!panel || !first) return;

      track.scrollTo({
        left: panel.offsetLeft - first.offsetLeft,
        // 'instant', NOT 'auto': per CSSOM, `auto` defers to the element's
        // computed `scroll-behavior`, which is `smooth` here — so `auto` would
        // animate anyway and this branch would be decorative. Verified in
        // Chrome: with 'auto' the track was still mid-flight two frames after
        // the click; with 'instant' it lands on the target immediately.
        behavior: prefersReducedMotion() ? 'instant' : 'smooth',
      });
      setActiveIndex(clamped);
    },
    [panelCount]
  );

  // Mirror the settled panel back into state — covers swipe, trackpad, and
  // find-in-page, all of which move the track without going through `goTo`.
  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;

    const settle = () => {
      const first = track.children[0] as HTMLElement | undefined;
      if (!first) return;
      let nearest = 0;
      let nearestDistance = Number.POSITIVE_INFINITY;
      Array.from(track.children).forEach((child, i) => {
        const offset = (child as HTMLElement).offsetLeft - first.offsetLeft;
        const distance = Math.abs(offset - track.scrollLeft);
        if (distance < nearestDistance) {
          nearestDistance = distance;
          nearest = i;
        }
      });
      setActiveIndex(nearest);
    };

    if ('onscrollend' in window) {
      track.addEventListener('scrollend', settle);
      return () => track.removeEventListener('scrollend', settle);
    }

    let timer: ReturnType<typeof setTimeout> | undefined;
    const onScroll = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(settle, 100);
    };
    track.addEventListener('scroll', onScroll);
    return () => {
      if (timer) clearTimeout(timer);
      track.removeEventListener('scroll', onScroll);
    };
  }, [panelCount]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        goTo(activeIndex + 1);
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        goTo(activeIndex - 1);
      } else if (e.key === 'Home') {
        e.preventDefault();
        goTo(0);
      } else if (e.key === 'End') {
        e.preventDefault();
        goTo(panelCount - 1);
      }
    },
    [activeIndex, goTo, panelCount]
  );

  return { trackRef, activeIndex, goTo, onKeyDown };
}
