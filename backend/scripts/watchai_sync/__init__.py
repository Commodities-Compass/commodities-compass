"""Manual ingestion of WatchAI origin data into Compass Postgres.

``poetry run watchai-sync --source ../watch-ai``

Manual by design (decision #6): the upstream publication lag is variable (J+3 to
J+11 after month end), so an operator runs this when a new month lands. No cron,
no Cloud Run Job, no scheduler — same family as ``set-farmgate-price`` and
``seed-trading-calendar``.

Module layout mirrors the scraper convention:

* ``acquire``        — git provenance + read the parquet/xlsx sources
* ``transform``      — pure derivation (season, taxonomy, entities), no I/O
* ``db_writer``      — snapshot write, batch promotion, restatement diff, cube
* ``reconciliation`` — computed totals vs published golden values
* ``main``           — CLI
"""
