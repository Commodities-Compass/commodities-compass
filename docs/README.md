# `docs/` — Documentation index

This is the canonical documentation set for Commodities Compass. Only docs that
are useful for an outside developer or operator land here. Personal notes,
research drafts, and one-shot artifacts live elsewhere (see end of this file).

## Tracked subdirectories

| Folder | What's inside |
|---|---|
| [`architecture/`](architecture/) | High-level pipeline + system design. Read these first if you're new: `CODE_MAP.md`, `PIPELINE_LEGACY.md`, `PIPELINE_ENSEMBLE.md`, `JOBS_AND_SCRAPERS.md`. Plus the ensemble bridge spec, the soft-gate decision explanation, and **`entitlement-and-tenancy.md`** (per-client show/hide of dashboard sections/features). |
| [`runbooks/`](runbooks/) | Operational playbooks for prod incidents and routine procedures (brief dual-track, contract roll, ensemble failure recovery, DB sync from GCP, etc.). |
| [`brand/`](brand/) | Compass CC brand pack: logo library (PNG/JPG/favicon/social/transparent), brand bible HTML, gauge & magazine reference designs. Referenced by `CLAUDE.md § Brand identity`. |
| [`gcp-cost-analysis/`](gcp-cost-analysis/) | Monthly GCP cost breakdowns + analysis. |
| [`archive/`](archive/) | Sprint-by-sprint snapshots of completed R&D handoffs, onboarding artifacts, backtests, and one-shot deliverables. See [archive/README.md](archive/README.md). |

## Local-only (gitignored)

These directories are kept on disk but **not in the repo** — they hold work that
is useful for the maintainer's personal workflow but doesn't belong on github:

- `docs/algorithms/` — algorithm specs, vendor model PDFs, legacy v1 spec
- `docs/user-stories/` — P1/P2/P3 user stories tracker
- `docs/feature-proposals/` — exploratory feature briefs
- `docs/presentations/` — slide decks (HTML)

Untracked HTML drafts/investigations anywhere under `docs/` (except `docs/brand/`)
are also gitignored — see root `.gitignore`.
