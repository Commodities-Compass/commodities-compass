import { describe, it, expect } from 'vitest';
import {
  shouldReloadForPreloadError,
  RELOAD_LOOP_WINDOW_MS,
} from './preload-error-reload';

describe('shouldReloadForPreloadError', () => {
  const now = 1_000_000;

  it('reloads on the first preload error (no prior reload)', () => {
    expect(shouldReloadForPreloadError(now, null)).toBe(true);
  });

  it('does NOT reload again within the loop window (fresh build also failed)', () => {
    expect(shouldReloadForPreloadError(now, now - 1)).toBe(false);
    expect(shouldReloadForPreloadError(now, now - RELOAD_LOOP_WINDOW_MS)).toBe(
      false
    );
  });

  it('reloads again once past the loop window (a later, separate deploy)', () => {
    expect(
      shouldReloadForPreloadError(now, now - RELOAD_LOOP_WINDOW_MS - 1)
    ).toBe(true);
  });
});
