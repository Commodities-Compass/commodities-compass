# Multi-Year IV History Sourcing — London Cocoa #7 Options

> **Why:** the IV-crush reversal signal is the only conditioning input that flipped the forward-return sign in
> 2025-26 (vol-high & mm_z>0 & iv_chg5<0 → fwd J+4 +1.42% vs −0.82% without), but our scraped `implied_volatility`
> only starts **2025-01-28** (n=9 firing days). Cannot validate without a multi-year history spanning the 2024
> super-spike + 2025 reversal. **Date:** 2026-06-12 (web-research memo).

## Recommendation (confirmed by a 4-front investigation, 2026-06-12)

**Databento `IFEU.IMPACT` options, symbol `C` (ICE Europe London Cocoa options) + self-computed Black-76 IV, 2018-12-23→today (~7.5y, covers the 2024 super-spike + 2025 reversal). Effective cost ≈ $0.**

**The cost unlock (key finding):** Databento **historical** ICE data is usage-based pay-per-GB ($0.50–1.75/GB) with **NO exchange license fee** — the $875/mo ICE license applies to the **LIVE** feed only (usage-based live was discontinued 2025-02-27; historical pay-per-GB remains). A `definition` + `statistics` (daily settlement + OI) pull for ONE option family, daily-only, 7y ≈ tens-to-low-hundreds of MB → **inside the $125 free sign-up credit → net ~$0** (worst case $1–2). NEVER pull the order book (mbo/mbp-10) — that's the huge/expensive part.

**Dead ends — confirmed, stop looking:**
- **ICE free public CDN** (the `cocoa_cert_stock_*.xls` path our stock scraper uses) is **stock-only**. Probed `cocoa_options_*`, `cocoa_settlement_*`, `cocoa_volatility_*`, directory listings → **all HTTP 404**. Option settlements live only behind paid MFT/subscription.
- **Barchart** `volatility-greeks` / `core-api` / `getFuturesOptions` are **snapshot-only (no date param)** — IV isn't an OHLCV field, so `getHistory` can't backfill it. That's exactly why our scraper only has IV from 2025-01-28. The only Barchart history is the enterprise "Solutions" product (London-cocoa coverage unconfirmed, sales-gated, ≫ tens of $).
- **No published cocoa vol index exists anywhere** (CBOE = OVX/GVZ oil/gold only; FRED = price only).
- **Realized-vol proxy** on our OHLCV: already built (`zero_cost_ivproxy_coherence.py`) and **proven a coin-flip** (50.7% sign-fidelity vs true IV). Not a substitute.

**Black-76 caveat:** London Cocoa options are American-exercise → Black-76 (European) slightly *under*-implies IV, but the bias is small for near-ATM short-dated and *consistent* → fine for a crush/regime signal. Swap to Barone-Adesi-Whaley later (~30 LOC, same inputs) if absolute accuracy matters.

## Ranked options

| # | Source | Depth | IV | Cost | Effort | Verdict |
|---|---|---|---|---|---|---|
| 1 | **Databento IFEU.IMPACT `C`** (`statistics`+`definition` schemas) | **2018-12-23→today** (covers 2024 spike + 2025 reversal) | self-compute Black-76 from settlements | usage-based $/GB; **$125 free credits**; daily-settlement pull likely fits free/low-$ (`metadata.get_cost` to price first) | medium (IV solver + 30d-CMV interp; options are **American** → Black-76 is an approx, fine for a crush *signal*) | **BEST** |
| 2 | **GARCH / realized-vol proxy** on our 2016+ OHLCV | 2016→today | proxy (not option IV) | $0 | low (we already vendor GARCH) | **Best free** — use as 2016-18 bridge + falsification; but RV/GARCH **lags** the crush (detects aftermath, mean-reverts), not a faithful substitute |
| 3 | Barchart futures-options (solutions team) | "from the 2000s" (may reach 2016) | pre-computed IV indices | paid, **unpriced** (quote-only `solutions@barchart.com`) | low | Only realistic source deeper than 2018; coverage of ICE EU cocoa **unverified** |
| 4 | ICE EOD Reports / ICE Data Services | authoritative | settlements | subscription (MFT/SFTP) | heavy | No free public archive; no edge over Databento |
| 5 | Refinitiv/LSEG, Bloomberg, CME Datamine/QuikStrike | — | vol surfaces | enterprise $ / no ICE-EU cocoa coverage | — | **Reject** for this task |

## Plan

1. `databento.metadata.get_cost` dry-run on `IFEU.IMPACT` `C` options `statistics`+`definition` (2018-12-23→today).
2. Pull settlements + definitions; build a 30-day constant-maturity ATM IV via Black-76 (American-exercise approx).
3. Backtest IV-crush (`iv_chg5 < 0` interaction) on 2018+ across the 2024 spike + 2025 reversal.
4. In parallel, build the GARCH/RV proxy on 2016+ OHLCV; measure proxy fidelity vs real IV on the 2018+ overlap.
5. If 2018+ is promising and pre-2018 *true* IV is needed for super-spike-grade validation, request a Barchart
   futures-options quote (only deeper-than-2018 path).

## Verified sources

- Databento cocoa options: `databento.com/datasets/IFEU.IMPACT/options/C`
- Databento ICE Europe launch (Dec-2018 start): `databento.com/blog/ice-futures-market-data`
- Databento pricing/credits: `databento.com/docs/faqs/usage-pricing-and-data-credits`
- Barchart futures-options (quote-only): `barchart.com/solutions/services/futures-options`
- ICE London Cocoa Options: `ice.com/products/37089084/London-Cocoa-Options`

**Unverified:** exact Databento $ for the cocoa pull (run `get_cost`); Barchart cocoa-options coverage + price.
