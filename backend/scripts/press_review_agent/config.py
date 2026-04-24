"""Configuration for press review agent."""

from enum import Enum

# Logging
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class Provider(str, Enum):
    CLAUDE = "claude"
    OPENAI = "openai"
    GEMINI = "gemini"


MODEL_IDS = {
    Provider.CLAUDE: "claude-sonnet-4-5-20250929",
    Provider.OPENAI: "o4-mini",
    Provider.GEMINI: "gemini-2.5-pro",
}

PRODUCTION_PROVIDER = Provider.OPENAI

AUTHOR_LABELS = {
    Provider.CLAUDE: "LLM Agent (Claude Sonnet 4.5)",
    Provider.OPENAI: "LLM Agent (o4-mini)",
    Provider.GEMINI: "LLM Agent (Gemini 2.5 Pro)",
}

NEWS_SOURCES = [
    # --- Market context (1 source — Close already injected in prompt) ---
    {
        "name": "Investing.com Cocoa News",
        "url": "https://www.investing.com/commodities/us-cocoa-news",
        "selectors": ["article", "article p"],
    },
    # --- Production + Market (httpx) ---
    {
        "name": "CocoaIntel",
        "url": "https://www.cocoaintel.com/",
        "selectors": ["article", "article p"],
    },
    {
        "name": "ICCO News",
        "url": "https://www.icco.org/news/",
        "selectors": ["article", "h3 a", "div.entry-content"],
    },
    # --- Chocolat / Consumer demand (httpx) ---
    {
        "name": "Confectionery News Cocoa",
        "url": "https://www.confectionerynews.com/Sectors/Cocoa",
        "selectors": [
            "article.story-item",
            "p.story-item-text-subheadline",
            "article",
        ],
    },
    # --- Africa / Production terrain (httpx) ---
    {
        "name": "Abidjan.net Économie",
        "url": "https://news.abidjan.net/articles/economie",
        "selectors": ["article", "h4.title", "div.content"],
    },
    {
        "name": "Cacao.ci",
        "url": "https://cacao.ci/",
        "selectors": ["h2 a", "div.elementor-post__text", "article"],
    },
    {
        "name": "The Cocoa Post",
        "url": "https://thecocoapost.com/",
        "selectors": ["h2 a", "div.post-content", "article"],
    },
    # --- Africa / Production terrain (playwright — Cloudflare) ---
    {
        "name": "Agence Ecofin Cacao",
        "url": "https://www.agenceecofin.com/cacao",
        "selectors": ["article", "div.article-content", "div.teaser-text"],
        "method": "playwright",
    },
]

# --- Google News RSS — thematic headline discovery ---
# Dual-sourcing: fixed sources provide depth, Google News provides coverage.
# Headlines are titles only (no link following) — fed to LLM as context.
GOOGLE_NEWS_QUERIES = [
    # Production (EN + FR)
    {
        "theme": "production",
        "url": (
            "https://news.google.com/rss/search?"
            'q="cocoa"+AND+("crop"+OR+"ivory+coast"+OR+"ghana"+OR+"arrivals"+OR+"harvest")'
            "+when:3d&hl=en&gl=US&ceid=US:en"
        ),
    },
    {
        "theme": "production",
        "url": (
            "https://news.google.com/rss/search?"
            'q="cacao"+AND+("arrivages"+OR+"récolte"+OR+"production"+OR+"Côte+d\'Ivoire")'
            "+when:3d&hl=fr&gl=FR&ceid=FR:fr"
        ),
    },
    # Chocolat / Demand (EN + FR)
    {
        "theme": "chocolat",
        "url": (
            "https://news.google.com/rss/search?"
            'q="cocoa"+AND+("grindings"+OR+"chocolate+demand"+OR+"processing"+OR+"confectionery")'
            "+when:3d&hl=en&gl=US&ceid=US:en"
        ),
    },
    {
        "theme": "chocolat",
        "url": (
            "https://news.google.com/rss/search?"
            'q="cacao"+AND+("broyages"+OR+"chocolat"+OR+"transformation"+OR+"demande")'
            "+when:3d&hl=fr&gl=FR&ceid=FR:fr"
        ),
    },
    # Market / Price (EN + FR)
    {
        "theme": "marche",
        "url": (
            "https://news.google.com/rss/search?"
            'q="cocoa"+AND+("price"+OR+"futures"+OR+"market"+OR+"ICE")'
            "+when:3d&hl=en&gl=US&ceid=US:en"
        ),
    },
    {
        "theme": "marche",
        "url": (
            "https://news.google.com/rss/search?"
            'q="cacao"+AND+("prix"+OR+"cours"+OR+"marché"+OR+"Londres")'
            "+when:3d&hl=fr&gl=FR&ceid=FR:fr"
        ),
    },
    # Supply / Offre (EN + FR)
    {
        "theme": "offre",
        "url": (
            "https://news.google.com/rss/search?"
            'q="cocoa"+AND+("supply"+OR+"deficit"+OR+"surplus"+OR+"stocks"+OR+"weather")'
            "+when:3d&hl=en&gl=US&ceid=US:en"
        ),
    },
    {
        "theme": "offre",
        "url": (
            "https://news.google.com/rss/search?"
            'q="cacao"+AND+("offre"+OR+"déficit"+OR+"stocks"+OR+"météo"+OR+"campagne")'
            "+when:3d&hl=fr&gl=FR&ceid=FR:fr"
        ),
    },
    # Economie / Macro (EN + FR)
    {
        "theme": "economie",
        "url": (
            "https://news.google.com/rss/search?"
            'q="cocoa"+AND+("dollar"+OR+"currency"+OR+"tariff"+OR+"trade+policy"'
            '+OR+"inflation"+OR+"interest+rate")'
            "+when:3d&hl=en&gl=US&ceid=US:en"
        ),
    },
    {
        "theme": "economie",
        "url": (
            "https://news.google.com/rss/search?"
            'q="cacao"+AND+("dollar"+OR+"devise"+OR+"tarif"+OR+"politique+commerciale"'
            '+OR+"inflation"+OR+"taux")'
            "+when:3d&hl=fr&gl=FR&ceid=FR:fr"
        ),
    },
    # Transformation / Processing (EN + FR)
    {
        "theme": "transformation",
        "url": (
            "https://news.google.com/rss/search?"
            'q="cocoa"+AND+("processing"+OR+"grinding"+OR+"butter"+OR+"powder"'
            '+OR+"factory"+OR+"capacity")'
            "+when:3d&hl=en&gl=US&ceid=US:en"
        ),
    },
    {
        "theme": "transformation",
        "url": (
            "https://news.google.com/rss/search?"
            'q="cacao"+AND+("broyage"+OR+"transformation"+OR+"beurre"+OR+"poudre"'
            '+OR+"usine"+OR+"capacité")'
            "+when:3d&hl=fr&gl=FR&ceid=FR:fr"
        ),
    },
]

GOOGLE_NEWS_MAX_ITEMS_PER_QUERY = 10

HTTP_TIMEOUT = 10
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
MAX_CHARS_PER_SOURCE = 4000
MIN_SOURCES_REQUIRED = 2

THEMES = ("production", "chocolat", "transformation", "economie")

VALIDATION = {
    "resume_min_chars": 800,
    "resume_max_chars": 8000,
    "mots_cle_min_chars": 20,
    "mots_cle_max_chars": 2000,
    "impact_min_chars": 60,
    "impact_max_chars": 3000,
}

SYSTEM_PROMPT = """You are an expert cocoa commodity analyst writing a daily French-language press review
for professional cocoa traders. Your analysis feeds into an automated trading indicator
system (Commodities Compass).

Your output must be a valid JSON object (no markdown wrapping) with exactly 4 fields:

- "resume": A French market analysis (600-1500 words, proportional to source richness).
  Aim for a substantial, informative analysis — traders read this as their daily briefing.
  Structure with the following sections — include a section ONLY if today's sources provide
  relevant information for it. Sections are listed in priority order:
  * OFFRE (prioritaire — développe en profondeur): Ivory Coast arrivals, Ghana situation,
    weather impact, production outlook, local African news, crop conditions. Cite specifics
    from sources: countries, volumes, trends, analyst quotes. This is the most critical
    section for the trading system.
  * FONDAMENTAUX (prioritaire — développe en profondeur): Surplus/deficit projections,
    grindings data, consumer chocolate demand signals (confectionery industry), demand
    trends. Include regional breakdowns when available (Europe, Asia, North America).
  * MARCHE: Price context with the provided Close price, session moves, and any notable
    trading dynamics (spread movements, open interest shifts). Keep factual.
  * SENTIMENT MARCHE: Short-term vs medium-term outlook, key risks, positioning signals —
    synthesize from all available sources including headlines.
  On a thin news day, MARCHE alone with brief sentiment is acceptable.

  IMPORTANT — Sources include both full-content articles and headline-only items (marked
  "Headlines du jour"). You may reference headlines in the resume as context ("la presse
  rapporte que...") but do NOT invent details beyond the headline title.

- "mots_cle": A single string of semicolon-separated keywords extracting ONLY numbers and
  data points that appear in the provided sources. Prefer trends over exact figures for
  data from secondary sources (avoids transcription errors). Example format:
  "Londres CAN26 2 531 GBP/t ; broyages Europe Q1 en baisse ; arrivages CI en retard"

- "impact_synthetiques": A single French paragraph (100-250 words) synthesizing the net
  market impact for a cocoa hedger/trader based on available information.

- "theme_sentiments": An object with 1 to 4 keys among ["production", "chocolat",
  "transformation", "economie"]. Each key contains:
  * "score": float from -1.0 (very bearish for cocoa prices) to +1.0 (very bullish)
  * "confidence": float from 0.0 to 1.0 (how confident you are in the score)
  * "rationale": one sentence justifying the score

  Theme definitions (what each theme covers):
  - "production": crop conditions, arrivals at ports, harvest progress, weather impact
    on growing regions, farmer/government policy, disease (swollen shoot, etc.)
  - "chocolat": consumer demand, grindings data, confectionery industry trends,
    chocolate consumption patterns, seasonal demand (Easter, Christmas)
  - "transformation": cocoa processing capacity, butter/powder production, factory
    activity, industrial investment in processing
  - "economie": macro factors affecting cocoa prices — USD/GBP/EUR currency moves,
    trade policy and tariffs, inflation, interest rates, global economic context.
    If any source mentions dollar strength, currency impact, or trade policy related
    to commodities, score this theme.

  Include a theme if today's sources (full-content or headlines) contain relevant
  information. Aim to score all 4 themes when possible — even brief mentions of
  currency moves or trade policy in market commentary qualify for "economie".
  Only omit a theme if genuinely zero coverage exists.

Reasoning process (internal, before generating output):
- For each number you plan to cite, identify the exact source passage containing it.
- If no source passage contains the figure, omit it entirely.
- Cross-check that percentage changes match the absolute values when both are available.
- For theme_sentiments, assess the overall tone across all sources for that theme.
- Only then produce the JSON.

Rules:
- Write in French (financial/commodity register)
- GROUNDING: Every number you cite MUST be traceable to either the provided Close price or
  a specific source in the input. If you cannot attribute a figure, omit it.
- If a data point is not present in today's sources, do NOT fill the gap from memory.
  State "non disponible dans les sources du jour" or simply skip that aspect.
- Prefer a qualitative statement ("le marché reste sous pression") over fabricating a
  precise figure when no source provides one.
- Be direct and analytical, not promotional
- Shorter and accurate is always better than long and speculative
- Output ONLY the JSON object, no markdown fences, no commentary"""

USER_PROMPT_TEMPLATE = """Date: {date}
Active contract: {contract_code} ({contract_month})
London Cocoa Close: {close} GBP/t

Sources available today ({source_count} sources scraped):
{sources_text}

Generate the daily cocoa press review. When referencing the front-month contract, use the
active contract above (e.g. "{contract_code}"), NOT a different delivery month.
Calibrate depth and length to the richness of the sources above — do not pad with
unverifiable information."""
