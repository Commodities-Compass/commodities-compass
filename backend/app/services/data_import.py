"""
Data import service for Google Sheets to PostgreSQL migration.

This service handles the ETL pipeline for importing data from Google Sheets
into the PostgreSQL database using the defined SQLAlchemy models.
"""

import logging
import json
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Any

import pandas as pd
import sentry_sdk
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from sentry_sdk.crons import monitor

from app.core.database import AsyncSessionLocal
from app.core.excel_mappings import EXCEL_MAPPINGS
from app.core.config import settings
from app.core.sentry import init_sentry

logger = logging.getLogger(__name__)


class DataTransforms:
    """Data transformation utilities for cleaning Google Sheets data."""

    @staticmethod
    def parse_datetime(value) -> Optional[datetime]:
        """Parse various datetime formats from Google Sheets."""
        if pd.isna(value) or value is None:
            return None

        if isinstance(value, datetime):
            return value

        try:
            return pd.to_datetime(value)
        except Exception:
            return None

    @staticmethod
    def parse_decimal(value) -> Optional[Decimal]:
        """Parse decimal values from Google Sheets."""
        if pd.isna(value) or value is None or value == "":
            return None

        try:
            # Handle percentage values
            if isinstance(value, str) and value.endswith("%"):
                # Convert percentage to decimal (e.g., "9.06%" -> 0.0906)
                return Decimal(value.rstrip("%")) / 100

            # Handle US number format with commas as thousand separators
            if isinstance(value, str) and "," in value:
                value = value.replace(",", "")

            return Decimal(str(value))
        except Exception:
            return None

    @staticmethod
    def parse_decimal_from_string(value) -> Optional[Decimal]:
        """
        Parse decimal from string that may contain Google Sheets formulas.

        This handles cases where Google Sheets cells contain formulas like
        '=A1/B1' instead of computed values.
        """
        if pd.isna(value) or value is None or value == "":
            return None

        # If it's already a number, convert directly
        if isinstance(value, (int, float)):
            return Decimal(str(value))

        # If it's a string, try to extract numerical value
        if isinstance(value, str):
            # Handle percentage values first
            if value.endswith("%"):
                try:
                    return Decimal(value.rstrip("%")) / 100
                except Exception:
                    return None

            # Remove Google Sheets formula markers
            cleaned = value.replace("=", "").strip()

            # Try to parse as number
            try:
                return Decimal(cleaned)
            except Exception:
                # If it contains formula elements, log for manual review
                return None

        return None

    @staticmethod
    def parse_integer(value) -> Optional[int]:
        """Parse integer values from Google Sheets."""
        if pd.isna(value) or value is None or value == "":
            return None

        try:
            # Handle US number format with commas as thousand separators
            if isinstance(value, str) and "," in value:
                value = value.replace(",", "")

            return int(float(str(value)))
        except Exception:
            return None


class GoogleSheetsDataImporter:
    """Service for importing Google Sheets data into PostgreSQL."""

    def __init__(self, spreadsheet_id: str, credentials_json: str):
        self.spreadsheet_id = spreadsheet_id
        self.credentials_json = credentials_json
        self.transforms = DataTransforms()
        self.service = None

    def _get_service(self):
        """Initialize Google Sheets service with authentication."""
        if self.service is None:
            scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
            credentials_dict = json.loads(self.credentials_json)
            credentials = Credentials.from_service_account_info(
                credentials_dict, scopes=scopes
            )
            self.service = build("sheets", "v4", credentials=credentials)
        return self.service

    async def import_all_sheets(self, session: AsyncSession) -> Dict[str, Any]:
        """Import data from all sheets in the Google Spreadsheet."""
        results = {}
        service = self._get_service()

        # Get spreadsheet metadata to check available sheets
        try:
            spreadsheet = (
                service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
            )
            available_sheets = [
                sheet["properties"]["title"] for sheet in spreadsheet["sheets"]
            ]
        except Exception as e:
            return {"error": f"Failed to access spreadsheet: {str(e)}"}

        for mapping_key, config in EXCEL_MAPPINGS.items():
            sheet_name = config["sheet_name"]

            if sheet_name not in available_sheets:
                results[mapping_key] = {"error": f"Sheet {sheet_name} not found"}
                continue

            with sentry_sdk.start_span(op="sheet", description=mapping_key):
                try:
                    result = await self.import_sheet(session, mapping_key, config)
                    results[mapping_key] = result
                except Exception as e:
                    results[mapping_key] = {"error": str(e)}
                    sentry_sdk.capture_exception(e)

        return results

    async def import_sheet(
        self, session: AsyncSession, mapping_key: str, config: Dict
    ) -> Dict[str, Any]:
        """Import data from a single sheet."""
        sheet_name = config["sheet_name"]
        table_model = config["table_model"]
        column_mapping = config["column_mapping"]
        transforms = config["transforms"]
        service = self._get_service()

        # Read Google Sheet data
        try:
            result = (
                service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{sheet_name}!A:ZZ",  # Get all data
                )
                .execute()
            )
            values = result.get("values", [])
        except Exception as e:
            return {"error": f"Failed to read sheet {sheet_name}: {str(e)}"}

        if not values:
            return {"error": f"Sheet {sheet_name} is empty"}

        # Convert to DataFrame for easier processing
        df = pd.DataFrame(values[1:], columns=values[0] if values else [])

        # Track import statistics
        stats = {
            "sheet_name": sheet_name,
            "total_rows": len(df),
            "imported_rows": 0,
            "skipped_rows": 0,
            "errors": [],
        }

        # Clear existing data (for full refresh) - FIXED: Use proper SQLAlchemy delete
        await session.execute(delete(table_model))

        # Process each row using savepoints to isolate per-row failures
        for index, row in df.iterrows():
            try:
                async with session.begin_nested():
                    # Transform row data according to mapping
                    model_data = {}

                    for excel_col, db_col in column_mapping.items():
                        if excel_col in df.columns:
                            raw_value = (
                                row[excel_col] if not pd.isna(row[excel_col]) else None
                            )

                            # Convert empty strings to None
                            if raw_value == "" or raw_value == "nan":
                                raw_value = None

                            # Apply transformation if specified
                            if db_col in transforms:
                                transform_func = getattr(
                                    self.transforms, transforms[db_col]
                                )
                                transformed_value = transform_func(raw_value)
                            else:
                                transformed_value = raw_value

                            # Final check: ensure empty strings become None for optional fields
                            if transformed_value == "":
                                transformed_value = None

                            # Additional cleanup for percentage values that might not be in transforms
                            if isinstance(
                                transformed_value, str
                            ) and transformed_value.endswith("%"):
                                try:
                                    transformed_value = (
                                        Decimal(transformed_value.rstrip("%")) / 100
                                    )
                                except Exception:
                                    transformed_value = None

                            # No longer need to validate score fields since they now use DECIMAL(8,2)

                            model_data[db_col] = transformed_value

                    # Add default values for required fields if not present
                    if (
                        hasattr(table_model, "commodity_symbol")
                        and "commodity_symbol" not in model_data
                    ):
                        model_data["commodity_symbol"] = "CC"

                    # Handle required fields that might be missing from Google Sheets
                    if table_model.__name__ == "Indicator":
                        if (
                            "close_pivot" not in model_data
                            or model_data["close_pivot"] is None
                        ):
                            model_data["close_pivot"] = Decimal("0.0")

                        if (
                            "close_pivot_norm" not in model_data
                            or model_data["close_pivot_norm"] is None
                        ):
                            model_data["close_pivot_norm"] = Decimal("0.0")

                        if (
                            "macroeco_bonus" not in model_data
                            or model_data["macroeco_bonus"] is None
                        ):
                            model_data["macroeco_bonus"] = Decimal("0.0")

                        if "eco" not in model_data or model_data["eco"] is None:
                            model_data["eco"] = ""

                    # Handle weather_data required fields
                    if table_model.__name__ == "WeatherData":
                        for field in [
                            "text",
                            "summary",
                            "keywords",
                            "impact_synthesis",
                        ]:
                            if field not in model_data or model_data[field] is None:
                                model_data[field] = ""

                    # Handle market_research required fields
                    if table_model.__name__ == "MarketResearch":
                        for field in [
                            "author",
                            "summary",
                            "impact_synthesis",
                            "date_text",
                        ]:
                            if field not in model_data or model_data[field] is None:
                                model_data[field] = ""

                    # Create model instance
                    model_instance = table_model(**model_data)
                    session.add(model_instance)

                # Savepoint succeeded — count the row
                stats["imported_rows"] += 1

            except Exception as e:
                # Savepoint rolled back — row skipped, outer transaction intact
                stats["skipped_rows"] += 1
                stats["errors"].append(f"Row {index + 2}: {str(e)}")

        # Commit changes
        await session.commit()

        return stats

    async def validate_import(self, session: AsyncSession) -> Dict[str, Any]:
        """Validate the imported data."""
        validation_results = {}

        for mapping_key, config in EXCEL_MAPPINGS.items():
            table_model = config["table_model"]

            # Count records efficiently using func.count()
            result = await session.execute(
                select(func.count()).select_from(table_model)
            )
            count = result.scalar()

            validation_results[mapping_key] = {
                "table_name": table_model.__tablename__,
                "record_count": count,
            }

        return validation_results


# CLI function for running the import
async def run_google_sheets_import(
    spreadsheet_id: str = None,
    credentials_json: str = None,
):
    """Run the Google Sheets import process."""
    logger.info("Starting Google Sheets to PostgreSQL import...")

    # Get configuration from settings if not provided
    if spreadsheet_id is None:
        spreadsheet_id = settings.SPREADSHEET_ID

    if credentials_json is None:
        credentials_json = settings.GOOGLE_SHEETS_CREDENTIALS_JSON

    # Initialize importer
    importer = GoogleSheetsDataImporter(spreadsheet_id, credentials_json)

    # Get database session
    async with AsyncSessionLocal() as session:
        # Run import
        results = await importer.import_all_sheets(session)

        # Print results
        logger.info(f"Import Results for Spreadsheet: {spreadsheet_id}")

        import_summary = {}
        for mapping_key, result in results.items():
            if "error" in result:
                logger.error(f"{mapping_key}: {result['error']}")
                import_summary[mapping_key] = {
                    "status": "error",
                    "error": result["error"],
                }
            else:
                logger.info(
                    f"{mapping_key}: {result['imported_rows']}/{result['total_rows']} rows imported"
                )
                import_summary[mapping_key] = {
                    "status": "ok",
                    "imported": result["imported_rows"],
                    "total": result["total_rows"],
                    "skipped": result["skipped_rows"],
                }
                if result["skipped_rows"] > 0:
                    logger.warning(f"  {result['skipped_rows']} rows skipped")
                if result.get("errors"):
                    logger.warning(f"  First errors: {result['errors'][:3]}")

        # Validate
        validation = await importer.validate_import(session)
        logger.info("Validation Results:")
        for mapping_key, stats in validation.items():
            logger.info(f"{stats['table_name']}: {stats['record_count']} records")

        # Sentry context + summary message
        sentry_sdk.set_context("import_results", import_summary)

        failed = [k for k, v in import_summary.items() if v["status"] == "error"]
        if failed:
            sentry_sdk.capture_message(
                f"Daily import PARTIAL FAILURE — failed: {failed}",
                level="error",
            )


# Init Sentry at module level so @monitor works
init_sentry("daily-import")


@monitor(monitor_slug="daily-import")
def main():
    """Entry point for Poetry script."""
    import asyncio

    asyncio.run(run_google_sheets_import())


if __name__ == "__main__":
    main()
