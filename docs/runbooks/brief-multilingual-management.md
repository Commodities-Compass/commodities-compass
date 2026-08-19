# Runbook — Multilingual brief & podcast management

> How the daily brief → NotebookLM → audio flow works. Updated 2026-08-19: the
> flip left **one track**, so the multi-track matrix this runbook was written for
> collapsed to two rows — FR and EN of the same edition.

## Daily artefacts

| Edition | Brief `.txt` (Drive) | NotebookLM audio (Drive) | Producer |
|---|---|---|---|
| **FR** | `YYYYMMDD-CompassBrief-Regime.txt` | `YYYYMMDD-CompassAudio-Regime.{wav,m4a,mp4}` | `cc-regime-brief --language both` |
| **EN** | `YYYYMMDD-CompassBrief-Regime-EN.txt` | `YYYYMMDD-CompassAudio-Regime-EN.{wav,m4a,mp4}` | same job, same run |

Unlike the retired tracks, the two editions are **written natively per language**
by the same job — the EN brief is not a translation of the FR one. The LLM cost is
therefore real (two narration calls), where the old templated briefs were free.
**NotebookLM is still manual** and is the operational cost: 2 manual voicings/day.

⚠️ `cc-publish-session` waits on the audio before flipping the dashboard, with a
09:00 UTC data-only fallback so a missing voicing cannot freeze it indefinitely.

## Manual NotebookLM step (per track, per day)

1. Wait for the brief `.txt` to land in the Drive folder (after the Phase-B
   jobs, ~19:55 UTC).
2. Open the correct NotebookLM notebook:
   - FR → prompt [notebooklm-podcast-prompt-regime.md](../operations/notebooklm-podcast-prompt-regime.md), output language **French**.
   - EN → prompt [notebooklm-podcast-prompt-regime-en.md](../operations/notebooklm-podcast-prompt-regime-en.md), output language **English**.
3. Upload the day's brief, paste the prompt body into "Customise", Generate.
4. Download the audio, **rename exactly** to the filename in the table above
   (the dashboard matches on that name), upload back to the same Drive folder.

## Serving (dashboard)

The dashboard resolves audio by `(version, language)` →
`YYYYMMDD-CompassAudio-Regime{-EN}.{wav|m4a|mp4}`. The candidate list is
**language-consistent by construction** (`audio_service._candidate_suffixes`): the
EN edition never falls back to an FR file, so a missing EN audio degrades to
no-audio in the player rather than mislabelling an FR track under the EN edition
(i18n decisions D3/D4).

`BRIEF_DEFAULT_VERSION=regime` since 2026-08-19; an explicit `?version=` overrides
it per request. The frontend language
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

Manual NotebookLM is the bottleneck, now at 2 voicings/day (down from 3 before
the flip). If it grows, the only real lever left is an automated TTS path — there
is no reliable NotebookLM API today, and there is no longer a redundant track to
drop.
