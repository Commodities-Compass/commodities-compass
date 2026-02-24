#!/bin/bash
set -e

echo "=== Press Review Agent Cron Job ==="
echo "Starting at: $(date)"

poetry run python -m scripts.press_review_agent.main --sheet=production

echo "Completed at: $(date)"
echo "==================================="
