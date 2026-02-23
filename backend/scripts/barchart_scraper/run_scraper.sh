#!/bin/bash
# Railway cron job entry point for Barchart scraper

set -e  # Exit on error

echo "=== Barchart Scraper Cron Job ==="
echo "Starting at: $(date)"
echo "Python version: $(python --version)"
echo "Poetry version: $(poetry --version)"

# Run scraper in PRODUCTION mode
echo "Running scraper..."
poetry run python -m scripts.barchart_scraper.main --sheet=production

echo "Completed at: $(date)"
echo "================================="
