/**
 * Recovers from Vite's `vite:preloadError`, fired when a lazy-loaded chunk
 * (e.g. `dashboard-layout-<hash>.js` from `React.lazy`) fails to load.
 *
 * The classic "stale chunk after deploy" case: the user's tab was built on an
 * older release, a newer deploy replaced the content-hashed chunk files on the
 * server, and a route navigation triggers an `import()` of a URL that no longer
 * exists → 404 → "Failed to fetch dynamically imported module".
 *
 * Fix: reload once to pull the fresh index.html (which references the new chunk
 * hashes). A one-shot, time-boxed guard prevents a reload loop when the failure
 * is genuine (network down, or the fresh build also can't serve the chunk) — in
 * that case we let the error propagate to the Sentry ErrorBoundary.
 */

const RELOAD_FLAG_KEY = 'cc:preload-error-reloaded-at';

/**
 * If a preload error fires again within this window of our last reload, the
 * fresh build could not serve the chunk either — stop reloading and surface it.
 */
export const RELOAD_LOOP_WINDOW_MS = 10_000;

/** Pure decision: reload only when we did not just reload (loop guard). */
export function shouldReloadForPreloadError(
  now: number,
  lastReloadAt: number | null
): boolean {
  if (lastReloadAt === null) return true;
  return now - lastReloadAt > RELOAD_LOOP_WINDOW_MS;
}

function readLastReloadAt(): number | null {
  try {
    const raw = sessionStorage.getItem(RELOAD_FLAG_KEY);
    if (!raw) return null;
    const parsed = Number.parseInt(raw, 10);
    return Number.isNaN(parsed) ? null : parsed;
  } catch {
    // sessionStorage unavailable (private mode, storage disabled) — treat as
    // first attempt so we still recover the common case.
    return null;
  }
}

function writeLastReloadAt(now: number): void {
  try {
    sessionStorage.setItem(RELOAD_FLAG_KEY, String(now));
  } catch {
    // Non-fatal: without the flag we lose loop protection, but reloading once
    // is still the right recovery for the overwhelmingly common single-deploy
    // case.
  }
}

/**
 * Registers the global `vite:preloadError` handler. Call once at startup,
 * before rendering.
 */
export function registerPreloadErrorReload(): void {
  window.addEventListener('vite:preloadError', (event) => {
    const now = Date.now();

    if (!shouldReloadForPreloadError(now, readLastReloadAt())) {
      // Loop guard tripped: let Vite's default fire → ErrorBoundary + Sentry.
      return;
    }

    // We are recovering by reloading — suppress Vite's re-throw so this benign,
    // self-healing case does not pollute Sentry.
    event.preventDefault();
    writeLastReloadAt(now);
    window.location.reload();
  });
}
