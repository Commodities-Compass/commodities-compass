"""Data validation for scraped values."""

import logging
from typing import Dict, List, Optional

from scripts.barchart_scraper.config import VALIDATION_RANGES

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when validation fails."""

    pass


class DataValidator:
    """Validates scraped data before writing to Sheets."""

    @staticmethod
    def validate_field(field: str, value: Optional[float]) -> None:
        """
        Validate a single field.

        Args:
            field: Field name
            value: Field value

        Raises:
            ValidationError: If validation fails
        """
        # Check non-null
        if value is None:
            raise ValidationError(f"Field '{field}' is null")

        # Check range
        if field in VALIDATION_RANGES:
            min_val, max_val = VALIDATION_RANGES[field]
            if not (min_val <= value <= max_val):
                raise ValidationError(
                    f"Field '{field}' value {value} outside valid range [{min_val}, {max_val}]"
                )

    @staticmethod
    def validate_all(data: Dict[str, Optional[float]]) -> List[str]:
        """
        Validate all fields.

        Args:
            data: Dict of scraped data

        Returns:
            List of validation errors (empty if all valid)
        """
        errors = []

        required_fields = [
            "close",
            "high",
            "low",
            "volume",
            "open_interest",
            "implied_volatility",
        ]

        # Validate each required field
        for field in required_fields:
            try:
                DataValidator.validate_field(field, data.get(field))
            except ValidationError as e:
                errors.append(str(e))
                logger.error(f"Validation error: {e}")

        # Logical checks
        if data.get("high") and data.get("low"):
            if data["high"] < data["low"]:
                errors.append(
                    f"HIGH ({data['high']}) cannot be less than LOW ({data['low']})"
                )

        if data.get("close") and data.get("high") and data.get("low"):
            if not (data["low"] <= data["close"] <= data["high"]):
                errors.append(
                    f"CLOSE ({data['close']}) must be between LOW ({data['low']}) and HIGH ({data['high']})"
                )

        if errors:
            logger.warning(f"Validation failed with {len(errors)} error(s)")
        else:
            logger.info("Validation passed")

        return errors
