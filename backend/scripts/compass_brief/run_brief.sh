#!/bin/bash
set -e

echo "=== Compass Brief Cron Job ==="
echo "Starting at: $(date)"

poetry run compass-brief

echo "Completed at: $(date)"
echo "==============================="
