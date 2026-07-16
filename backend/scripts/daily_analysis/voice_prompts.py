"""Voice-only Call #2 prompts (US-1 facts/voice refactor + US-3 English edition).

The LLM writes only a qualitative HEADLINE plus the decision fields (decision,
confiance, [confiance_rationale], direction). Every number is rendered
deterministically from the FactsPayload by the engine, so the model never
re-types a figure. This module is language-parametric: ``build_*(..., language)``
selects the FR or EN template set. The JSON field names stay French-named
(``confiance``, ``confiance_rationale``) because the parser + DB expect them; only
the prose/instructions differ per language. Decision (OPEN/MONITOR/HEDGE) and
direction (HAUSSIERE/BAISSIERE/NEUTRE) enum VALUES are kept as-is in both
languages (downstream contracts depend on them).

The superseded full-conclusion prompts still live in ``prompts.py`` (deprecated).
"""

from __future__ import annotations

from scripts.daily_analysis.prompts import (
    ENSEMBLE_DIAGNOSTICS_BLOCK,
    _format_optional,
    _qualitative_conviction,
)

# ---------------------------------------------------------------------------
# Shared technical context (per language)
# ---------------------------------------------------------------------------

_TECHNICALS_CONTEXT_FR = """\
Données techniques du jour (aujourd'hui vs hier), pour t'aider à juger :
- CLOSE : {CLOSETOD} (hier {CLOSEYES})
- HIGH : {HIGHTOD} (hier {HIGHYES})
- LOW : {LOWTOD} (hier {LOWYES})
- VOLUME : {VOLTOD} (hier {VOLYES})
- OPEN INTEREST : {OITOD} (hier {OIYES})
- IMPLIED VOLATILITY : {VOLIMPTOD} (hier {VOLIMPYES})
- STOCK US (tonnes) : {STOCKUSTOD} (hier {STOCKUSYES})
- STOCK EU (tonnes) : {STOCKEUTOD} (hier {STOCKEUYES})
- COM NET : {COMNETTOD} (hier {COMNETYES})
- PIVOT : {PIVOTTOD} | SUPPORT 1 : {S1TOD} | RESISTANCE 1 : {R1TOD}
- EMA9 : {EMA9TOD} | EMA21 : {EMA21TOD}
- MACD : {MACDTOD} (signal {SIGNTOD})
- RSI : {RSI14TOD} | %K : {pctKTOD} | %D : {pctDTOD} | ATR : {ATRTOD}
- BOLLINGER SUP : {BSUPTOD} | BOLLINGER INF : {BBINFTOD}
"""

_TECHNICALS_CONTEXT_EN = """\
Today's technicals (today vs the prior session), to inform your read:
- CLOSE: {CLOSETOD} (prior {CLOSEYES})
- HIGH: {HIGHTOD} (prior {HIGHYES})
- LOW: {LOWTOD} (prior {LOWYES})
- VOLUME: {VOLTOD} (prior {VOLYES})
- OPEN INTEREST: {OITOD} (prior {OIYES})
- IMPLIED VOLATILITY: {VOLIMPTOD} (prior {VOLIMPYES})
- US STOCKS (tonnes): {STOCKUSTOD} (prior {STOCKUSYES})
- EU STOCKS (tonnes): {STOCKEUTOD} (prior {STOCKEUYES})
- COM NET: {COMNETTOD} (prior {COMNETYES})
- PIVOT: {PIVOTTOD} | SUPPORT 1: {S1TOD} | RESISTANCE 1: {R1TOD}
- EMA9: {EMA9TOD} | EMA21: {EMA21TOD}
- MACD: {MACDTOD} (signal {SIGNTOD})
- RSI: {RSI14TOD} | %K: {pctKTOD} | %D: {pctDTOD} | ATR: {ATRTOD}
- BOLLINGER UP: {BSUPTOD} | BOLLINGER LOW: {BBINFTOD}
"""

# ---------------------------------------------------------------------------
# Legacy (non-ensemble) voice prompt
# ---------------------------------------------------------------------------

_LEGACY_INTRO_FR = """\
Tu es un trader expert du marché cacao à Londres. Tu rédiges une lecture de
marché destinée à des exportateurs d'Afrique de l'Ouest.

Tu disposes d'un indicateur agrégé {FINAL_INDICATOR}. La décision du jour,
fondée sur cet indicateur, est {FINAL_CONCLUSION} (OPEN, MONITOR ou HEDGE). Tu
dois la respecter sans contradiction ni alternative.
"""

_LEGACY_INTRO_EN = """\
You are an expert London cocoa trader writing a market read for West-African
exporters.

You have an aggregate indicator {FINAL_INDICATOR}. Today's decision, based on
it, is {FINAL_CONCLUSION} (OPEN, MONITOR or HEDGE). You must respect it without
contradiction or alternative.
"""

_VOICE_TASK_LEGACY_FR = """\
Ta tâche — produis UNIQUEMENT une lecture éditoriale, jamais de données chiffrées :

1. CONFIANCE : de 1 (faible) à 5 (forte), selon que les indicateurs soutiennent
   la décision {FINAL_CONCLUSION}.
2. DIRECTION : "HAUSSIERE" (OPEN), "BAISSIERE" (HEDGE) ou "NEUTRE" (MONITOR).
3. HEADLINE : UNE seule phrase de synthèse qualitative sur la lecture du jour et
   la fenêtre à venir.
   INTERDIT dans le headline : chiffres de marché, seuils, pourcentages, bullets,
   liste « à surveiller ». Ces éléments chiffrés sont générés automatiquement —
   ne les écris PAS.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour :
"""

_VOICE_TASK_LEGACY_EN = """\
Your task — produce ONLY an editorial read, never figures:

1. confiance: 1 (low) to 5 (high), depending on whether the indicators back the
   {FINAL_CONCLUSION} decision.
2. direction: "HAUSSIERE" (OPEN), "BAISSIERE" (HEDGE) or "NEUTRE" (MONITOR)
   — keep these exact enum values.
3. headline: ONE qualitative sentence summarising today's read and the window
   ahead.
   FORBIDDEN in the headline: market figures, thresholds, percentages, bullets,
   any "to watch" list. Those numbered elements are generated automatically —
   do NOT write them.

Reply ONLY with a valid JSON object, no surrounding text:
"""

_LEGACY_JSON_FR = (
    '{{"decision": "OPEN ou MONITOR ou HEDGE", "confiance": 3, '
    '"direction": "HAUSSIERE ou BAISSIERE ou NEUTRE", '
    '"headline": "Repli mesuré du marché, la prudence reste de mise sur la séance."}}'
)

_LEGACY_JSON_EN = (
    '{{"decision": "OPEN or MONITOR or HEDGE", "confiance": 3, '
    '"direction": "HAUSSIERE or BAISSIERE or NEUTRE", '
    '"headline": "Measured pullback, caution stays warranted into the session."}}'
)

# ---------------------------------------------------------------------------
# Ensemble-aligned voice prompt
# ---------------------------------------------------------------------------

_ENSEMBLE_INTRO_FR = """\
Tu es un trader expert du marché cacao à Londres. Tu rédiges une lecture de
marché destinée à des exportateurs d'Afrique de l'Ouest.
"""

_ENSEMBLE_INTRO_EN = """\
You are an expert London cocoa trader writing a market read for West-African
exporters.
"""

# English mirror of prompts.ENSEMBLE_DIAGNOSTICS_BLOCK — same confidence rubric
# and forbidden-vocabulary rules, translated for the EN edition.
_ENSEMBLE_DIAGNOSTICS_BLOCK_EN = """\
DECISION CONTEXT — TODAY'S COMPASS READING

Today's decision ({DECISION_WRAPPED}) is the Compass verdict — you MUST justify
it from the diagnostics below, NOT from a technical composite score.

Signal diagnostics:
- Decision: {DECISION_WRAPPED}
- Intrinsic Compass conviction: {CONVICTION_QUALITATIVE}
- Macro direction (filtered signal): {MACRO_DIRECTION} (surprise={MACRO_SURPRISE}, half-life={MACRO_HALF_LIFE_DAYS}d)

═══ CONFIDENCE ASSESSMENT (fields "confiance" + "confiance_rationale") ═══

Confidence reflects how strongly today's external factors back the Compass
decision. CORE RULE: the Compass decision is the verdict — external factors can
ONLY reinforce confidence or slightly temper it. They can NEVER contradict it.

STEP 1 — Confidence base, from the intrinsic Compass conviction:
- "strong" conviction   → base 4
- "moderate" conviction → base 3
- "weak" conviction     → base 2

STEP 2 — Modulation by the 5 external pillars (technical, macro, market
sentiment, fundamentals, weather). For each, judge whether it SUPPORTS, is
NEUTRAL, or adds a slight NUANCE vs the Compass decision:
- SUPPORT: the pillar clearly aligns with the decision
- NEUTRAL: no clear signal, or mixed
- NUANCE: a slight friction (e.g. mildly bullish sentiment on a HEDGE) — NEVER
  a hard contradiction

STEP 3 — Final adjustment (max ±1 from the base):
- Majority SUPPORT → +1 (max 5)
- Majority NEUTRAL / mixed → 0 (keep the base)
- 1 or 2 NUANCE pillars → -1 (min 1)

STRICT RULE: never -2 or worse. External factors never contradict the Compass
decision — they only temper confidence around the base.

Vocabulary to use in the headline:
- "strong / moderate / weak conviction" for the Compass engagement
- "today's readings converge" / "readings that align"
- "bullish / bearish / neutral direction" for today's bias

STRICTLY FORBIDDEN VOCABULARY (NEVER write these — they trigger a downstream
pipeline cut):
- Any mention of the panel size — no "X specialists out of 14", no "X/14", no
  "panel of 14"
- Any internal diagnostic figure: no "net_score", no "running_acc", no
  "anomaly_z", no "composite score"
- Any internal architecture: no "soft-gate", no "wrapper", no "safety net", no
  "detector", no "Winter cluster", no "Spring cluster", no "Bayesian
  orchestrator", no "ensemble v1", no "machine learning", no "proprietary model"
- No specialist technical names (W1, W2, exp_optim_*, xpol_*)

You may name ONE or two business specialist labels (trend reader, bearish FX
sentinel, global macro strategist…) if relevant, only to describe what they
watch — never to reveal the panel size.

"""

_VOICE_TASK_ENSEMBLE_FR = """\
Ta tâche — produis UNIQUEMENT une lecture éditoriale, jamais de données chiffrées :

1. CONFIANCE : entier de 1 à 5, dérivé STRICTEMENT de la rubrique ÉVALUATION DE
   LA CONFIANCE ci-dessus (base 2/3/4 selon la conviction qualitative +
   ajustement max ±1 selon les piliers externes).
2. confiance_rationale : 60 à 140 caractères listant 2-3 piliers dominants avec
   leur rôle SOUTIEN ou NUANCE (ex. : "Tech + macro alignés, stocks neutres, climat NUANCE.").
3. DIRECTION cohérente avec {DECISION_WRAPPED} (HEDGE→BAISSIERE, OPEN→HAUSSIERE,
   MONITOR→NEUTRE).
4. HEADLINE : UNE seule phrase qualitative décrivant la conviction Compass du
   jour (forte / modérée / faible) et le biais.
   INTERDIT dans le headline : tout chiffre interne, tout chiffre de marché, tout
   seuil, bullets, liste « à surveiller ». Respecte le VOCABULAIRE STRICTEMENT
   INTERDIT ci-dessus. Les éléments chiffrés sont générés automatiquement.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour :
"""

_VOICE_TASK_ENSEMBLE_EN = """\
Your task — produce ONLY an editorial read, never figures:

1. confiance: integer 1 to 5, derived STRICTLY from the CONFIDENCE ASSESSMENT
   rubric above (base 2/3/4 by qualitative conviction + max ±1 by the external
   pillars).
2. confiance_rationale: 60 to 140 characters listing 2-3 dominant pillars with
   their SUPPORT or NUANCE role (e.g. "Tech + macro aligned, stocks neutral, weather NUANCE.").
3. direction consistent with {DECISION_WRAPPED} (HEDGE→BAISSIERE, OPEN→HAUSSIERE,
   MONITOR→NEUTRE) — keep these exact enum values.
4. headline: ONE qualitative sentence describing today's Compass conviction
   (strong / moderate / weak) and the bias.
   FORBIDDEN in the headline: any internal figure, any market figure, any
   threshold, bullets, any "to watch" list. Respect the STRICTLY FORBIDDEN
   VOCABULARY above. Numbered elements are generated automatically.

Reply ONLY with a valid JSON object, no surrounding text:
"""

_ENSEMBLE_JSON_FR = (
    '{{"decision": "{DECISION_WRAPPED}", "confiance": 3, '
    '"confiance_rationale": "Tech + macro alignés, stocks neutres, climat NUANCE.", '
    '"direction": "HAUSSIERE ou BAISSIERE ou NEUTRE", '
    '"headline": "Lecture Compass alignée sur la position {DECISION_WRAPPED}, '
    'conviction modérée, biais neutre sur la fenêtre à venir."}}'
)

_ENSEMBLE_JSON_EN = (
    '{{"decision": "{DECISION_WRAPPED}", "confiance": 3, '
    '"confiance_rationale": "Tech + macro aligned, stocks neutral, weather NUANCE.", '
    '"direction": "HAUSSIERE or BAISSIERE or NEUTRE", '
    '"headline": "Compass reading aligned with the {DECISION_WRAPPED} call, '
    'moderate conviction, neutral bias into the window ahead."}}'
)


def _assemble(intro: str, task: str, json_ex: str, context: str) -> str:
    return intro + "\n" + context + "\n" + task + "\n" + json_ex


def _assemble_ensemble(
    intro: str, block: str, task: str, json_ex: str, context: str
) -> str:
    return intro + "\n" + block + "\n" + context + "\n" + task + "\n" + json_ex


_LEGACY_PROMPT: dict[str, str] = {
    "fr": _assemble(
        _LEGACY_INTRO_FR, _VOICE_TASK_LEGACY_FR, _LEGACY_JSON_FR, _TECHNICALS_CONTEXT_FR
    ),
    "en": _assemble(
        _LEGACY_INTRO_EN, _VOICE_TASK_LEGACY_EN, _LEGACY_JSON_EN, _TECHNICALS_CONTEXT_EN
    ),
}

_ENSEMBLE_PROMPT: dict[str, str] = {
    "fr": _assemble_ensemble(
        _ENSEMBLE_INTRO_FR,
        ENSEMBLE_DIAGNOSTICS_BLOCK,
        _VOICE_TASK_ENSEMBLE_FR,
        _ENSEMBLE_JSON_FR,
        _TECHNICALS_CONTEXT_FR,
    ),
    "en": _assemble_ensemble(
        _ENSEMBLE_INTRO_EN,
        _ENSEMBLE_DIAGNOSTICS_BLOCK_EN,
        _VOICE_TASK_ENSEMBLE_EN,
        _ENSEMBLE_JSON_EN,
        _TECHNICALS_CONTEXT_EN,
    ),
}

# Back-compat aliases (FR) — some readers reference these module constants.
CALL_2_VOICE_PROMPT = _LEGACY_PROMPT["fr"]
CALL_2_VOICE_PROMPT_ENSEMBLE = _ENSEMBLE_PROMPT["fr"]

# FR conviction label -> EN. Reuses the FR threshold logic so the (net_score,
# n_committed) -> label mapping stays in one place.
_CONVICTION_EN: dict[str, str] = {
    "forte": "strong",
    "modérée": "moderate",
    "faible": "weak",
}


def _conviction_label(net_score: object, n_committed: object, language: str) -> str:
    fr = _qualitative_conviction(net_score, n_committed)
    return _CONVICTION_EN.get(fr, fr) if language == "en" else fr


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _inject_technicals(
    today: dict[str, str], yesterday: dict[str, str]
) -> dict[str, str]:
    """Merge today/yesterday dicts, renaming %K/%D so str.format() is happy."""
    variables: dict[str, str] = {}
    for key, val in today.items():
        variables[key.replace("%K", "pctK").replace("%D", "pctD")] = val
    for key, val in yesterday.items():
        variables[key.replace("%K", "pctK").replace("%D", "pctD")] = val
    return variables


def build_call2_voice_prompt(
    technicals_today: dict[str, str],
    technicals_yesterday: dict[str, str],
    final_indicator: float,
    final_conclusion: str,
    language: str = "fr",
) -> str:
    """Build the legacy voice-only Call #2 prompt in ``language`` (fr | en)."""
    variables = _inject_technicals(technicals_today, technicals_yesterday)
    variables["FINAL_INDICATOR"] = str(final_indicator)
    variables["FINAL_CONCLUSION"] = final_conclusion
    return _LEGACY_PROMPT.get(language, _LEGACY_PROMPT["fr"]).format(**variables)


def build_call2_voice_prompt_ensemble(
    technicals_today: dict[str, str],
    technicals_yesterday: dict[str, str],
    ensemble: object,  # EnsembleDiagnostics — attr access to avoid circular import
    language: str = "fr",
) -> str:
    """Build the ensemble-aligned voice-only Call #2 prompt in ``language``.

    Only the 5 diagnostics variables the block references are injected;
    ``str.format`` ignores any others.
    """
    variables = _inject_technicals(technicals_today, technicals_yesterday)
    variables.update(
        {
            "DECISION_WRAPPED": str(getattr(ensemble, "decision_wrapped", "MONITOR")),
            "CONVICTION_QUALITATIVE": _conviction_label(
                getattr(ensemble, "net_score", None),
                getattr(ensemble, "n_committed_specialists", None),
                language,
            ),
            "MACRO_DIRECTION": _format_optional(
                getattr(ensemble, "macro_direction", None)
            ),
            "MACRO_SURPRISE": _format_optional(
                getattr(ensemble, "macro_surprise", None), 3
            ),
            "MACRO_HALF_LIFE_DAYS": _format_optional(
                getattr(ensemble, "macro_half_life_days", None)
            ),
        }
    )
    return _ENSEMBLE_PROMPT.get(language, _ENSEMBLE_PROMPT["fr"]).format(**variables)
