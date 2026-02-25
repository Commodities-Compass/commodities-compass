# US-005 — Google Sheets Integration Issues Log

## Context
Replacing Make.com DAILY BOT AI scenario (Module 23) with Python. The INDICATOR sheet has:
- **Columns A-O**: Regular formulas (per-row, must be dragged/copied down to each new row)
- **Column P**: MACROECO BONUS (written by our script)
- **Columns Q-R**: FINAL INDICATOR / CONCLUSION (HISTORIQUE refs, managed by our script)
- **Column S**: MACROECO SCORE (written by our script)
- **Column T**: ECO (written by our script)

Make.com Module 23 uses `google-sheets:addRow` with `INSERT_ROWS`, writing only indices 15 (P) and 19 (T).

---

## Issue #1 — `_update_values` doesn't create rows properly
**When**: First Railway deployment
**Symptom**: Row 351 created but column A empty, arrayformulas didn't extend
**Root cause**: Original code used `spreadsheets.values.update` on `A:T` to write the new row. This writes to existing grid cells without inserting a row, so arrayformulas (which need a proper row insertion to extend) didn't fire.
**Impact**: `get_state` couldn't find the row (column A empty), idempotency check failed, next run created duplicate row 352.

## Issue #2 — `get_state` only checked column A for last row
**When**: After Railway left INDICATOR_STAGING in corrupted state
**Symptom**: `Expected 2 HISTORIQUE refs in column Q, found 1 (rows 341-350)`
**Root cause**: `get_state` used `len(col_A)` as last data row. Row 351 had Q/R data but empty A (arrayformula didn't extend), so it was invisible.
**Fix applied**: Changed to `max(len(col_A), len(col_Q))` — column Q is always written by our script.
**Status**: ✅ Fixed

## Issue #3 — Date format mismatch (leading zeros)
**When**: First successful local run
**Symptom**: `METEO_ALL: no row found for 02/24/2026` despite row existing
**Root cause**: `strftime("%m/%d/%Y")` produces `02/24/2026` but Google Sheets `FORMATTED_VALUE` returns `2/24/2026` (no leading zero). Exact string comparison failed.
**Fix applied**: Added `_dates_match()` helper that parses both dates via `datetime.strptime` before comparing. Applied to `_read_macronews`, `_read_meteotoday`, and `has_indicator_for_date`.
**Status**: ✅ Fixed

## Issue #4 — Switched to `spreadsheets.values.append` with `INSERT_ROWS` + range `A:T`
**When**: Attempt to match Make.com Module 23 behavior
**Symptom**: Arrayformulas in A-O didn't extend, date showed `12/29/1899`
**Root cause**: Appending with range `A:T` and a 20-element sparse row `["", "", ..., macroeco_bonus, "", "", macroeco_score, eco]` writes empty strings to cells A-O. Empty strings are cell content that **blocks** arrayformula output. The `12/29/1899` value = Google Sheets epoch date (serial number 0/-1), meaning the arrayformula computed from empty/zero inputs.
**Status**: ❌ Reverted, led to Issue #5

## Issue #5 — `spreadsheets.values.append` with range `P:T` writes to wrong columns
**When**: Attempt to fix Issue #4 by only appending P:T
**Symptom**: MACROECO SCORE and ECO appeared in columns D and E instead of S and T
**Root cause**: `spreadsheets.values.append` ignores the column range for positioning. The API finds the "table" in the sheet (starting from column A), then writes values starting from the table's first column. So our 5-element array `[P, Q, R, S, T]` was placed at A-E.
**Google API behavior**: The range parameter in `append` only controls WHERE (which row) to append, NOT which columns receive the values. Values always start from the table's leftmost column.
**Status**: ❌ Reverted

## Issue #6 — `spreadsheets.values.append` with range `P:P` (single column)
**When**: Attempt to append only P, then update S/T separately
**Symptom**: Row created, P in correct column, S/T written correctly via update. But arrayformulas in A-O still did NOT extend. Date `12/29/1899` appeared (INSERT_ROWS triggered arrayformula but it computed wrong value from empty inputs).
**Root cause**: `INSERT_ROWS` via `P:P` range inserts a new row but the arrayformula computes before P has meaningful data context? Or the arrayformula depends on other columns that are empty at insert time.
**Status**: ❌ Partially works (P/S/T correct, Q/R correct, but A-O blank or wrong date)

## Issue #7 — Direct `_update_values` to P, S, T on existing empty row
**When**: Current approach — skip append entirely, write directly via update
**Symptom**: P, S, T in correct columns (P=351, S=351, T=351). Q/R HISTORIQUE refs correct. FINAL_INDICATOR read-back works (3.7000 → OPEN). But **arrayformulas did NOT extend** — A351 stays empty after 5 polling attempts (10 seconds).
**Root cause**: Writing to cells in an existing empty grid row does NOT trigger arrayformula extension. Arrayformulas only cover the "used range" of the sheet. A row beyond the used range is invisible to ARRAYFORMULA, even if individual cells have data.
**Status**: ❌ Current state — pipeline works functionally (Q/R compute correctly) but A-O are blank

## Issue #8 — Root cause: A-O are regular formulas, not ARRAYFORMULA
**When**: After all append/update approaches failed
**Root cause**: Columns A-O are **regular per-row formulas** (relative references), NOT ARRAYFORMULA from row 1. They must be explicitly copied/dragged down to each new row. All previous approaches (Issues #1-#7) assumed ARRAYFORMULA auto-extension, which was wrong.
**Fix applied**: `CopyPasteRequest` via `spreadsheets.batchUpdate` — copies A-O formulas from the last row to the new row (equivalent to dragging formulas down in the UI). Relative references auto-adjust. Then overwrite column A with the correct TECHNICALS date (since the copied formula may reference the wrong source row), then write P/S/T via update.
**Status**: ✅ Fixed — full pipeline works end-to-end, A-O formulas compute correctly

---

## Resolution (2026-02-25 13:00)

### Final approach (9 steps)
1. Idempotency check (skip if date already exists, unless `--force`)
2. Freeze the older HISTORIQUE row (inline formulas)
3. Demote the newer HISTORIQUE row (R102 → R101)
4. **`CopyPasteRequest`** — copy formulas A-O from last row to new row (`PASTE_FORMULA`)
5. Overwrite column A with the correct TECHNICALS date
6. Wait for formulas (B-O) to compute (poll A for non-empty value)
7. Write P, S, T to the new row via `values.update`
8. Write HISTORIQUE R102 refs to the new row (Q/R)
9. Read back FINAL INDICATOR + CONCLUSION (retry with exponential backoff)

### Key API methods used
- `spreadsheets.batchUpdate` with `CopyPasteRequest` (PASTE_FORMULA) — requires numeric sheet ID lookup
- `spreadsheets.values.update` (USER_ENTERED) — for P, S, T, Q, R, and date overwrites
- `spreadsheets.values.get` (FORMATTED_VALUE / FORMULA) — for reads and formula inspection

### All issues resolved ✅
- Full pipeline executes end-to-end (Steps 1-9)
- LLM Call #1 → MACROECO BONUS + ECO parsed correctly
- HISTORIQUE row-shift logic (freeze/demote/new) works perfectly
- A-O formulas copied and computed correctly
- Column A shows correct TECHNICALS date
- P, S, T written to correct columns on correct row
- Q/R HISTORIQUE refs written correctly
- Read-back of FINAL_INDICATOR + CONCLUSION works
- LLM Call #2 → DECISION/CONFIANCE/DIRECTION/CONCLUSION parsed correctly
- TECHNICALS write (AO-AR) works
- SCORE format matches expected `> ` + `        • ` bullet structure
- Date comparison handles leading zeros
- Idempotency checks work for both INDICATOR and TECHNICALS

### Approaches tried (summary)

| # | Approach | A-O formulas? | P/S/T correct? | Result |
|---|---|---|---|---|
| 1 | `values.update` on A:T | ❌ No row created | ✅ | Failed |
| 2 | `values.append` INSERT_ROWS on A:T | ❌ Blocked by empty strings | ✅ | Failed |
| 3 | `values.append` INSERT_ROWS on P:T | ❌ Values land in A-E | ❌ | Failed |
| 4 | `values.append` INSERT_ROWS on P:P + update S:T | ❌ Wrong date (epoch) | ✅ | Failed |
| 5 | `values.update` on P + S:T (no append) | ❌ Not in used range | ✅ | Failed |
| **6** | **`CopyPasteRequest` A-O + update P/S/T** | **✅** | **✅** | **Success** |

---

## Files modified
- `backend/scripts/daily_analysis/indicator_writer.py` — `_copy_formulas_down`, `_get_sheet_id`, `_wait_for_formulas`, `get_state` fix, `_dates_match`
- `backend/scripts/daily_analysis/sheets_reader.py` — `_dates_match` for METEO_ALL and BIBLIO_ALL lookups
- `backend/scripts/daily_analysis/prompts.py` — Call #2 SCORE format (section E)
- `backend/scripts/daily_analysis/analysis_engine.py` — Pass TECHNICALS date to indicator writer
