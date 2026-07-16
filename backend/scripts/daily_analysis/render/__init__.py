"""Per-locale renderers: FactsPayload -> deterministic conclusion body.

The renderer owns the fact-bullets and à-surveiller alerts; the LLM voice owns
only the headline. Numbers are formatted here so the model never re-types one.
Adding a language = adding a module (mirroring ``fr``) and registering it below.
"""

from __future__ import annotations

from types import ModuleType

from scripts.daily_analysis.render import en, fr

DEFAULT_LANG = "fr"

_RENDERERS: dict[str, ModuleType] = {
    fr.LANG: fr,
    en.LANG: en,
}


def get_renderer(lang: str) -> ModuleType:
    """Return the renderer module for ``lang``, falling back to French."""
    return _RENDERERS.get(lang, _RENDERERS[DEFAULT_LANG])
