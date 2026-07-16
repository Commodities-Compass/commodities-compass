# NotebookLM podcast prompt — Compass Daily Brief (English / Ghana edition)

> Source of truth for the prompt pasted into NotebookLM's "Customise" panel
> before generating the daily **English** audio podcast from
> `YYYYMMDD-CompassBrief-Ensemble-EN.txt`. Any change here MUST be mirrored in
> NotebookLM (and vice versa) so we keep a single, versioned canon.
>
> This is the **native-English** counterpart of
> [notebooklm-podcast-prompt.md](notebooklm-podcast-prompt.md) — a re-write, not
> a translation. The brand hooks ("Compasteurs"), the register (British / West-
> African trader English), and the Ghana-first framing are deliberate identity
> choices (decisions D4 + US-4). Ensemble track only (US-4 scope decision §5).

## Why this prompt is redacted

The daily audio is distributed outside the engineering team and is the most
exposed channel for reverse-engineering the decision engine. The prompt is
intentionally redacted of any reference to the underlying architecture (panel
size, model family, orchestrator, internal detectors) to avoid leaking
proprietary mechanics in casual listening. The brief template that NotebookLM
ingests ([compass_brief_ensemble/brief_generator.py](../../backend/scripts/compass_brief_ensemble/brief_generator.py))
is similarly redacted — keep both in sync when you tweak either side.

## How to use

1. Open the NotebookLM notebook tied to the Compass Daily Brief workflow.
2. Set the notebook / Audio Overview **output language to English**.
3. Upload the day's `YYYYMMDD-CompassBrief-Ensemble-EN.txt` (or paste it).
4. In "Customise", paste the **prompt body** below verbatim.
5. Click "Generate".
6. Download the audio, rename to `YYYYMMDD-CompassAudio-Ensemble-EN.m4a` and
   upload back to the Drive folder watched by the dashboard.

## Prompt body

Copy-paste everything below the rule into NotebookLM:

---

Read the document and generate a podcast script (<5 min) between two English-
speaking market experts (1 woman, 1 man) in natural, conversational English.
ABOVE ALL, do NOT switch voices mid-podcast — the exchange must be a
conversation, not a sequential read-out. Use a British / West-African trading
register (spell "tonnes", "favourable"; prices in GBP per tonne).

The document is a Compass brief on London COCOA, horizon 4 to 5 trading
sessions.

FORBIDDEN VOCABULARY (NEVER say these words):
  • "artificial intelligence", "AI", "AI expert", "AI algorithm"
  • anything about a panel size, a number of specialists, "X out of 14"
  • internal mechanics: "orchestrator", "soft-gate", "wrapper", "detector",
    "cluster", "net score", "machine learning", "proprietary model"

Mandatory structure:

1. HOOK (≤30 sec)
   - ALWAYS open with "Good morning, Compasteurs!"
   - One intro line: "today's Compass signal on London COCOA, horizon 4 to 5
     sessions."

2. YTD PERFORMANCE (≤20 sec)
   - Cite the signal's YTD performance exactly as written in the brief.
   - Clearly positive: confident tone. Negative or weak: acknowledge the
     tricky phase honestly. Absent from the brief: skip straight to point 3
     without commenting on it.

3. TODAY'S DECISION (≤60 sec)
   - State it plainly: OPEN, HEDGE or MONITOR.
   - The direction (bullish, bearish, neutral) MUST be coherent with the
     decision (HEDGE is bearish, OPEN is bullish).
   - Give the confidence (1 to 5) as it appears in Section I of the brief.
   - **Read and reword the rationale sentence that follows the score** in the
     "Confidence: X/5 — [rationale]" line. The rationale lists 2-3 pillars
     (Technical, Macro, Sentiment, Fundamentals, Weather) with a SUPPORT or
     NUANCE role. Reword it as a fluid sentence: "the technical read and the
     macro back the position, stocks stay neutral and the weather adds a slight
     nuance" (adapt to the brief's exact words).
   - If no confidence or rationale is present in the brief: skip to point 4
     without inventing anything.

4. EDITORIAL READ (1 to 2 min — section "II — EDITORIAL READ" of the brief)
   ⭐ KEY SECTION — editorial, not an inventory.
   - Cite ONLY the headline read named in the brief (a single business label).
     Explain its read of the day in 2 sentences, drawing on the description
     provided right under the label.
   - For the rest: paraphrase the sentence "other reads converge on this
     verdict — an FX read and a macro read" (or the brief's equivalent). Do NOT
     name the other reads by their labels.
   - Do NOT read a table, do NOT count votes, do NOT mention abstentions, do NOT
     talk about a "panel" or "specialist convergence".

5. ECO + PRESS (1 to 2 min — section "III — ECO & PRESS REVIEW" of the brief)
   - Market news, macro release, chocolate demand. Fluid tone.

6. WEATHER (≤1 min — section "IV — WEATHER WATCH" of the brief)
   - Côte d'Ivoire + Ghana, short-term and longer-term impact. Frame Ghana
     first for this edition.

7. TECHNICAL SNAPSHOT (≤30 sec — section "V — TECHNICAL SNAPSHOT" of the brief)
   - The levels that matter, in prose: close, RSI, MACD, stocks (in tonnes).

8. RECOMMENDATION + TO WATCH (≤1 min — section "VI — OPERATIONAL
   RECOMMENDATIONS" of the brief)
   - Reword the decision in operational terms for the 4-to-5-session window.
   - Read the 3 "TO WATCH" alerts in prose, not as a list.

9. CLOSE
   - ALWAYS end with "See you tomorrow, Compasteurs!"

CROSS-CUTTING CONSTRAINTS:
- Fluid, professional style, like two financial journalists trading views.
- Invent NO figures. Use ONLY what is in the document.
- If a section is absent or marked "n/a", move to the next point without
  commenting on it.
- ABOVE ALL: do NOT switch voices mid-podcast; the exchange stays
  conversational between a woman and a man, in natural English.
