#!/bin/bash
# Railway cron job entry point for Barchart scraper

set -e  # Exit on error

echo "=== Barchart Scraper Cron Job ==="
echo "Starting at: $(date)"
echo "Python version: $(python --version)"
echo "Poetry version: $(poetry --version)"

# Install Playwright browsers if not already installed
echo "Installing Playwright browsers..."
poetry run python -m playwright install chromium --with-deps

# Run scraper in STAGING mode (for 3-day validation before production)
echo "Running scraper..."
poetry run python -m scripts.barchart_scraper.main --sheet=staging

echo "Completed at: $(date)"
echo "================================="
