# Runbook — Multilingual brief & podcast management

> How the daily brief → NotebookLM → audio flow works once the **English
> (Ghana)** edition is live. Scope decision (US-4 §5): **ensemble track only in
> English** — we do NOT produce a legacy-EN audio. FR keeps both tracks.

## Daily artefacts

| Track | Brief `.txt` (Drive) | NotebookLM audio (Drive) | Producer |
|---|---|---|---|
| Legacy FR | `YYYYMMDD-CompassBrief.txt` | `YYYYMMDD-CompassAudio.m4a` | `cc-compass-brief` |
| Ensemble FR | `YYYYMMDD-CompassBrief-Ensemble.txt` | `YYYYMMDD-CompassAudio-Ensemble.m4a` | `cc-compass-brief-ensemble` |
| **Ensemble EN** | `YYYYMMDD-CompassBrief-Ensemble-EN.txt` | `YYYYMMDD-CompassAudio-Ensemble-EN.m4a` | `cc-compass-brief-ensemble --language both` |

Briefs are generated automatically (no LLM cost — templated from the DB rows).
**NotebookLM is manual** and is the real cost: **+1 manual step/day** for EN
(upload → set language → generate → download → rename → re-upload).

## Manual NotebookLM step (per track, per day)

1. Wait for the brief `.txt` to land in the Drive folder (after the Phase-B
   jobs, ~19:35 UTC).
2. Open the correct NotebookLM notebook:
   - FR → prompt [notebooklm-podcast-prompt.md](../operations/notebooklm-podcast-prompt.md), output language **French**.
   - EN → prompt [notebooklm-podcast-prompt-en.md](../operations/notebooklm-podcast-prompt-en.md), output language **English**.
3. Upload the day's brief, paste the prompt body into "Customise", Generate.
4. Download the audio, **rename exactly** to the filename in the table above
   (the dashboard matches on that name), upload back to the same Drive folder.

## Serving (dashboard)

The dashboard resolves audio by `(version, language)` →
`YYYYMMDD-CompassAudio{-Ensemble}{-EN}.{wav|m4a|mp4}`. The candidate list is
**language-consistent by construction** (`audio_service._candidate_suffixes`):

- **EN** (ensemble-only): tries `-Ensemble-EN`, then a bare `-EN` — both
  English. It **never** falls back to an FR file (`-Ensemble` / no-suffix), so a
  missing EN audio degrades to no-audio in the player rather than mislabelling
  an FR track under the EN edition (i18n decisions D3/D4). Because EN is
  ensemble-only, the `version` param is effectively ignored for EN.
- **FR**: the exact per-version file (`-Ensemble` for ensemble, no suffix for
  legacy) — unchanged, no cross-version fallback (the two tracks stay
  independent).

`BRIEF_DEFAULT_VERSION` still picks the default FR track. The frontend language
selection travels to the backend via the `Accept-Language` header; the
`/dashboard/audio` response then embeds `?language=` on the returned stream URL
so the unauthenticated `<audio>` element streams the matching edition. An
explicit `?language=` query param overrides the header.

## Failure / gaps

- **EN audio not uploaded yet** → dashboard EN shows the podcast block empty
  (expected; the text brief is still there). Upload the audio to fix.
- **Wrong filename** → not matched → empty block. Re-check the exact suffix.
- **Prompt drift** → keep the `.md` prompt and the NotebookLM "Customise" panel
  in sync; the brief template redaction and the prompt redaction must match.

## Scaling note

Manual NotebookLM is the bottleneck. If the EN edition grows, revisit either
(a) an automated TTS path (no reliable NotebookLM API today), or (b) dropping
the legacy FR audio once legacy is fully rationalised — both reduce the daily
manual count.
