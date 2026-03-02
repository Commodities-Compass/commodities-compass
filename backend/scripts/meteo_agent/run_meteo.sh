#!/bin/bash
set -e

echo "=== Meteo Agent Cron Job ==="
echo "Starting at: $(date)"

poetry run meteo-agent --sheet=production

echo "Completed at: $(date)"
echo "==================================="
