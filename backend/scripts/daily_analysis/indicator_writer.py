"""INDICATOR sheet formula management for the daily analysis pipeline.

Handles the 2-slot HISTORIQUE row-shifting logic for columns Q and R:

    BEFORE (2 live HISTORIQUE rows at the bottom):
      Row N-1: Q=HISTORIQUE!R101  R=HISTORIQUE!T101   (older)
      Row N:   Q=HISTORIQUE!R102  R=HISTORIQUE!T102   (newer)

    AFTER (adding row N+1):
      Row N-1: Q=IF(N{row}="","",...) R=IF(Q{row}="",...) ← frozen (inline)
      Row N:   Q=HISTORIQUE!R101  R=HISTORIQUE!T101        ← demoted (was R102)
      Row N+1: Q=HISTORIQUE!R102  R=HISTORIQUE!T102        ← new row

R101/R102 are a 2-slot circular buffer in the HISTORIQUE sheet.
Each cycle: freeze the R101 row, demote R102→R101, new row gets R102.
"""

import json
import logging
import re
import time
from dataclasses import dataclass

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from scripts.daily_analysis.config import (
    FREEZE_Q_FORMULA,
    FREEZE_R_FORMULA,
    HISTORIQUE_Q_FORMULA,
    HISTORIQUE_R_FORMULA,
    SCOPES,
    SPREADSHEET_ID,
)

logger = logging.getLogger(__name__)

HISTORIQUE_REF_PATTERN = re.compile(r"=HISTORIQUE!R(\d+)")


@dataclass
class IndicatorSheetState:
    """Current state of the INDICATOR sheet's HISTORIQUE formula rows."""

    last_data_row: int
    older_row: int  # INDICATOR row with the LOWER HISTORIQUE ref (to freeze)
    newer_row: int  # INDICATOR row with the HIGHER HISTORIQUE ref (to demote)
    lower_ref: int  # Lower HISTORIQUE row number (e.g., 101)
    higher_ref: int  # Higher HISTORIQUE row number (e.g., 102)


@dataclass
class ReadBackResult:
    """Values read back from INDICATOR after formula recalculation."""

    final_indicator: float
    conclusion: str  # OPEN, MONITOR, or HEDGE
    row_number: int


class IndicatorWriterError(Exception):
    """Raised on INDICATOR sheet write failures."""


class IndicatorWriter:
    """Manages INDICATOR sheet writes and the HISTORIQUE formula row-shift."""

    def __init__(
        self, credentials_json: str, spreadsheet_id: str = SPREADSHEET_ID
    ) -> None:
        try:
            creds = json.loads(credentials_json)
            self.credentials = Credentials.from_service_account_info(
                creds, scopes=SCOPES
            )
            self.service = build("sheets", "v4", credentials=self.credentials)
            self.spreadsheet_id = spreadsheet_id
            logger.info("IndicatorWriter initialised")
        except (json.JSONDecodeError, Exception) as exc:
            raise IndicatorWriterError(f"Failed to init Sheets client: {exc}") from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_state(self, sheet_name: str) -> IndicatorSheetState:
        """Read current INDICATOR sheet state.

        Finds the last data row and the 2 rows with HISTORIQUE references.
        """
        col_a = self._get_values(f"{sheet_name}!A:A")
        all_rows = col_a.get("values", [])
        last_data_row = len(all_rows)
        if last_data_row < 3:
            raise IndicatorWriterError(
                f"INDICATOR sheet '{sheet_name}' has too few rows ({last_data_row})"
            )

        # Read Q formulas for the last 10 rows to locate the 2 HISTORIQUE refs
        start = max(2, last_data_row - 9)
        formulas = self._get_values(
            f"{sheet_name}!Q{start}:Q{last_data_row}",
            value_render_option="FORMULA",
        ).get("values", [])

        hist_rows: list[tuple[int, int]] = []
        for i, row in enumerate(formulas):
            q = row[0] if row else ""
            match = HISTORIQUE_REF_PATTERN.search(str(q))
            if match:
                hist_rows.append((start + i, int(match.group(1))))

        if len(hist_rows) < 2:
            raise IndicatorWriterError(
                f"Expected 2 HISTORIQUE refs in column Q, found {len(hist_rows)} "
                f"(rows {start}-{last_data_row})"
            )

        # The last 2 HISTORIQUE rows: sort by ref number
        hist_rows = hist_rows[-2:]
        hist_rows.sort(key=lambda x: x[1])

        state = IndicatorSheetState(
            last_data_row=last_data_row,
            older_row=hist_rows[0][0],
            newer_row=hist_rows[1][0],
            lower_ref=hist_rows[0][1],
            higher_ref=hist_rows[1][1],
        )
        logger.info(
            "INDICATOR state: last_row=%d | older_row=%d (R%d) | newer_row=%d (R%d)",
            state.last_data_row,
            state.older_row,
            state.lower_ref,
            state.newer_row,
            state.higher_ref,
        )
        return state

    def freeze_row(self, sheet_name: str, row: int, *, dry_run: bool = False) -> None:
        """Replace HISTORIQUE references with inline formulas."""
        q = FREEZE_Q_FORMULA.format(row=row)
        r = FREEZE_R_FORMULA.format(row=row)
        logger.info("Freeze row %d → Q=%s | R=%s", row, q, r)
        if not dry_run:
            self._update_values(f"{sheet_name}!Q{row}:R{row}", [[q, r]])

    def write_historique_refs(
        self, sheet_name: str, row: int, ref: int, *, dry_run: bool = False
    ) -> None:
        """Write HISTORIQUE!R{ref} / HISTORIQUE!T{ref} to Q/R of a row."""
        q = HISTORIQUE_Q_FORMULA.format(ref=ref)
        r = HISTORIQUE_R_FORMULA.format(ref=ref)
        logger.info("Write HISTORIQUE refs row %d → Q=%s | R=%s", row, q, r)
        if not dry_run:
            self._update_values(f"{sheet_name}!Q{row}:R{row}", [[q, r]])

    def write_indicator_values(
        self,
        sheet_name: str,
        row: int,
        macroeco_bonus: float,
        eco: str,
        *,
        dry_run: bool = False,
    ) -> None:
        """Write MACROECO BONUS (P), MACROECO SCORE (S), and ECO (T) to an INDICATOR row."""
        macroeco_score = 1 + macroeco_bonus
        logger.info(
            "Write values row %d → P=%.2f | S=%.2f | T=%s",
            row,
            macroeco_bonus,
            macroeco_score,
            eco[:60],
        )
        if not dry_run:
            self._update_values(f"{sheet_name}!P{row}", [[macroeco_bonus]])
            self._update_values(f"{sheet_name}!S{row}", [[macroeco_score]])
            self._update_values(f"{sheet_name}!T{row}", [[eco]])

    def read_back(
        self,
        sheet_name: str,
        row: int,
        *,
        max_retries: int = 3,
        initial_delay: float = 2.0,
    ) -> ReadBackResult:
        """Wait for Sheets recalculation then read Q and R values.

        Retries with exponential backoff if values are empty or stale.
        """
        delay = initial_delay

        for attempt in range(1, max_retries + 1):
            logger.info(
                "Read-back attempt %d/%d (%.1fs delay) for row %d",
                attempt,
                max_retries,
                delay,
                row,
            )
            time.sleep(delay)

            result = self._get_values(f"{sheet_name}!Q{row}:R{row}")
            values = result.get("values", [[]])
            cells = values[0] if values else []

            q_raw = str(cells[0]).strip() if len(cells) > 0 else ""
            r_raw = str(cells[1]).strip() if len(cells) > 1 else ""

            if q_raw and r_raw and "#CALC" not in q_raw and "#REF" not in q_raw:
                try:
                    final_indicator = float(q_raw.replace(",", "."))
                except (ValueError, TypeError):
                    logger.warning("Cannot parse FINAL INDICATOR: %r", q_raw)
                    delay *= 2
                    continue

                conclusion = r_raw.upper()
                if conclusion in ("OPEN", "MONITOR", "HEDGE"):
                    logger.info(
                        "Read-back OK: FINAL_INDICATOR=%.4f CONCLUSION=%s",
                        final_indicator,
                        conclusion,
                    )
                    return ReadBackResult(
                        final_indicator=final_indicator,
                        conclusion=conclusion,
                        row_number=row,
                    )

            logger.warning(
                "Read-back attempt %d: Q=%r R=%r — retrying", attempt, q_raw, r_raw
            )
            delay *= 2

        raise IndicatorWriterError(
            f"Read-back failed for row {row} after {max_retries} attempts"
        )

    def has_indicator_for_date(self, sheet_name: str, date_str: str) -> bool:
        """Check if INDICATOR sheet already has a row for the given date (col P filled)."""
        col_a = self._get_values(f"{sheet_name}!A:A")
        rows = col_a.get("values", [])
        for i, row in enumerate(rows[1:], start=2):  # skip header
            if row and str(row[0]).strip() == date_str:
                # Check if column P (MACROECO BONUS) is already filled
                p_val = self._get_values(f"{sheet_name}!P{i}")
                p_rows = p_val.get("values", [])
                if p_rows and p_rows[0] and str(p_rows[0][0]).strip():
                    logger.info(
                        "INDICATOR row %d already has data for %s (P=%s)",
                        i,
                        date_str,
                        p_rows[0][0],
                    )
                    return True
        return False

    def execute(
        self,
        sheet_name: str,
        macroeco_bonus: float,
        eco: str,
        *,
        dry_run: bool = False,
        force: bool = False,
        target_date_str: str = "",
    ) -> ReadBackResult:
        """Full row-shift operation.

        1. Idempotency check (skip if date already exists, unless --force)
        2. Freeze the older HISTORIQUE row (inline formulas)
        3. Demote the newer HISTORIQUE row (R102 → R101)
        4. Write MACROECO BONUS + ECO to the new row
        5. Write HISTORIQUE R102 refs to the new row
        6. Wait and read back FINAL INDICATOR + CONCLUSION
        """
        # Idempotency: check if data for this date already exists
        if target_date_str and not force:
            if self.has_indicator_for_date(sheet_name, target_date_str):
                raise IndicatorWriterError(
                    f"INDICATOR already has data for {target_date_str}. "
                    f"Use --force to overwrite."
                )

        state = self.get_state(sheet_name)
        new_row = state.last_data_row + 1

        # Step 1: freeze the older row
        self.freeze_row(sheet_name, state.older_row, dry_run=dry_run)

        # Step 2: demote the newer row (higher ref → lower ref)
        self.write_historique_refs(
            sheet_name, state.newer_row, state.lower_ref, dry_run=dry_run
        )

        # Step 3: write values to new row
        self.write_indicator_values(
            sheet_name, new_row, macroeco_bonus, eco, dry_run=dry_run
        )

        # Step 4: write HISTORIQUE refs to new row (gets the higher ref)
        self.write_historique_refs(
            sheet_name, new_row, state.higher_ref, dry_run=dry_run
        )

        # Step 5: read back
        if dry_run:
            logger.info("[DRY RUN] Skipping read-back for row %d", new_row)
            return ReadBackResult(
                final_indicator=0.0, conclusion="DRY_RUN", row_number=new_row
            )

        return self.read_back(sheet_name, new_row)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_values(
        self, range_: str, *, value_render_option: str = "FORMATTED_VALUE"
    ) -> dict:
        try:
            return (
                self.service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self.spreadsheet_id,
                    range=range_,
                    valueRenderOption=value_render_option,
                )
                .execute()
            )
        except HttpError as exc:
            raise IndicatorWriterError(f"Sheets read failed ({range_}): {exc}") from exc

    def _update_values(
        self,
        range_: str,
        values: list[list],
        *,
        value_input_option: str = "USER_ENTERED",
    ) -> dict:
        try:
            return (
                self.service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=self.spreadsheet_id,
                    range=range_,
                    valueInputOption=value_input_option,
                    body={"values": values},
                )
                .execute()
            )
        except HttpError as exc:
            raise IndicatorWriterError(
                f"Sheets write failed ({range_}): {exc}"
            ) from exc
