# Runbook — WatchAI origin ingestion (`watchai-sync`)

> Loads Côte d'Ivoire physical-origin data (customs exports, exporter purchases, GEPEX grindings) from **a folder on disk** into Compass Postgres.
> Design: `docs/feature-proposals/watchai/watchai-integration.md` · semantics: `business-rules.md` (both gitignored — working tree only).
> **Phase 1 scope: local database only.** `--target prod` is refused by the CLI; a prod load is Phase 2 and needs the section at the bottom filled in first.

---

## What this job is — and what it is not

Manual, operator-run, no cron (decision #6). Same family as `set-farmgate-price` and `seed-trading-calendar`. It is **not** part of the nightly pipeline: nothing in `deploy.yml`, `Dockerfile.jobs` or Cloud Scheduler references it.

**Compass has no relationship with WatchAI at runtime.** No API call, no OVH VPS in any request path, no credential, zero lines of their code. What crosses over is (a) the business semantics, re-implemented in our idiom, and (b) four files, copied once a month. After a load, Postgres is the source of truth and WatchAI is irrelevant until the next month.

| | |
|---|---|
| Source | **A folder containing `Master_Data/` with the four masters.** Git is optional. |
| Batch identity | **sha256 of each source file** (decision #5) |
| Cadence | Monthly, manual, J+3 to J+11 after month end |
| Writes | `pl_origin_ingest_batch`, `ref_origin_entity`, `pl_origin_export_declaration`, `pl_origin_purchase_monthly`, `pl_origin_grinding_monthly`, `pl_origin_flow_monthly` |
| Reads | Nothing else in the schema. Fully additive to the rest of the pipeline. |

### Why the identity is a content hash, not a commit

Pushing the data is an **optional step** in Julien's monthly procedure — it ends at `scp` to his VPS, not at `git push`. A commit SHA can therefore describe a different dataset than the one on disk. `main` was frozen at 2026-06-05 (May data) for two months while July's data lived only on a feature branch. A content hash cannot lie: same bytes, same hash.

---

## Normal run

Any folder holding `Master_Data/` with the four files works — however Julien delivered them.

```bash
cd backend
poetry run watchai-sync --source ~/watchai-2026-07 --dry-run   # inspect
poetry run watchai-sync --source ~/watchai-2026-07             # load
```

If the folder happens to be a git checkout, branch / SHA / commit date are recorded as **bonus metadata** and a dirty working tree is refused (the recorded SHA must describe the bytes read). Neither is required.

**`--source` is resolved against your current directory.** `poetry run` executes from `backend/`, so a checkout sitting beside the repo is `../../watch-ai`, not `../watch-ai`. Most common operator mistake; the error prints the resolved absolute path.

### Flags

| Flag | Effect |
|---|---|
| `--dry-run` | Full run — cube, reconciliation, diff — inside a transaction it rolls back. Nothing persists. |
| `--skip-compute` | Land the observation tables, skip the cube. Reconciliation is skipped too (it reads the cube). |
| `--target {local,prod}` | Default `local`. `prod` is refused in Phase 1. |
| `--database-url` | Overrides `DATABASE_SYNC_URL`, which overrides the local docker-compose URL. |
| `--ingested-by` | Operator handle on the batch row. Defaults to the OS user. |
| `--keep-batches N` | Retention, default 2. The previous batch is what the next run diffs against — do not set 1. |

---

## Reading the output

### Source block — printed **before** anything is written

```
── Source ──
  folder       : /Users/…/watchai-2026-07
  kind         : files
  identity     : c42b44e9052b0eab (sha256 of the file set)
    5f79415b2f77  Db_Master_Achats.parquet
    83565582e4b8  Db_Master_Broyage.parquet
    4da25a54a501  Db_Master_Tax.parquet
    d5718d63d660  Entity_Mappings.xlsx
  freshness    : newest period per source
    declarations : 2026-07-31
    grindings    : 2026-04-01
    purchases    : 2026-07-01
  data_as_of   : 2026-07-31  ← what the UI will stamp
```

**Check the freshness block every time** (integration doc §4 step 1). A stale source is the normal case, not the exception. Grinding structurally trails the other two by 2-3 months — STATSER stops at 2026-04 while exports and achats run to 2026-07 — and that is expected, not a fault.

### Reconciliation

```
  [PASS] 2026-07 exports (t): 147,866 (Δ -0.418)
  [PASS] 2025-2026 YTD(Oct→M7) mix FEVES: 1,236,439 (Δ +0.423)
  [SKIP] 2026-07 achats: purchases does not cover 2026-07; activates on its own once it lands
```

- **PASS** — reproduced within 1 tonne / 1 M FCFA (the report rounds to whole units; observed worst case 0,47 t).
- **SKIP** — that source does not yet cover the period. Coverage is evaluated **per source** (business-rules §6), so a lagging achats file skips the achats check alone and never suppresses the exports one. Re-enables itself when the data lands; no code change.
- **FAIL** — aborts the run. The fixtures are verified exact upstream, so **a divergence is a bug in our transform**: taxonomy (business-rules §2) or unit (§1). Never adjust the expected value.

On the pinned dataset the full set is **22/22 PASS, 0 SKIP**.

### Restatement

```
  source files : Db_Master_Achats.parquet, Db_Master_Tax.parquet
  restatement  : HISTORY MOVED vs the previous batch
    exports_tonnes: 3 month(s) changed
      2025-11-01   200,195.4 →   201,004.2 t  (+808.8)
```

**Expected behaviour, not an error.** The upstream masters are rebuilt from scratch every month (`business-rules.md` §12): `consolidate_achats.py` re-reads every source workbook, `consolidate_broyage.py` regenerates 2012→present. Corrected source files legitimately republish prior months.

The two lines answer different questions: `source files` says *which files changed bytes* (content-addressed, needs no commit); `restatement` says *whether that changed any published figure*. A file can change without moving a total, and that is worth knowing.

If a client has already been shown a figure for a restated month, that is a deliberate conversation. The diff is printed and stored on `pl_origin_ingest_batch.restatement_summary`.

---

## Failure modes

All fail-loud, non-zero exit, **no partial write** — the whole load is one transaction. Recovery is always: diagnose → fix the root cause → re-run. Never a retry, never a fallback (`.claude/rules/pipeline-error-handling.md`).

| Error | Meaning | Fix |
|---|---|---|
| `SourceNotFoundError` | Bad `--source`, missing `Master_Data/`, or a missing master file. | Check the resolved path in the message. |
| `DirtyWorkingTreeError` | *Git mode only.* Modified tracked files, or untracked files under `Master_Data/`. | Commit, clean, **or** copy the four masters into a plain folder and point `--source` there — a folder has no dirty-tree notion. Untracked files *outside* `Master_Data/` are recorded, not blocking. |
| `SourceSchemaError` | A master lost a required column, or a mapping sheet changed shape. | The upstream extract changed. Do **not** reindex around it — re-read `business-rules.md` §1–§2 and confirm what the new column means. |
| `UnknownProductError` | A `PRODUIT SIMPLE` value or POSTAR prefix that maps to nothing. | Confirm the product with Julien, then add it to `config.PRODUCT_SIMPLE_MAP` / `POSTAR_PREFIX_MAP`. WatchAI silently defaults these to `FEVES`; we refuse, because beans are ~85 % of volume and a wrong default is invisible. |
| `UnmappedEntityError` | A row has an empty `EXPORTATEUR_SIMPLE`. | Upstream data fix. A blank name would merge unrelated books into one entity. |
| `InvalidTonnageError` | Negative weight, or two grinding rows for one month. | Upstream data fix. |
| `RowCountRegressionError` | The new batch is >2 % smaller than the current one. | Usually a truncated source file — **or loading an older dataset over a newer one**, which is the same shape and equally worth stopping. |
| `CubeUniquenessError` | Duplicate natural key, or mass not conserved between the line table and the cube. | A real bug in `compute_cube`. Do not work around it — every cross-series ratio on that batch would be wrong (`.claude/rules/timeseries-uniqueness.md`). |
| `ReconciliationError` | A published golden value diverged. | Bug in our transform. See above. |

---

## Things that look wrong but are not

Permanent properties of the upstream extract, counted into `pl_origin_ingest_batch.quality_report` rather than raised — raising on them would mean the job never runs. Figures below are on `refonte-da-v2` @ `11336ef` (172 712 declarations).

- **131 573 rows carry no real money data** — everything before the 2023-2024 season. On `main` these were `NULL`; on `refonte-da-v2` they are **0**. Sums are unaffected either way, but any *average* must filter `valcaf > 1`, not `> 0` (277 rows sit at exactly 1 FCFA). This is a live trap for the Phase 3 stabilisation analytic, which business-rules §9 still specifies with `> 0`.
- **46 exporters and 7 destinations are absent from `Entity_Mappings.xlsx`.** The file maps *raw → SIMPLE*, but the parquet already carries the `*_SIMPLE` columns, so it is not a complete universe and cannot act as a gate. They are created and flagged (`ref_origin_entity.in_entity_mappings = false`). Worth sending back to Julien periodically.
- **`Entity_Mappings.xlsx` holds 56 646 rows across 4 sheets**, not the "588 mappings" both spec docs state. Only `Exportateurs` (722) and `Destinations` (152) are read; `Destinataires` (55 636) and `Declarant` (136) map columns the reduced projection drops.
- **`TAX %` disagrees with `DROITS_TAXES/VALCAF` on ~30 % of comparable rows** (12 119), and `CAF/kg` on ~0,5 %. business-rules §1 asks for an assert; it would abort every run, so these are counters. WatchAI ignores both columns and recomputes — and we do not ingest them at all.
- **`DECLARATION` is populated on 101 113 of 172 712 rows (58,5 %)** and on 0 % on `main`. Partially populated is *less* usable as a natural key than uniformly empty; do not key on it (business-rules §13).
- **`COQUES` and `LIQUEUR` never appear.** All 18 621 POSTAR-1802 rows are labelled `HORS GRADE` by the source, and `PRODUIT SIMPLE` is populated on every row, so the POSTAR fallback never fires. The codes exist for that dormant path.
- **`Db_Master_Broyage.SOURCE_FILE` says "demo"** (`Report GEPEX April 2026 demo.xlsx`). That is what upstream ships.
- **The report's "TOTAL TRANSFORMÉ" will not match ours.** Published: 473 907 t (27,7 %), which counts HORS GRADE as transformed. Ours: **340 068 t (19,9 %)** — hors-grade beans are beans (business-rules §2: weighted CAF at 96,8 % of the fève price, POSTAR 1802 being a fiscal choice, and v2's own tested code). The delta is exactly the HORS GRADE line and a test asserts it. **This is politically sensitive in Côte d'Ivoire — brief the commercial side before a client asks.**

---

## Verifying a load

```sql
-- the batch that is being served
SELECT source, source_branch, source_ref, ingested_by, ingested_at,
       data_as_of, row_counts
  FROM pl_origin_ingest_batch WHERE is_current;

-- content identity of the served dataset
SELECT source_hashes FROM pl_origin_ingest_batch WHERE is_current;

-- exactly one current batch, always
SELECT COUNT(*) FROM pl_origin_ingest_batch WHERE is_current;   -- must be 1

-- what moved last time, and the source imperfections recorded
SELECT restatement_summary, quality_report
  FROM pl_origin_ingest_batch WHERE is_current;

-- mass conservation, line table vs cube (must be equal)
SELECT (SELECT SUM(net_weight_kg)/1000 FROM pl_origin_export_declaration
         WHERE ingest_batch_id = b.id) AS declared_tonnes,
       (SELECT SUM(export_tonnes) FROM pl_origin_flow_monthly
         WHERE ingest_batch_id = b.id) AS cube_tonnes
  FROM pl_origin_ingest_batch b WHERE b.is_current;
```

---

## Tests

```bash
cd backend
poetry run pytest tests/test_watchai_transform.py tests/test_watchai_sync_db.py \
                  tests/test_watchai_acquire_cli.py tests/test_watchai_reconciliation_golden.py
```

`test_watchai_reconciliation_golden.py` is the Phase 1 gate: it runs a real dataset end to end and asserts every published figure. It **skips itself** under either of two conditions, and the distinction matters:

1. **No source folder** — CI, where that data is not available.
2. **A different dataset** — the fixtures are verified against one specific byte-for-byte dataset (`config.SPEC_SOURCE_FILE_SET_SHA256`). Point it at `main` and the 2024-2025 product mix differs by 2 t: that is a **restatement between the two branches**, not a bug in our transform, and reporting it as a failure would be wrong.

The skip reason prints both hashes. To run the gate:

```bash
WATCHAI_SOURCE=/path/to/pinned/dataset poetry run pytest tests/test_watchai_reconciliation_golden.py
```

`test_at_least_one_golden_check_actually_ran` stops the suite degrading into "everything skipped, all green".

---

## Spec provenance and drift

The semantics were read from and reconciled against `plakoplister/watch-ai` @ **`11336ef`**, branch **`refonte-da-v2`** (2026-08-14), verified 2026-08-17. WatchAI has been rebuilt as FastAPI + DuckDB + Next.js; that v2 `api/app/` is the port reference and `Webapp/webapp_tax.py` is historical.

Recorded in `scripts/watchai_sync/config.py` as `SPEC_SOURCE_BRANCH`, `SPEC_SOURCE_COMMIT`, `SPEC_VERIFIED_ON`, `SPEC_SOURCE_FILE_SET_SHA256` — **for the reader and for the test gate, never enforced at load time**. A new month legitimately moves everything.

`refonte-da-v2` is an active branch, which makes spec drift the **top risk** on this integration. The one constant to watch is `RENDEMENT_BROYAGE = 0.80` (`api/app/data.py:292`, mirrored in our `config.py`): it converts transformed exports back to bean equivalent in the material balance, and if it moved upstream without us noticing, every balance we publish would be restated silently. On re-sync: diff `data.py` / `saison.py`, re-run the reconciliation, then bump the four constants together.

The CLI prints a warning when the source is a git checkout on a branch other than the pinned one.

---

## Phase 2 — prod load (not yet authorised)

`--target prod` currently raises. Before it is enabled, this section must specify:

1. The bastion tunnel setup (`.local/db-prod.sh up`) and the exact connection string.
2. Confirmation that migration `n9c0d1e2f3g4` has landed on `main` and been applied by a Cloud Run cold start — **never** `alembic upgrade head` from a feature branch (`.claude/rules/migrations-prod-via-main-only.md`).
3. A mandatory `--dry-run` against prod first, with the restatement diff reviewed.
4. `--ingested-by` set to a real human, since `pl_origin_ingest_batch` is the only record the operation happened.

A manual CLI writing 172k rows into prod Cloud SQL sits in the third branch of the migrations rule — *"un ordre direct du user, en pleine conscience qu'il sort du process"*. Never a `psql` one-off.

---

## Out of Phase 1 scope

The **material balance** (business-rules §4–§5) lives in the Phase 3 service, not here. Two things to carry forward when it ships:

- It is bean-equivalent arithmetic: `broyage_deduit_t = transfo_exporte_t / RENDEMENT_BROYAGE`, then `solde_t = achats_t − feves_exportees_t − broyage_deduit_t`. Adding transformed exports raw is the v1 double-count Julien fixed on 2026-07-17 (124 % taux de sortie, negative solde).
- **Grinding is derived, not read.** STATSER becomes a *confrontation* — the gap between derived and declared is published as a consistency signal. That is what lets the balance recover the 2-3 months STATSER lags by, and it confines the GEPEX-perimeter bias to the confrontation alone.
- The two invariants — `0 ≤ taux_sortie_pct ≤ 100` and `solde_t ≥ 0` — belong in the test suite as assertions, not in a comment. Either failing is the signature of a double-count.
