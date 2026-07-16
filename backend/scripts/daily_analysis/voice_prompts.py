"""Voice-only Call #2 prompts (US-1 facts/voice refactor).

The LLM no longer writes the numbered conclusion — it writes a single
qualitative HEADLINE plus the decision fields (decision, confiance,
[confiance_rationale], direction). Every number (the fact-bullets and the
à-surveiller alerts) is rendered deterministically from the FactsPayload by the
engine, so the model never re-types a figure. This is what makes the numbers
correct-by-construction and the output language-parametric.

The superseded full-conclusion prompts still live in ``prompts.py`` and are no
longer called; they are removed once the flip is validated (US-1e cleanup).
The ensemble diagnostics block + conviction/formatting helpers are reused from
``prompts.py`` so the confidence rubric and forbidden-vocabulary rules stay in
one place.
"""

from __future__ import annotations

from scripts.daily_analysis.prompts import (
    ENSEMBLE_DIAGNOSTICS_BLOCK,
    _format_optional,
    _qualitative_conviction,
)

# Shared technical context. Uses the same TOD/YES variable names the build
# functions inject (with %K/%D renamed to pctK/pctD so str.format() is happy).
_TECHNICALS_CONTEXT = """\
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


# ---------------------------------------------------------------------------
# Legacy (non-ensemble) voice prompt
# ---------------------------------------------------------------------------

_LEGACY_INTRO = """\
Tu es un trader expert du marché cacao à Londres. Tu rédiges une lecture de
marché destinée à des exportateurs d'Afrique de l'Ouest.

Tu disposes d'un indicateur agrégé {FINAL_INDICATOR}. La décision du jour,
fondée sur cet indicateur, est {FINAL_CONCLUSION} (OPEN, MONITOR ou HEDGE). Tu
dois la respecter sans contradiction ni alternative.
"""

_VOICE_TASK_LEGACY = """\
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

_LEGACY_JSON = (
    '{{"decision": "OPEN ou MONITOR ou HEDGE", "confiance": 3, '
    '"direction": "HAUSSIERE ou BAISSIERE ou NEUTRE", '
    '"headline": "Repli mesuré du marché, la prudence reste de mise sur la séance."}}'
)

CALL_2_VOICE_PROMPT = (
    _LEGACY_INTRO
    + "\n"
    + _TECHNICALS_CONTEXT
    + "\n"
    + _VOICE_TASK_LEGACY
    + "\n"
    + _LEGACY_JSON
)


# ---------------------------------------------------------------------------
# Ensemble-aligned voice prompt
# ---------------------------------------------------------------------------

_ENSEMBLE_INTRO = """\
Tu es un trader expert du marché cacao à Londres. Tu rédiges une lecture de
marché destinée à des exportateurs d'Afrique de l'Ouest.
"""

_VOICE_TASK_ENSEMBLE = """\
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

_ENSEMBLE_JSON = (
    '{{"decision": "{DECISION_WRAPPED}", "confiance": 3, '
    '"confiance_rationale": "Tech + macro alignés, stocks neutres, climat NUANCE.", '
    '"direction": "HAUSSIERE ou BAISSIERE ou NEUTRE", '
    '"headline": "Lecture Compass alignée sur la position {DECISION_WRAPPED}, '
    'conviction modérée, biais neutre sur la fenêtre à venir."}}'
)

CALL_2_VOICE_PROMPT_ENSEMBLE = (
    _ENSEMBLE_INTRO
    + "\n"
    + ENSEMBLE_DIAGNOSTICS_BLOCK
    + "\n"
    + _TECHNICALS_CONTEXT
    + "\n"
    + _VOICE_TASK_ENSEMBLE
    + "\n"
    + _ENSEMBLE_JSON
)


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
) -> str:
    """Build the legacy voice-only Call #2 prompt."""
    variables = _inject_technicals(technicals_today, technicals_yesterday)
    variables["FINAL_INDICATOR"] = str(final_indicator)
    variables["FINAL_CONCLUSION"] = final_conclusion
    return CALL_2_VOICE_PROMPT.format(**variables)


def build_call2_voice_prompt_ensemble(
    technicals_today: dict[str, str],
    technicals_yesterday: dict[str, str],
    ensemble: object,  # EnsembleDiagnostics — attr access to avoid circular import
) -> str:
    """Build the ensemble-aligned voice-only Call #2 prompt.

    Only the 5 diagnostics variables the block actually references are injected;
    ``str.format`` ignores any others.
    """
    variables = _inject_technicals(technicals_today, technicals_yesterday)
    variables.update(
        {
            "DECISION_WRAPPED": str(getattr(ensemble, "decision_wrapped", "MONITOR")),
            "CONVICTION_QUALITATIVE": _qualitative_conviction(
                getattr(ensemble, "net_score", None),
                getattr(ensemble, "n_committed_specialists", None),
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
    return CALL_2_VOICE_PROMPT_ENSEMBLE.format(**variables)
