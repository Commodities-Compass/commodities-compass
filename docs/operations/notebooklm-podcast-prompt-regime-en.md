# NotebookLM podcast prompt — Compass Daily Brief (regime track, English / Ghana edition)

> Source of truth for the prompt pasted into NotebookLM's "Customise" panel
> before generating the daily **English** audio podcast from
> `YYYYMMDD-CompassBrief-Regime-EN.txt`. Any change here MUST be mirrored in
> NotebookLM (and vice versa) so we keep a single, versioned canon.
>
> This is the **native-English** counterpart of
> [notebooklm-podcast-prompt-regime.md](notebooklm-podcast-prompt-regime.md) — a
> re-write, not a translation. The brand hooks ("Compasteurs"), the register
> (British / West-African trader English) and the Ghana-first framing are
> deliberate identity choices (decisions D4 + US-4).

## What changed vs the ensemble prompt

Only three things, because only one section of the brief changed:

1. **Horizon** — the regime call decides for the **next session**, not a 4-to-5
   session window. This is the change most likely to be missed: an audio that
   promises a week-long view on a next-day signal misrepresents the product.
2. **Point 4 (editorial)** — the ensemble brief named a headline read among
   several converging reads. The regime brief names the **market regime** and how
   the **macro arbitration** landed. No panel, no convergence, no counting.
3. **Point 3 (rationale)** — the confidence sentence is no longer a list of
   pillars with SUPPORT/NUANCE roles. It is a single sentence naming what would
   invalidate the read.

Everything else is unchanged, because the brief's other sections are unchanged:
they describe the market, not the algorithm.

## Why this prompt is redacted

The daily audio is distributed outside the engineering team and is the most
exposed channel for reverse-engineering the decision engine. The prompt is
intentionally redacted of any reference to the underlying architecture (regime
detection, specialists, the macro overlay's mechanics). The brief template that
NotebookLM ingests ([regime_brief/brief_generator.py](../../backend/scripts/regime_brief/brief_generator.py))
is similarly redacted, and refuses to render if a field leaks — keep both in
sync when you tweak either side.

## How to use

1. Open the NotebookLM notebook tied to the Compass Daily Brief workflow.
2. Set the notebook / Audio Overview **output language to English**.
3. Upload the day's `YYYYMMDD-CompassBrief-Regime-EN.txt` (or paste it).
4. In "Customise", paste the **prompt body** below verbatim.
5. Click "Generate".
6. Download the audio, rename to `YYYYMMDD-CompassAudio-Regime-EN.m4a` and
   upload back to the Drive folder watched by the dashboard.

## Prompt body

Copy-paste everything below the rule into NotebookLM:

---

Read the document and generate a podcast script (<5 min) between two English-
speaking market experts (1 woman, 1 man) in natural, conversational English.
ABOVE ALL, do NOT switch voices mid-podcast — the exchange must be a
conversation, not a sequential read-out. Use a British / West-African trading
register (spell "tonnes", "favourable"; prices in GBP per tonne).

The document is a Compass brief on London COCOA, horizon the next trading
session.

FORBIDDEN VOCABULARY (NEVER say these words):
  • "artificial intelligence", "AI", "AI expert", "AI algorithm"
  • internal mechanics: "regime detector", "specialist", "model",
    "probability", "score", "machine learning", "proprietary model"
  • never count votes, reads or indicators

Mandatory structure:

1. HOOK (≤30 sec)
   - ALWAYS open with "Good morning, Compasteurs!"
   - One intro line: "today's Compass signal on London COCOA, horizon the next
     session."

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
   - **Read and reword the sentence that follows the score** in the
     "Confidence: X/5 — [sentence]" line. That sentence says what could prove
     today's read wrong. Reword it as a fluid line: "conviction stays measured
     — a return to normal on the logistics side would call this read into
     question" (adapt to the brief's exact words).
   - If no confidence is present: skip to point 4 without inventing anything.

4. EDITORIAL READ (1 to 2 min — section "II — EDITORIAL READ" of the brief)
   ⭐ KEY SECTION — editorial, not an inventory.

   - The brief first names the MARKET REGIME in plain language (for instance
     "established uptrend", "no clear direction", "elevated volatility").
     Explain in 2 sentences what that regime means concretely for a physical
     buyer.
   - The brief then says how the MACRO READ sat against the technical stance:
     it confirms it, it opposes it, or it does not decide. Reword that sentence
     in prose and explain the arbitration — that is the editorial core of the
     day.
   - Refer to "the technical read" and "the macro read" as two angles of
     analysis. Do NOT mention a specialist, a model, a probability, or any
     decision mechanism.

5. ECO + PRESS (1 to 2 min — section "III — ECO & PRESS REVIEW" of the brief)
   - Market news, macro release, chocolate demand. Fluid tone.

6. WEATHER (≤1 min — section "IV — WEATHER WATCH" of the brief)
   - Côte d'Ivoire + Ghana, short-term impact and campaign trajectory. Frame
     Ghana first for this edition.

7. TECHNICAL SNAPSHOT (≤30 sec — section "V — TECHNICAL SNAPSHOT" of the brief)
   - The levels that matter, in prose: close, volume, open interest, stocks
     (in tonnes).

8. RECOMMENDATION + TO WATCH (≤1 min — section "VI — OPERATIONAL
   RECOMMENDATIONS" of the brief)
   - Reword the decision in operational terms for the next session.
   - Read the "TO WATCH" alerts in prose, not as a list.

9. CLOSE
   - ALWAYS end with "See you tomorrow, Compasteurs!"

CROSS-CUTTING CONSTRAINTS:
- Fluid, professional style, like two financial journalists trading views.
- Invent NO figures. Use ONLY what is in the document.
- If a section is absent or marked "n/a", move to the next point without
  commenting on it.
- ABOVE ALL: do NOT switch voices mid-podcast; the exchange stays
  conversational between a woman and a man, in natural English.
