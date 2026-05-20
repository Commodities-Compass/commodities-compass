"""Helpers shared across scrapers (sentry init, logging, CLI, HTTP).

Keep this module dependency-light — it must not import scraper-specific
configuration. Each helper is one focused responsibility, so callers
import what they need without pulling in the whole package.
"""
