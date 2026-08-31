import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CreditCard, Loader2 } from 'lucide-react';

import { authApi } from '@/api/auth';
import { useEntitlements } from '@/contexts/EntitlementsContext';
import { Eyebrow } from '@/components/editorial';

/**
 * Payment-state banner — the client's only signal before their access lapses.
 *
 * Two states, and the difference matters:
 *
 * - `past_due`: a debit failed and Stripe is retrying (~2-3 weeks). Access is
 *   still FULL by design, so nothing else on the page changes — this banner is
 *   the whole notification. Amber, not red.
 * - `unpaid` / `canceled`: retries exhausted, the backend now denies. Red.
 *
 * The button opens the Stripe Customer Portal, where the client updates the
 * card themselves. That round-trip IS the recovery loop: on `invoice.paid` the
 * webhook drops the cached principal, so access returns immediately rather than
 * after the 10-minute TTL.
 */
const NEEDS_ATTENTION = new Set(['past_due', 'unpaid', 'canceled']);

export function BillingBanner() {
  const { t } = useTranslation();
  const { billingStatus } = useEntitlements();
  const [opening, setOpening] = useState(false);
  const [failed, setFailed] = useState(false);

  if (!billingStatus || !NEEDS_ATTENTION.has(billingStatus)) return null;

  const isRetrying = billingStatus === 'past_due';

  const openPortal = async () => {
    setOpening(true);
    setFailed(false);
    try {
      const { url } = await authApi.createPortalSession();
      window.location.href = url;
    } catch {
      // Never leave the client stuck on a spinner with no explanation: a
      // failed portal call is exactly when they most need a way forward.
      setFailed(true);
      setOpening(false);
    }
  };

  return (
    <div
      role="status"
      aria-live="polite"
      className={`w-full border-b px-4 py-3 ${
        isRetrying
          ? 'border-[color:var(--color-signal-monitor)]/30 bg-[color:var(--color-signal-monitor)]/10'
          : 'border-[color:var(--color-signal-hedge)]/30 bg-[color:var(--color-signal-hedge)]/10'
      }`}
    >
      <div className="mx-auto flex max-w-7xl flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <AlertTriangle
            aria-hidden
            className={`mt-0.5 h-4 w-4 shrink-0 ${
              isRetrying
                ? 'text-[color:var(--color-signal-monitor)]'
                : 'text-[color:var(--color-signal-hedge)]'
            }`}
          />
          <div>
            <Eyebrow tone="primary">
              {isRetrying ? t('billing.pastDueTitle') : t('billing.unpaidTitle')}
            </Eyebrow>
            <p className="mt-1 text-sm text-[color:var(--ink-mid)]">
              {isRetrying ? t('billing.pastDueBody') : t('billing.unpaidBody')}
            </p>
            {failed && (
              <p className="mt-1 text-sm text-[color:var(--color-signal-hedge)]">
                {t('billing.error')}
              </p>
            )}
          </div>
        </div>

        <button
          type="button"
          onClick={openPortal}
          disabled={opening}
          className="inline-flex shrink-0 items-center gap-2 border border-[color:var(--ink)] px-4 py-2 font-mono text-[11px] uppercase tracking-wider text-[color:var(--ink)] transition-colors hover:bg-[color:var(--ink)] hover:text-[color:var(--paper)] disabled:opacity-60"
        >
          {opening ? (
            <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <CreditCard aria-hidden className="h-3.5 w-3.5" />
          )}
          {opening ? t('billing.opening') : t('billing.manage')}
        </button>
      </div>
    </div>
  );
}
