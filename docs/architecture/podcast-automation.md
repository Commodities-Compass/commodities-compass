# Podcast automation — replacing the manual NotebookLM step

> Status: **design, not built** — 2026-08-25.
> Decisions locked with Hedi on 2026-08-25 (§3). Nothing in the served pipeline
> changes until §6 P5, and P5 is a manual call made on the benchmark evidence.

## 1. What is manual today

`cc-regime-brief` (19:55 UTC) uploads `YYYYMMDD-CompassBrief-Regime{,-EN}.txt`
to Drive. Then a human:

1. opens the NotebookLM notebook, uploads the `.txt`;
2. pastes [notebooklm-podcast-prompt-regime.md](../operations/notebooklm-podcast-prompt-regime.md)
   (FR) / [-en.md](../operations/notebooklm-podcast-prompt-regime-en.md) into "Customise";
3. generates, downloads, renames to `YYYYMMDD-CompassAudio-Regime{,-EN}.{wav,m4a,mp4}`;
4. uploads to the Drive audio folder.

Everything downstream is already keyed on that filename —
[audio_service.py:233](../../backend/app/services/audio_service.py#L233) resolves it,
[publish_session/main.py:135](../../backend/scripts/publish_session/main.py#L135) polls
Drive every 30 min and flips the dashboard atomically once it appears. **A job that
drops those two files makes the chain hands-free with zero downstream change.**

### The blind spot nobody is measuring

The manual step is the visible cost. The invisible one is that **a black box
writes the client-facing statement of a paid financial signal**, and nothing
verifies what it says. The prompt is 130 lines of pure defence — `VOCABULAIRE
INTERDIT`, `N'invente AUCUN chiffre`, `ne compte JAMAIS des voix`, `la direction
DOIT être cohérente avec la décision`. Each line guards against a failure mode
that cannot be tested. `test_regime_podcast_prompt_contract.py` binds the
*prompt anchors to the brief*; it says nothing about the *episode*.

Second unpriced cost: **no `voice_id`**. The voices are NotebookLM's, not ours,
with no guarantee they are the same next quarter. There is no brand voice asset.

## 2. Options considered

Verified 2026-08-25.

| | Script author | Voices | Cost/yr (est.) | Verdict |
|---|---|---|---|---|
| **A1** Gemini Notebook Enterprise API | black box, `episodeFocus` string | not selectable | ~$1 600 | rejected |
| **A2** Playwright on the NotebookLM UI | black box | not selectable | ~0 | rejected |
| **B1** in-house script + ElevenLabs v3 Text-to-Dialogue | ours | pinned `voice_id`, 70+ langs | ~$1 200 | escalation path |
| **B2** in-house script + Gemini 2.5 TTS multi-speaker | ours | 2 native speakers, 24 langs | **~$40** | **target** |
| **C** ElevenLabs GenFM `POST /v1/studio/podcasts` | black box | pinned host/guest | ~$1 200 | benchmark control only |

**A1 rejected** — the API is real (`POST .../v1alpha/projects/{p}/locations/{l}/notebooks/{id}/audioOverviews`)
but it is Pre-GA preview, needs a Gemini Notebook Enterprise licence (~$9/seat,
15-seat minimum), exposes only `episodeFocus` (a string) + `languageCode`, and
allows **one audio overview per notebook** — daily notebook lifecycle churn.
Paying ~$1.6k/yr to *lose* editorial control over a client deliverable.

**A2 rejected** — ToS violation, an authenticated Google session inside a
headless container, and a silent-failure machine on a load-bearing daily
deliverable. Directly contradicts [pipeline-error-handling.md](../../.claude/rules/pipeline-error-handling.md):
a UI scraper fails in ways that cannot be classified. Acceptable **only** as a
manual generator of benchmark reference episodes.

**B2 cost basis** — Gemini 2.5 Flash TTS, $10 / 1M audio output tokens at
25 tok/s ⇒ ~$0.08 per 5-minute episode ⇒ ~$0.16/day for FR+EN ⇒ ~$40/yr.
`gemini-3.1-flash-tts-preview` pricing not yet published. Order-of-magnitude
estimate, to be confirmed on the first real invoice.

**B1 cost basis** — ElevenLabs v3 at 1 credit/char, ~5 000 chars/episode.
Production: 2 episodes × ~250 sessions ≈ 2.5M chars/yr ⇒ ~$250/yr at the stated
API rate ($0.10 / 1 000 chars) or ~$1 200/yr on a credit plan (Pro, 500k/mo).
Which of the two applies is the first thing to confirm if B1 wins.

## 3. Decisions locked (2026-08-25)

1. **We write the script.** In-repo module, native per language, contract-tested.
2. **Cheapest first.** Gemini TTS is the target; ElevenLabs v3 is the escalation
   if and only if the benchmark says money fixes the gap.
3. **Iterate before migrating.** No flip on faith — shadow mode, blind listening,
   flip when the evidence is in. Some loss of conversational fluidity is
   acceptable; a loss of *product* quality is not.
4. **The TTS engine is an adapter, not a dependency.** Same shape as
   `AlertSender`/`ALERT_CHANNEL` in `intraday_monitor` — swap providers by env
   var without touching the pipeline.

### Settled by the P0 listening tests (2026-08-26)

5. **Brand voice: `Kore` (F) + `Algieba` (M)**, pinned by `speakerId`. Chosen by
   Hedi over Charon (flat), Aoede, Puck, Orus, Umbriel, Iapetus and Schedar.
   This is the least reversible decision in the project — clients will associate
   these two voices with Compass.
6. **`input.prompt` is mandatory, not optional.** Without a style prompt the
   output is two narrators taking turns. With one ("deux journalistes financiers
   en direct… ce n'est PAS une lecture à tour de rôle") it reads as a
   conversation. Verified A/B/C.
7. **Conversational quality is a script property, not a TTS property.** Feeding
   the served *monologue* prose and flipping speaker every sentence produces a
   monologue cut in half. `script_writer` must emit a real dialogue — questions,
   reactions, one speaker finishing the other's sentence. This is the single
   biggest determinant of whether the result passes for NotebookLM.
8. **`normalize_for_speech()` before any synthesis.** See §4.1.1.
9. **Tempo: 15 chars/s target** (`speakingRate ≈ 0.954` on the dialogue's own
   calibration). Config constant, tunable without a deploy.
10. **Turn length must vary.** Confirmed by ear: same words and same tempo, a
    15-turn dialogue (avg 77 chars) reads smoothly where a 26-turn mechanical
    split (avg 44 chars) sounds jerky — a speaker change every sentence forces a
    pause and a fresh attack. Rhythm is a script property.
11. **A pronunciation lexicon, via `customPronunciations` (IPA).** `COMPASTEURS`
    opens and closes every episode and is a coined Compass word in neither French
    nor English; it was heard as "C-O-M-P-asteurs". Validated 3/3 with
    `customPronunciations` + IPA `kɔ̃pastœʁ` — chosen over normal-casing or a
    prompt hint because it is **deterministic**: the model cannot drop it. The
    lexicon extends to `CAZ26`, `ICE`, `COT`, `momentum`, `HEDGE`, `MONITOR`,
    `YTD`. Config, not code.

### 3.1 The synthesis contract — settled, P1 builds against this

| Parameter | Value |
|---|---|
| model | `gemini-3.1-flash-tts-preview` |
| surface | Cloud TTS `texttospeech.googleapis.com` (**needs `aiplatform` enabled too**) |
| voices | `Kore` (Ana, F) · `Algieba` (Marc, M) |
| languages | `fr-FR` (GA) · `en-US` (GA) |
| `input.prompt` | mandatory — conversational steering |
| `input.customPronunciations` | mandatory — IPA lexicon |
| tempo | 15 chars/s, calibrated per episode, `speakingRate` clamped [0.7, 1.4] |
| chunking | ≤3 500 B payload ⇒ ~2 chunks per 5-min episode |
| chunk levelling | measure, then re-synthesise off-target chunks (7.3 % → 2.2 %) |
| encoding | LINEAR16 24 kHz mono, transcoded to `.m4a` for Drive |

**ElevenLabs is not needed.** Gemini passed every P0 gate — pronunciation,
conversation, numbers, seam, coined vocabulary. The escalation arm stays
documented in §2 but is not opened. The cheapest option won on merit, at ~$40/yr
against ~$250–1 200.

## 4. Architecture

```
pl_indicator_daily (served row: conclusion / eco / confidence_rationale)
  + BriefData (deterministic figures)
        │
        └→ cc-podcast-audio                    (new job, 20:05 UTC)
             ├→ script_writer.py   → [{speaker, text}, …]   (LLM, 1 call/language)
             ├→ tts/<provider>.py  → audio bytes
             └→ DriveUploader.upload_bytes()
                  ├→ SHADOW folder  YYYYMMDD-CompassAudio-Regime-{provider}{,-EN}.m4a
                  └→ (after P5) AUDIO folder  YYYYMMDD-CompassAudio-Regime{,-EN}.m4a
                                                   └→ cc-publish-session picks it up 20:30
```

### 4.1 `script_writer.py` — mirrors `narrator.py`

**It does not read the rendered `.txt`.** `narrator.py` already wrote the prose
onto the served row; the script writer consumes **that prose plus the
deterministic figures**, so the podcast and the dashboard say literally the same
thing. Parsing the human-facing `.txt` back into structure would be fragile and
would let the two drift — which is exactly what happens today.

- One LLM call per language, **native composition, never translation** — the
  rule established by US-1 and enforced in `narrator.py`.
- Reuses `scripts/_shared/llm_client.py`.
- Output is **structured turns**, not prose: `[{"speaker": "host"|"guest", "text": …}]`.
  Structured output is what makes the script assertable and what feeds a
  multi-speaker TTS call directly.
- The 9-section structure and the forbidden-vocabulary list move out of the
  NotebookLM "Customise" panel and into the prompt + the test suite.

### 4.2 The contract tests — the actual product win

What becomes testable for the first time:

| Assertion | Today |
|---|---|
| the announced decision == the served row's decision | unverifiable |
| the announced confidence == the served row's score | unverifiable |
| every figure spoken exists in `BriefData` | a prompt line and a prayer |
| no forbidden vocabulary is uttered | a prompt line and a prayer |
| direction (haussier/baissier) is coherent with the decision | a prompt line and a prayer |
| opens `Bonjour les COMPASTEURS`, closes `A demain les COMPASTEURS` | unverifiable |
| duration budget (< 5 min ⇒ character budget per section) | unverifiable |

These are assertions on the **script**, so they run in CI with no TTS spend.

### 4.3 `tts/` adapter

```
tts/base.py         SpeechSynthesizer protocol: synthesize(turns, language) -> bytes
tts/gemini.py       Gemini-TTS, multi-speaker, chunked (see 4.3.1)
tts/elevenlabs.py   ElevenLabs v3 Text-to-Dialogue (escalation)
tts/noop.py         writes the script to disk, no audio — CI + --dry-run
```

Selected by `TTS_PROVIDER`, default `noop`. Voice ids are config, not code.

Gemini models available (verified 2026-08-25): `gemini-3.1-flash-tts-preview`
(launched 2026-04-15 — 70+ languages, 30 voices, 200+ audio tags, native
multi-speaker), `gemini-2.5-flash-tts`, `gemini-2.5-pro-tts`,
`gemini-2.5-flash-lite-preview-tts`. **`fr-FR` is GA**, `en` GA. Multi-speaker
is configured via `MultiSpeakerVoiceConfig` / `MultiSpeakerMarkup` with
turn-based dialogue — which maps 1:1 onto `script_writer`'s output.

Reachable through **either** the Cloud Text-to-Speech API
(`texttospeech.googleapis.com`) or Vertex AI (`aiplatform.googleapis.com`), both
on the existing `cacaooo` project — the service account and Workload Identity
Federation already exist, so there is no new API key to provision or rotate.
ElevenLabs needs a Secret Manager entry (`ELEVENLABS_API_KEY`).

#### 4.1.1 The prose is written for the eye — normalise before speaking

The served `conclusion` contains markdown and a hybrid number format:

```
> Signal MONITOR avec une conviction modérée…
> À SURVEILLER AUJOURD'HUI :
        • Baissier si le cours casse le SUPPORT 1 (4 160.67).
```

Sent raw to a French voice, the `>` and `•` are **spoken aloud**, and
`4 160.67` — French thousands space with an English decimal dot — cannot be
parsed as a number, so it is read digit by digit. `> Signal` also garbles the
following word. All three were heard in the first P0 pack and all three are
layout, never meaning. `normalize_for_speech()` strips the markup and rewrites
the decimal separator. It belongs to `script_writer`, whichever engine wins.

#### 4.3.1 The 4 000-byte wall — Gemini only

Gemini-TTS caps the `text` field at **4 000 bytes** (8 000 combined with the
prompt), output audio at ~655 s. A 5-minute French script is ~5 000 characters,
and French accents cost 2 bytes in UTF-8 ⇒ **~5 300+ bytes, over the limit**.

The cap is on the **whole payload, not per turn** — 12 turns / 1 764 B pass,
30 turns / 4 410 B are refused. Chunking is therefore structural, and a real
5-minute episode (~5 000 B) splits into **2 chunks, one seam**.

**The seam is not a click, it is a pace change.** Each call is an independent
generation that picks its own tempo: the same chunk sent three times unchanged
came back at 16.9, 15.5 and 13.4 chars/s — 26 % spread on identical input.

`audioConfig.speakingRate` is honoured and near-linear, which makes the fix
deterministic: synthesise, measure the achieved chars/s, re-synthesise
off-target chunks at `rate × target/measured`, clamped to [0.7, 1.4].

```
2-chunk episode, spread across chunks:  uncorrected 7.3 %  →  corrected 2.2 %
```

**The target is relative, not absolute.** The natural rate depends on the shape
of the content: the same voices run at 15.7 chars/s on a dialogue of short turns
and ~20 on monologue prose, because dialogue carries pauses and reactions. A
hard-coded target therefore imposes a tempo instead of levelling one. Calibrate
from the episode's own first pass (median across chunks) and normalise to that.

Cost: one extra call per off-target chunk — at most 2× on a ~$0.08 episode.

### 4.4 Drive

`DriveUploader.upload()` is text-only (`content: str`, mimetype hardcoded to
`text/plain`). Add `upload_bytes(data: bytes, filename, mimetype, folder_id)`
alongside it; keep the existing idempotent find-then-update behaviour.

**Shadow output goes to a third Drive folder** (`GOOGLE_DRIVE_AUDIO_SHADOW_FOLDER_ID`),
never the watched audio folder. A stray file in the watched folder would flip
the dashboard onto an unvalidated episode. Separate folder ⇒ that cannot happen.

Created and verified 2026-08-26: `1sX5dehEK_PksMbS_cvunGHPWo42tAzOQ`
("PODCAST NOTEBOOK SHADOW"), writable by `commodities-compass-data@cacaooo.iam.gserviceaccount.com`.

⚠️ **P5 blocker, found early.** The watched folder ("PODCAST NOTEBOOK") is
`canAddChildren = false` for that service account — it can read, not write.
Nothing needs write today because the audio is uploaded by hand, but the moment
`cc-podcast-audio` targets the watched folder at P5 it will fail. Share the
folder with the service account as Editor *before* the flip, not during it.

### 4.5 Job

- `cc-podcast-audio`, cron `5 20 * * *`, Phase B eve-of-trading gate, same as
  `cc-regime-brief`. `cc-publish-session`'s 20:30 tick picks the file up.
- `deploy_job cc-podcast-audio 512Mi "podcast-audio,--language,both"` in
  `deploy.yml` — the inventory is the source of truth, a job absent from it drifts.
- Fail-loud, `--max-retries=0`, like every other job.

## 5. Benchmark protocol

The point is to separate **two independent variables**: is *our script* as good
as a black-box script, and is *our TTS* as good as NotebookLM's voices.

### 5.1 P0 — two smoke tests (kill candidates cheap, before anything else)

**Pronunciation.** The sleeper risk in FR is not fluency, it is **numbers and
tickers**: `2 438`, `CAZ26`, `36 333 lots`, `ICE`, `COT`, `tonnes`, `YTD`,
`S1`/`R1`. A 30-second torture sentence through each engine, FR and EN. Anything
that mangles a price or a contract code is out before we spend a day on it.

**Stitching (Gemini only).** Synthesize one script both as N chunks stitched and
— where it fits — as a single call, and listen for the seams. See §4.3.1. If
stitching is audible, Gemini loses on a criterion money actually fixes.

### 5.2 Corpus — two corpora, not one

**All three decisions are reachable** (verified 2026-08-26 on a freshly synced
DB): `HEDGE` 86, `OPEN` 75, `MONITOR` 4 since 2025-12-23. `MONITOR` is rare and
recent — first 2026-08-05, last 2026-08-24 — but it is real, so the corpus can
and must cover it.

The two questions need different corpora:

| | Question | Corpus | Control |
|---|---|---|---|
| **P1** | is *our script* right? | wide — any served session, picked for editorial variety (low confidence, macro contradicting the technical read) | none needed; judged on its own against the served row |
| **P2** | is *our voice* good enough? | narrow — only sessions with a real NotebookLM `-Regime` episode in Drive, i.e. from ~2026-08-19 | the NotebookLM episode itself |

**P2's corpus, as of 2026-08-26** — the served rows carrying narrative prose,
which is what `script_writer` consumes:

| Session | Decision | conclusion | eco |
|---|---|---|---|
| 2026-08-18 | OPEN | 751 ch | 440 ch |
| 2026-08-19 | HEDGE | 776 | 401 |
| 2026-08-20 | OPEN | 813 | 456 |
| 2026-08-21 | OPEN | 862 | 393 |
| 2026-08-24 | **MONITOR** | 818 | 408 |
| 2026-08-25 | HEDGE | 787 | 451 |

Six sessions, 3 `OPEN` / 2 `HEDGE` / 1 `MONITOR` — the full decision space, by
luck rather than design. It grows one session per day while P1 is being built.
**The control is free** — the NotebookLM episodes for these days are already in
the Drive audio folder.

**Control coverage, verified 2026-08-26** — 11 `-Regime` episodes in the watched
folder cover all six sessions, with one gap: **2026-08-19 has FR but no EN**.
So the blind test runs 6 pairs in FR and 5 in EN.

### 5.3 Arms

| Arm | Script | Voice |
|---|---|---|
| control | NotebookLM | NotebookLM |
| 1 | ours | Gemini 2.5 Flash TTS |
| 2 | ours | Gemini 2.5 Pro TTS |
| 3 | ours | ElevenLabs v3 Text-to-Dialogue |
| 4 | ElevenLabs GenFM | ElevenLabs |

Arm 4 exists to answer "is our script the weak link, or the voice?" — without
it, a bad result is unattributable.

### 5.4 Blind

Files renamed to opaque ids, order randomised, mapping kept in a sidecar not
opened until scoring is done.

### 5.5 Rubric (1-5 per criterion)

| Criterion | Weight |
|---|---|
| **Factual fidelity** — decision, confidence, figures, no invention | **×2** |
| Conversational naturalness | ×1 |
| FR/EN pronunciation — numbers, tickers, acronyms | ×1 |
| Pace and duration (< 5 min) | ×1 |
| Brand voice / consistency across episodes | ×1 |

Factual fidelity is double-weighted because it is the product. An episode that
sounds beautiful and misstates the signal is worse than no episode.

### 5.6 Decision rule

Escalate the budget **only** if the cheap arm loses on a criterion money
actually fixes (naturalness, pronunciation). If it loses on factual fidelity,
that is a script problem and a more expensive TTS will not fix it.

## 6. Phases

| | Deliverable | Est. | Blocked on |
|---|---|---|---|
| **P0** | ~~pronunciation + stitching~~ **DONE 2026-08-26** — see §3.1 | — | — |
| **P1** | ~~`script_writer.py` + contract tests~~ **DONE 2026-08-26** — `speech_text.py`, `prompts.py`, `script_writer.py`, 40 tests | — | — |
| **P2** | `tts/` adapter + `upload_bytes` + blind benchmark pack delivered | 2 d | P0, P1 |
| **P3** | blind scoring → provider verdict | Hedi | P2 |
| **P4** | `cc-podcast-audio` job + scheduler + shadow folder, running in parallel | 2 d | P3 |
| **P5** | flip: shadow → watched folder, manual NotebookLM stops | — | N shadow sessions clean |

P1 before P2 is deliberate: **validate the script as text before spending a cent
on voice**. If the script is wrong, no engine saves it.

## 6.1 Episode length is measured, not assumed

The prompt has always said "< 5 min". The four NotebookLM episodes of
2026-08-24 and 08-25 actually run **237, 294, 297 and 326 s** (ffprobe, m4a at
~257 kbps). So the real product is 4–5.5 minutes, and `MIN/MAX_DURATION_SECONDS`
is set to **[210, 360]** around the observed ~290 s middle rather than around a
number nobody had checked. At 15 chars/s that is ~3 200–5 400 spoken characters.

## 6.2 Does the Drive brief survive the switch?

Hedi's question, 2026-08-26: once Gemini TTS is in, is the `.txt` still needed?

**The Drive file has no machine consumer.** Grepped: only `regime_brief/config.py`
(which names it) and tests reference it. The judge does *not* read it — 
`scripts/judge_shadow/brief_builder.py` rebuilds brief-shaped text from the
database and borrows only the vendored *parser functions*, never a Drive file.
`script_writer` likewise reads the served row, not the `.txt`.

**But `cc-regime-brief` is not only the `.txt`.** The same job writes
`conclusion` / `eco` / `confidence_rationale` onto the served row, which is what
the dashboard renders and what `script_writer` consumes. **The job stays; only
the Drive upload becomes optional.**

That leaves one question that is commercial, not technical: is the `.txt` read by
anyone — a client, an analyst, an archive? If yes it stays as a deliverable in
its own right. If no, dropping the upload removes a Drive dependency and a
failure mode. Not decided.

## 7. Blockers and open items

### Blockers found 2026-08-25

1. ~~**The local Drive service-account key is dead**~~ — **RESOLVED 2026-08-26.**
   The key in `backend/.env` (`34ef3df5…`) had been **deleted from the service
   account**; production was unaffected because Cloud Run reads Secret Manager,
   not `.env` — "the prod key works" and "the key in your .env works" were two
   different claims. Refreshed from
   `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` (now `c4cd872f…`, the only live
   USER_MANAGED key).
2. ~~**The local DB predates the regime flip**~~ — **RESOLVED 2026-08-26.**
   `sync_from_gcp.py` was itself broken: `SYNC_TABLES` had drifted 10 tables
   behind production (`pl_dashboard_gauge`, the six WatchAI `pl_origin_*` /
   `ref_origin_entity`, and the three `tenant_*`), so `DELETE FROM ref_contract`
   died on an FK. Fixed, plus a fail-loud pre-flight that names any non-empty
   local-only child table blocking the delete (the `tenant_billing_*` case on
   `feat/billing-stripe-socle`). Local is now 45/45 tables, 299 622 rows.

### Open

- ~~Cloud TTS / Vertex enablement~~ — **DONE 2026-08-26.** Both
  `texttospeech.googleapis.com` and `aiplatform.googleapis.com` are enabled on
  `cacaooo`; **`aiplatform` is required even when calling the `texttospeech`
  endpoint** (Gemini-TTS is served by Vertex underneath — a 403
  `SERVICE_DISABLED` on `aiplatform` is what you get otherwise). First live call
  returned HTTP 200, 597 KB / ~12.4 s of `fr-FR` audio on
  `gemini-3.1-flash-tts-preview` via ADC.
- ElevenLabs free tier is 10 000 credits/month ≈ **2 episodes**. The full
  benchmark (12 episodes ≈ 60 000 chars) needs one month of Creator (~$22), or
  ~$6 at the stated API rate. Confirm which meter applies before topping up.
- `GOOGLE_DRIVE_AUDIO_SHADOW_FOLDER_ID` — folder to create (blocker 1).
- How many clean shadow sessions gate P5 — **Hedi judges on the output**, no
  fixed threshold.
- ElevenLabs Studio podcast endpoint may require workspace allowlisting —
  confirm before counting on arm 4.
- ~~**`scripts/` is excluded from pyright**~~ — **RESOLVED**, PR #116. The
  exclusion dated from 2026-03-09 (`bffc272`, "resolve pyright errors for CI"),
  so every Cloud Run job went unchecked for five and a half months — and almost
  everything in `scripts/` today was written after it. The pre-commit hook
  matched those files and printed `Passed` while pyright skipped them, which is
  why nobody noticed. 66 errors closed in shipping modules; `archive` and
  `research` stay excluded.
- `backend/.env.bak*` is **not** covered by `.gitignore` — a hand-made backup of
  `.env` shows up as untracked and is one `git add .` away from being committed.
  One line in `.gitignore` would close it.

## 8. Sources

- [Gemini Notebook Enterprise — audio overview API](https://docs.cloud.google.com/gemini/enterprise/notebooklm-enterprise/docs/api-audio-overview)
- [Gemini API — speech generation](https://ai.google.dev/gemini-api/docs/speech-generation)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [ElevenLabs — Create Podcast](https://elevenlabs.io/docs/api-reference/studio/create-podcast)
- [ElevenLabs — Text to Dialogue](https://elevenlabs.io/docs/overview/capabilities/text-to-dialogue)
