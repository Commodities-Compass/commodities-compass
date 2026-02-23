#!/bin/bash
# Railway cron job entry point for CFTC COT report scraper
# No browser needed — direct HTML download from cftc.gov

echo "=== CFTC Scraper Cron Job ==="
echo "Starting at: $(date)"

poetry run python -m scripts.cftc_scraper.main --sheet=production
EXIT_CODE=$?

echo "Exit code: $EXIT_CODE"
echo "Completed at: $(date)"
echo "================================="

exit $EXIT_CODE
