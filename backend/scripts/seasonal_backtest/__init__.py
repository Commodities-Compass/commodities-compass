"""Seasonal score backtest tool.

Replays the seasonal scoring pipeline against a past campaign (e.g., 2024-2025)
to validate Open-Meteo data quality and formula fitness. Reuses the production
computation functions in scripts.meteo_agent.seasonal_memory.

CLI: `poetry run backtest-seasonal --target-date 2025-09-30`
"""
