# Watchlist Evaluation Report — "A Surveiller"

**Date**: 2026-04-20
**Period analyzed**: 2025-05-02 to 2026-04-17 (215 trading days)
**Items evaluated**: 497 recommendations extracted from `pl_indicator_daily.conclusion`

---

## 1. Executive Summary

The daily analysis LLM generates 2-3 "A surveiller" watchlist items per day — threshold-based alerts like "RSI sous 40 = risque de cassure baissiere" or "Cassure haussiere si CLOSE depasse R1 a 6520". These recommendations have **never been evaluated** against actual market outcomes.

This study extracts, structures, and evaluates all 497 historical watchlist items against real market data on J+1, J+2, and J+3.

### Key Findings

- **Hit rate (condition materialized)**: 43% at J+1, 52% within 3 days
- **Directional accuracy (when condition hit, was the implied direction correct)**: **71%**
- **HIGH confidence items** (clear indicator + threshold + direction): 50% hit rate at J+1, 71% directional accuracy
- **Best indicators**: SUPPORT 1 (74% hit, 78% direction), RESISTANCE 1 (76% hit, 70% direction)
- **Worst indicators**: BOLLINGER INF (0% hit), VOLUME (73% hit but 40% direction — worse than random)

**Conclusion**: The watchlist recommendations contain **real signal**, especially for support/resistance levels. Directional accuracy at 71% is well above the 50% random baseline. The main improvement areas are (1) reducing vague "monitorer" items, (2) tightening RSI thresholds, and (3) dropping VOLUME/SIGNAL from watchlist items.

---

## 2. Methodology

### Extraction

Each day's `conclusion` field in `pl_indicator_daily` contains an analysis section followed by an "A SURVEILLER AUJOURD'HUI:" section with 2-3 bullet items. A regex cascade extracts and parses each item into:

- **Indicator**: RSI, CLOSE, SUPPORT 1, RESISTANCE 1, etc.
- **Comparator**: BELOW, ABOVE, CROSS_ABOVE, CROSS_BELOW, NEAR
- **Threshold**: numeric value (e.g., 40, 6520, 2483.67)
- **Implied direction**: HAUSSIERE, BAISSIERE, NEUTRE (inferred from French context words)
- **Parse confidence**: HIGH (indicator + threshold + direction), MEDIUM (indicator + threshold), LOW (missing threshold or indicator)

### Evaluation

For each extracted item, we look up actual market data on the next 3 trading days (J+1, J+2, J+3) from `pl_contract_data_daily` and `pl_derived_indicators`:

1. **Condition check**: Did the actual indicator value cross the recommended threshold?
   - BELOW: actual < threshold
   - ABOVE: actual > threshold
   - NEAR: |actual - threshold| / threshold < 2%
   - CROSS_ABOVE/CROSS_BELOW: actual crossed threshold
2. **Direction check**: At the first day the condition materialized, did the CLOSE price move in the implied direction compared to the issue date?

### Scoring

- **Hit**: condition materialized within the evaluation window
- **Direction correct**: CLOSE moved in the implied direction at first hit
- Items with implied_direction = NEUTRE are excluded from directional scoring

---

## 3. Global Statistics

| Metric | Value |
|--------|-------|
| Total items extracted | 497 |
| Parse confidence HIGH | 178 (36%) |
| Parse confidence MEDIUM | 127 (26%) |
| Parse confidence LOW | 192 (39%) |
| **Parse success rate (HIGH+MEDIUM)** | **61.4%** |
| Unparseable lines skipped | 29 |

### Hit Rates

| Window | Hits / Evaluable | Rate |
|--------|-----------------|------|
| J+1 | 126 / 292 | **43.2%** |
| J+2 | 115 / 281 | 40.9% |
| J+3 | 120 / 268 | 44.8% |
| Any (J+1 to J+3) | 158 / 305 | **51.8%** |

### Directional Accuracy (at first hit, excluding NEUTRE)

| Metric | Value |
|--------|-------|
| Correct / Evaluated | 72 / 101 |
| **Accuracy** | **71.3%** |

### Hit Rate by Implied Direction

| Direction | Items | Hit Rate (any) |
|-----------|-------|----------------|
| HAUSSIERE | 80 | 57.5% |
| BAISSIERE | 98 | 56.1% |
| NEUTRE | 127 | 44.9% |

The LLM's bullish and bearish calls hit at similar rates (~57%), well above neutral items (45%). Neutral items are predominantly "monitorer" recommendations without a clear directional thesis.

---

## 4. By Indicator

| Indicator | Items | Hit J+1 | Hit Any | Dir. Accuracy | Assessment |
|-----------|-------|---------|---------|--------------|------------|
| **SUPPORT 1** | 19 | 72% | **74%** | **78%** | Best overall signal |
| **RESISTANCE 1** | 37 | 62% | **76%** | **70%** | High volume, reliable |
| RSI | 121 | 35% | 41% | **79%** | Most frequent; good direction but low hit rate |
| CLOSE | 30 | 22% | 37% | **100%** | Rare hits but perfect direction |
| SUPPORT | 20 | 25% | 40% | 100% | Good when it hits |
| PIVOT | 9 | 67% | 78% | 50% | Hits often, direction is coin flip |
| OPEN INTEREST | 12 | 42% | 75% | 50% | Similar: hits but no directional edge |
| VOLUME | 15 | 47% | 73% | **40%** | Hits often, direction worse than random |
| SIGNAL | 15 | 67% | 67% | **40%** | Same: frequent hit, bad direction |
| BOLLINGER SUP | 11 | 46% | 46% | 33% | Unreliable |
| BOLLINGER INF | 8 | 0% | **0%** | N/A | Never hits — thresholds too extreme |
| VOLATILITE | 3 | 100% | 100% | 33% | Too few samples |

### Tier Classification

**Tier 1 — High signal, actionable** (hit rate > 50% AND direction accuracy > 65%):
- SUPPORT 1: the most reliable watchlist indicator
- RESISTANCE 1: high volume and consistent

**Tier 2 — Good direction, low hit rate** (direction accuracy > 70% but hit rate < 50%):
- RSI: when the threshold actually triggers, the directional call is right 79% of the time. But thresholds are set too aggressively (e.g., "RSI sous 40" rarely fires in a ranging market).
- CLOSE: perfect directional accuracy (100%) but very conservative thresholds mean it rarely triggers.

**Tier 3 — High hit, no directional edge** (hit rate > 50% but direction accuracy < 50%):
- VOLUME: hits 73% of the time but direction is worse than a coin flip (40%). The LLM overinterprets volume signals.
- SIGNAL (MACD Signal): same pattern — frequent hits, bad directional calls.
- PIVOT: hits 78% of the time (it's the middle of the range, so mechanical), but direction is 50/50.

**Tier 4 — Low signal** (hit rate < 30% OR too few samples):
- BOLLINGER INF: 0% hit rate. Thresholds are set at the extreme of the Bollinger band — price almost never reaches it in 3 days.
- VOLATILITE: 3 samples, not statistically meaningful.

---

## 5. By Comparator Type

| Comparator | Items | Hit J+1 | Hit Any | Dir. Accuracy |
|------------|-------|---------|---------|--------------|
| ABOVE | 110 | 49% | 51% | 71% |
| BELOW | 115 | 56% | 54% | 73% |
| CROSS_ABOVE | 7 | 71% | 86% | 67% |
| CROSS_BELOW | 21 | 47% | 48% | 80% |
| **NEAR** | **244** | **18%** | **10%** | **0%** |

**Critical finding**: NEAR comparator items represent 49% of all items (244/497) and have a 10% hit rate with 0% directional accuracy. These are the "Monitorer le niveau de SUPPORT a 2531" type items — vague monitoring recommendations with a 2% tolerance band that almost never triggers.

ABOVE and BELOW are the workhorses: balanced hit rates (~50%) and directional accuracy (~72%). CROSS_BELOW has the best directional accuracy (80%) — when the LLM says "cassure baissiere si CLOSE passe sous SUPPORT", it's right 4 out of 5 times.

---

## 6. By Parse Confidence

| Confidence | Items | Hit J+1 | Hit Any | Dir. Accuracy |
|------------|-------|---------|---------|--------------|
| HIGH | 178 | **50%** | **57%** | **71%** |
| MEDIUM | 127 | 33% | 45% | N/A |
| LOW | 192 | N/A | 0% | N/A |

HIGH confidence items (clear indicator + threshold + direction) perform significantly better. LOW confidence items are effectively noise — they have no parseable threshold and contribute nothing to the evaluation.

---

## 7. Monthly Trend

| Month | Items | Hit J+1 | Dir. Accuracy |
|-------|-------|---------|--------------|
| 2025-05 | 23 | 33% | 100% |
| 2025-06 | 40 | 32% | 57% |
| 2025-07 | 42 | 58% | 75% |
| 2025-08 | 27 | 45% | 71% |
| 2025-09 | 49 | 52% | 75% |
| 2025-10 | 49 | 38% | 50% |
| 2025-11 | 47 | 65% | 50% |
| 2025-12 | 32 | 36% | 100% |
| 2026-01 | 44 | 35% | 80% |
| 2026-02 | 53 | 69% | 53% |
| 2026-03 | 59 | 32% | 86% |
| 2026-04 | 32 | 23% | 100% |

No clear improving or degrading trend. Hit rates fluctuate between 23% and 69% depending on market regime — ranging markets (Oct 2025, Apr 2026) produce lower hit rates because thresholds are set for trending moves. Directional accuracy is generally better in months with fewer hits (the easy calls are more likely to be correct).

---

## 8. Concrete Examples

### Good calls (Hit J+1 + correct direction)

| Date | Item | Threshold Hit | CLOSE Move | Direction |
|------|------|--------------|-----------|-----------|
| 2025-05-05 | "RESISTANCE 1 ABOVE 6350" | R1 = 6570 > 6350 | 6328 -> 6452 (+2%) | HAUSSIERE OK |
| 2025-05-28 | "RSI sous 40 = cassure baissiere" | RSI = 36 < 40 | 6506 -> 6201 (-4.7%) | BAISSIERE OK |
| 2025-06-05 | "Cassure haussiere si CLOSE depasse 6630" | CLOSE = 6646 > 6630 | 6612 -> 6646 (+0.5%) | HAUSSIERE OK |
| 2026-04-16 | "CLOSE tombe sous SUPPORT 1 a 2484" | CLOSE = 2427 < 2484 | 2531 -> 2427 (-4.1%) | BAISSIERE OK |

### Bad calls (Hit J+1 + wrong direction)

| Date | Item | Threshold Hit | CLOSE Move | Direction |
|------|------|--------------|-----------|-----------|
| 2025-07-01 | "CLOSE depasse BOLLINGER SUP a 5670" | CLOSE = 5670 (at band) | 5670 -> 5545 (-2.2%) | HAUSSIERE WRONG |
| 2025-07-08 | "RSI sous 40 = baissiere" | RSI = 33 < 40 | 5397 -> 5542 (+2.7%) | BAISSIERE WRONG |
| 2025-06-06 | "RESISTANCE 1 CROSS_ABOVE 6676" | R1 hit | 6646 -> 6626 (-0.3%) | HAUSSIERE WRONG |

Pattern in bad calls: Bollinger breakouts and extended RSI trends in mean-reverting markets. When RSI is already deeply oversold (< 40 for multiple days), the next move is often a bounce rather than further decline.

---

## 9. Recommendations

### 9.1 Prompt Improvements (Section D of Call #2)

1. **Eliminate vague "Monitorer" items**: 49% of all items use NEAR comparator with no clear direction, producing 0% directional accuracy. Change the prompt to require every watchlist item to include:
   - A specific numeric threshold
   - An explicit direction (haussiere/baissiere)
   - A consequence ("= X si franchi")

   Current: *"Monitorer le niveau de SUPPORT a 2531."*
   Better: *"Cassure baissiere si CLOSE cloture sous SUPPORT 1 a 2531 — objectif S2 a 2450."*

2. **Tighten RSI thresholds**: RSI items have 79% directional accuracy but only 41% hit rate. The LLM uses extreme thresholds (30, 40, 70, 80) that are rarely reached. Consider asking for relative thresholds:
   - Instead of "RSI sous 40": "RSI en baisse de plus de 5 points par rapport a hier"
   - Or use the actual RSI value as anchor: "Si RSI casse sous [YESTERDAY_RSI - 5]"

3. **Drop VOLUME and SIGNAL from watchlist**: Both have high hit rates but directional accuracy below 50% (worse than random). Volume movements don't predict price direction in this market.

4. **Prioritize SUPPORT 1 and RESISTANCE 1**: These are the most actionable indicators — high hit rate AND high directional accuracy. The prompt should always include at least one support/resistance level.

### 9.2 Alert System Design (if implemented)

Based on these findings, a dedicated alert system should:

- **Only fire on Tier 1 indicators**: SUPPORT 1 and RESISTANCE 1 breakouts
- **Require HIGH parse confidence**: clear indicator + threshold + direction
- **Use BELOW and ABOVE comparators only** (not NEAR)
- **Expected performance**: ~70% hit rate, ~75% directional accuracy
- **Evaluation window**: J+1 primary. If J+1 misses, the next day's fresh recommendation supersedes.

### 9.3 Not Recommended

- Scoring NEUTRE items: they carry no signal and inflate the LOW confidence bucket
- Extending evaluation beyond J+3: new recommendations are issued daily, so older ones are stale
- Using BOLLINGER INF as alert triggers: 0% historical hit rate

---

## 10. Methodology Limitations

1. **Parse success rate at 61%**: 39% of items are LOW confidence (no parseable threshold), primarily from older conclusions with less structured output formats. Recent months (2026) have better parse rates due to prompt improvements.

2. **NEAR comparator tolerance**: Fixed at 2% of threshold value. For RSI (0-100 scale), 2% of 50 = 1 point — too tight. For CLOSE at 6000, 2% = 120 points — reasonable. A per-indicator tolerance would improve NEAR evaluation.

3. **Direction check uses CLOSE only**: An item about VOLUME or OI is evaluated by whether CLOSE moved in the implied direction. This conflates "the condition materialized" with "the price moved as implied." A more sophisticated evaluation would check whether the indicator itself moved further in the predicted direction.

4. **No statistical significance testing**: With 497 items and varying sample sizes per indicator (8 to 121), some results (especially BOLLINGER, VOLATILITE) are not statistically significant. Only RSI (n=121), RESISTANCE 1 (n=37), and CLOSE (n=30) have meaningful sample sizes.

---

## Appendix: Data & Reproduction

**Script**: `poetry run watchlist-eval [--start-date] [--end-date] [--csv output.csv] [--verbose]`
**Source code**: `backend/scripts/watchlist_eval/`
**CSV export**: Contains one row per evaluated item with all J+1/J+2/J+3 values, hit flags, and directional outcomes.
**Data source**: `pl_indicator_daily.conclusion` (215 days with "A surveiller" section) joined with `pl_contract_data_daily` and `pl_derived_indicators` for market data.
