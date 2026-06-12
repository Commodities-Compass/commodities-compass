"""Black-76 pricing + implied-vol inversion for options on futures (dependency-light: stdlib + numpy only).

Black-76 (Black 1976) prices European options on a futures F:
    d1 = (ln(F/K) + 0.5*sigma^2*T) / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
    call = exp(-r*T) * (F*N(d1) - K*N(d2))
    put  = exp(-r*T) * (K*N(-d2) - F*N(-d1))

London Cocoa options are AMERICAN-exercise, so this European model slightly UNDER-implies IV. The bias is small
for near-ATM short-dated options and is CONSISTENT, so it's fine for a relative crush/regime signal (which is all
we need for the IV-crush reversal test). Swap to Barone-Adesi-Whaley later (~same inputs) if absolute IV matters.

No scipy dependency: normal CDF via math.erf, IV inversion via bracketed bisection (robust, monotone in sigma).
"""

from __future__ import annotations

import math


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black76_price(
    F: float, K: float, T: float, sigma: float, r: float, is_call: bool
) -> float:
    """Black-76 price of a European option on a future. T in years, sigma annualized."""
    if T <= 0 or sigma <= 0 or F <= 0 or K <= 0:
        # Intrinsic (discounted) as the degenerate limit.
        intrinsic = max(F - K, 0.0) if is_call else max(K - F, 0.0)
        return math.exp(-r * T) * intrinsic
    sqrtT = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    disc = math.exp(-r * T)
    if is_call:
        return disc * (F * norm_cdf(d1) - K * norm_cdf(d2))
    return disc * (K * norm_cdf(-d2) - F * norm_cdf(-d1))


def implied_vol(
    price: float,
    F: float,
    K: float,
    T: float,
    r: float,
    is_call: bool,
    *,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float | None:
    """Invert Black-76 for sigma via bisection. Returns None if the price is outside the no-arb bracket."""
    if not (price > 0 and F > 0 and K > 0 and T > 0):
        return None
    disc = math.exp(-r * T)
    intrinsic = disc * (max(F - K, 0.0) if is_call else max(K - F, 0.0))
    upper_bound = disc * (F if is_call else K)  # price as sigma -> inf
    # Price must sit strictly between intrinsic and the upper no-arb bound.
    if price <= intrinsic + 1e-9 or price >= upper_bound - 1e-12:
        return None
    f_lo = black76_price(F, K, T, lo, r, is_call) - price
    f_hi = black76_price(F, K, T, hi, r, is_call) - price
    if f_lo * f_hi > 0:
        return None  # not bracketed in [lo, hi]
    a, b = lo, hi
    for _ in range(max_iter):
        m = 0.5 * (a + b)
        fm = black76_price(F, K, T, m, r, is_call) - price
        if abs(fm) < tol or (b - a) < tol:
            return m
        if (black76_price(F, K, T, a, r, is_call) - price) * fm <= 0:
            b = m
        else:
            a = m
    return 0.5 * (a + b)


def atm_iv_for_expiry(
    chain: list[dict],
    F: float,
    T: float,
    r: float = 0.0,
) -> float | None:
    """ATM IV for a single expiry from its option settlements.

    ``chain``: list of {'K': strike, 'price': settlement, 'is_call': bool} for ONE expiry.
    Picks the strike nearest F, inverts IV on the available call AND put at that strike,
    returns their average (put-call IV should agree at ATM; averaging cuts settlement noise).
    """
    if not chain or F <= 0 or T <= 0:
        return None
    strikes = sorted({c["K"] for c in chain})
    if not strikes:
        return None
    k_atm = min(strikes, key=lambda k: abs(k - F))
    ivs: list[float] = []
    for c in chain:
        if c["K"] != k_atm:
            continue
        iv = implied_vol(c["price"], F, k_atm, T, r, c["is_call"])
        if iv is not None:
            ivs.append(iv)
    if not ivs:
        return None
    return sum(ivs) / len(ivs)


def cmv_30d_iv(
    expiry_ivs: list[tuple[float, float]], target_days: float = 30.0
) -> float | None:
    """Interpolate a 30-day constant-maturity ATM IV.

    ``expiry_ivs``: list of (days_to_expiry, atm_iv). Linear interpolation in DTE between the two
    expiries bracketing 30d; if 30d is outside the range, clamp to the nearest expiry's IV.
    """
    pts = sorted((float(d), float(v)) for d, v in expiry_ivs if v is not None and d > 0)
    if not pts:
        return None
    if len(pts) == 1:
        return pts[0][1]
    if target_days <= pts[0][0]:
        return pts[0][1]
    if target_days >= pts[-1][0]:
        return pts[-1][1]
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        if d0 <= target_days <= d1:
            w = (target_days - d0) / (d1 - d0)
            return v0 + w * (v1 - v0)
    return pts[-1][1]


if __name__ == "__main__":
    # Self-test (no Databento needed): round-trip a known ATM option.
    F, K, T, r, sig = 3000.0, 3000.0, 30 / 365, 0.0, 0.50
    call = black76_price(F, K, T, sig, r, True)
    put = black76_price(F, K, T, sig, r, False)
    iv_c = implied_vol(call, F, K, T, r, True)
    iv_p = implied_vol(put, F, K, T, r, False)
    print(
        f"ATM call={call:.3f} put={put:.3f}  (put-call parity holds: {abs(call - put) < 1e-6})"
    )
    print(f"recovered IV  call={iv_c:.4f}  put={iv_p:.4f}  (true={sig})")
    assert abs(iv_c - sig) < 1e-3 and abs(iv_p - sig) < 1e-3, (
        "Black-76 round-trip FAILED"
    )
    # 30d-CMV interp sanity
    cmv = cmv_30d_iv([(14, 0.60), (45, 0.40)])
    print(f"30d-CMV between (14d,0.60) and (45d,0.40) = {cmv:.4f}  (expect ~0.497)")
    print("Black-76 self-test PASSED")
