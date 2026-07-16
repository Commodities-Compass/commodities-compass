"""Language / locale primitives for content i18n.

Single source of truth for the supported content languages and the
request-time language resolution rule. Introduced by US-0 (EN/Ghana edition):
the ``language`` dimension keys the content tables (``pl_indicator_daily``,
``pl_fundamental_article``, ``pl_weather_observation``) and threads through the
serving layer. Stepping stone toward the North Star ``tenant.account.locale``.

Default is FRENCH: all existing content is French and the existing user is
French-speaking; English is opt-in. The serving layer must never silently
serve one language's content under another language's label.
"""

from __future__ import annotations

from enum import StrEnum


class Language(StrEnum):
    """Supported content languages."""

    FR = "fr"
    EN = "en"


DEFAULT_LANGUAGE: Language = Language.FR
SUPPORTED_LANGUAGES: frozenset[Language] = frozenset(Language)

# Pipeline-agent CLI: the accepted --language values. ``both`` runs every
# language in one execution (no per-language Cloud Run jobs).
LANGUAGE_CLI_CHOICES: tuple[str, ...] = ("fr", "en", "both")


def _parse_known(value: str | None) -> Language | None:
    """Return the matching :class:`Language` for a code, or ``None``."""
    if not value:
        return None
    candidate = value.strip().lower()
    for lang in Language:
        if lang.value == candidate:
            return lang
    return None


def resolve_language(
    query_param: str | None = None,
    accept_language: str | None = None,
    default: Language = DEFAULT_LANGUAGE,
) -> Language:
    """Resolve the content language for a request.

    Priority: explicit query param > ``Accept-Language`` header > ``default``.
    Unknown / malformed values fall through to ``default`` (fail-safe, never
    raises). Query param beats the header (explicit user choice > browser).
    """
    parsed = _parse_known(query_param)
    if parsed is not None:
        return parsed

    if accept_language:
        # RFC 7231: "fr-CA,fr;q=0.9,en;q=0.8" -> first recognised primary tag.
        for part in accept_language.split(","):
            tag = part.split(";", 1)[0].strip().lower()
            primary = tag.split("-", 1)[0]
            parsed = _parse_known(primary)
            if parsed is not None:
                return parsed

    return default


def expand_languages(language_arg: str) -> list[Language]:
    """Expand a pipeline-agent ``--language`` value into the languages to run.

    ``both`` → ``[FR, EN]`` — **FR first**: translated rows (e.g. the EN
    ``pl_indicator_daily`` row) copy the FR row, so the FR run must complete
    first. A single known language returns just that one; anything unknown
    falls back to ``[DEFAULT_LANGUAGE]`` (fail-safe, never raises).
    """
    if language_arg == "both":
        return [Language.FR, Language.EN]
    parsed = _parse_known(language_arg)
    return [parsed] if parsed is not None else [DEFAULT_LANGUAGE]
