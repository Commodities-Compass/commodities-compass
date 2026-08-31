import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '../test/test-utils';

let billingStatus: string | null = null;
vi.mock('@/contexts/EntitlementsContext', () => ({
  useEntitlements: () => ({
    billingStatus,
    enforced: true,
    entitlements: new Set<string>(),
    tier: null,
    isLoading: false,
    has: () => true,
    hasAny: () => true,
  }),
}));

const createPortalSession = vi.fn();
vi.mock('@/api/auth', () => ({
  authApi: {
    createPortalSession: () => createPortalSession(),
  },
}));

import { BillingBanner } from './billing-banner';

describe('BillingBanner', () => {
  beforeEach(() => {
    billingStatus = null;
    createPortalSession.mockReset();
  });

  it.each([null, 'active', 'trialing', 'manual'])(
    'renders nothing when billing_status is %s',
    (status) => {
      billingStatus = status;
      const { container } = render(<BillingBanner />);
      expect(container).toBeEmptyDOMElement();
    },
  );

  it('warns on past_due — the client still has full access, so this is the only signal', () => {
    billingStatus = 'past_due';
    render(<BillingBanner />);
    expect(screen.getByRole('status')).toBeInTheDocument();
    // The copy must not read as a cut-off: access is deliberately kept during
    // the Stripe retry window.
    expect(screen.getByText(/reste complet|stays fully open/i)).toBeInTheDocument();
  });

  it.each(['unpaid', 'canceled'])('warns on %s', (status) => {
    billingStatus = status;
    render(<BillingBanner />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('sends the client to the Stripe portal — the whole recovery loop', async () => {
    billingStatus = 'past_due';
    createPortalSession.mockResolvedValue({ url: 'https://billing.stripe.com/p/session_x' });

    const assign = vi.fn();
    Object.defineProperty(window, 'location', {
      value: { ...window.location, set href(v: string) { assign(v); } },
      writable: true,
    });

    render(<BillingBanner />);
    fireEvent.click(screen.getByRole('button'));

    await waitFor(() => expect(createPortalSession).toHaveBeenCalledOnce());
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith('https://billing.stripe.com/p/session_x'),
    );
  });

  it('shows an error instead of a stuck spinner when the portal call fails', async () => {
    billingStatus = 'unpaid';
    createPortalSession.mockRejectedValue(new Error('502'));

    render(<BillingBanner />);
    fireEvent.click(screen.getByRole('button'));

    expect(
      await screen.findByText(/Impossible d'ouvrir|Could not open/i),
    ).toBeInTheDocument();
    // Button usable again — a failed portal call is exactly when the client
    // most needs a way forward.
    expect(screen.getByRole('button')).not.toBeDisabled();
  });
});
