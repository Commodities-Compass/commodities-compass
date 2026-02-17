#!/bin/bash
# Railway cron job entry point for ICE Certified Stocks scraper
# No browser needed — direct XLS download from ice.com

echo "=== ICE Stocks Scraper Cron Job ==="
echo "Starting at: $(date)"

poetry run python -m scripts.ice_stocks_scraper.main --sheet=staging
EXIT_CODE=$?

echo "Exit code: $EXIT_CODE"
echo "Completed at: $(date)"
echo "================================="

exit $EXIT_CODE
