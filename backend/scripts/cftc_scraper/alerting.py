"""Alerting system for CFTC scraper."""

import logging
import os
from datetime import datetime
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """Alert severity levels."""

    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


def send_slack_alert(level: AlertLevel, subject: str, message: str) -> bool:
    """
    Send alert to Slack via webhook.

    Args:
        level: Alert severity level
        subject: Alert subject/title
        message: Alert message body

    Returns:
        True if sent successfully, False otherwise
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")

    if not webhook_url:
        logger.debug("SLACK_WEBHOOK_URL not configured - skipping Slack alert")
        return False

    # Color mapping
    colors = {
        AlertLevel.INFO: "#36a64f",  # Green
        AlertLevel.SUCCESS: "#2eb886",  # Bright green
        AlertLevel.WARNING: "#ff9900",  # Orange
        AlertLevel.CRITICAL: "#ff0000",  # Red
    }

    # Icon mapping
    icons = {
        AlertLevel.INFO: ":information_source:",
        AlertLevel.SUCCESS: ":white_check_mark:",
        AlertLevel.WARNING: ":warning:",
        AlertLevel.CRITICAL: ":rotating_light:",
    }

    payload = {
        "attachments": [
            {
                "color": colors.get(level, "#cccccc"),
                "title": f"{icons.get(level, '')} {subject}",
                "text": message,
                "footer": "CFTC Scraper",
                "ts": int(datetime.now().timestamp()),
            }
        ]
    }

    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(webhook_url, json=payload)
            response.raise_for_status()

        logger.info(f"✓ Slack alert sent: {subject}")
        return True

    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


def send_email_alert(level: AlertLevel, subject: str, message: str) -> bool:
    """
    Send alert via email (using SendGrid or similar).

    Args:
        level: Alert severity level
        subject: Alert subject/title
        message: Alert message body

    Returns:
        True if sent successfully, False otherwise
    """
    # Email configuration from environment
    from_email = os.getenv("ALERT_EMAIL_FROM")
    to_emails = os.getenv("ALERT_EMAIL_TO")  # Comma-separated
    sendgrid_api_key = os.getenv("SENDGRID_API_KEY")

    if not all([from_email, to_emails, sendgrid_api_key]):
        logger.debug("Email alerting not configured - skipping email alert")
        return False

    # TODO: Implement SendGrid integration if needed
    logger.debug("Email alerting not yet implemented")
    return False


def send_alert(level: AlertLevel, subject: str, message: str) -> None:
    """
    Send alert via all configured channels.

    Args:
        level: Alert severity level
        subject: Alert subject/title
        message: Alert message body
    """
    logger.info(f"[{level.value}] {subject}")
    logger.info(f"Message: {message}")

    # Try Slack
    slack_sent = send_slack_alert(level, subject, message)

    # Try Email
    email_sent = send_email_alert(level, subject, message)

    if not slack_sent and not email_sent:
        logger.warning("No alerts sent (no channels configured)")
