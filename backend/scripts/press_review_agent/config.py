"""Configuration for press review agent."""

from enum import Enum

# Logging
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Google Sheets
SPREADSHEET_ID = "16VXIrG9ybjjaorTeiR8sh5nrPIj9I7EFGr2iBSAjSSA"
TECHNICALS_SHEET = "TECHNICALS"
CLOSE_COLUMN_INDEX = 1  # Column B (0-based)


class Provider(str, Enum):
    CLAUDE = "claude"
    OPENAI = "openai"
    GEMINI = "gemini"


SHEET_NAMES: dict[str, dict[Provider, str]] = {
    "staging": {
        Provider.CLAUDE: "BIBLIO_ALL_STAGING_CLAUDE",
        Provider.OPENAI: "BIBLIO_ALL_STAGING_OPENAI",
        Provider.GEMINI: "BIBLIO_ALL_STAGING_GEMINI",
    },
    "production": {
        Provider.CLAUDE: "BIBLIO_ALL_STAGING_CLAUDE",
        Provider.OPENAI: "BIBLIO_ALL",
        Provider.GEMINI: "BIBLIO_ALL_STAGING_GEMINI",
    },
}

MODEL_IDS = {
    Provider.CLAUDE: "claude-sonnet-4-5-20250929",
    Provider.OPENAI: "gpt-4.1",
    Provider.GEMINI: "gemini-2.5-pro",
}

AUTHOR_LABELS = {
    Provider.CLAUDE: "LLM Agent (Claude Sonnet 4.5)",
    Provider.OPENAI: "LLM Agent (GPT-4.1)",
    Provider.GEMINI: "LLM Agent (Gemini 2.5 Pro)",
}

NEWS_SOURCES = [
    {
        "name": "Barchart Cocoa News",
        "url": "https://www.barchart.com/futures/quotes/CA*0/news",
        "selectors": ["article", "div.news-article", "div.bc-news-body"],
    },
    {
        "name": "Investing.com Cocoa News",
        "url": "https://www.investing.com/commodities/us-cocoa-news",
        "selectors": ["article", "article p"],
    },
    {
        "name": "Nasdaq Cocoa",
        "url": "https://www.nasdaq.com/market-activity/commodities/cj:nmx",
        "selectors": ["article", "div.commodity-article", "main"],
    },
    {
        "name": "CocoaIntel",
        "url": "https://www.cocoaintel.com/",
        "selectors": ["article", "article p"],
    },
    {
        "name": "MarketScreener Cocoa",
        "url": "https://www.marketscreener.com/quote/commodity/COCOA-2298/news/",
        "selectors": ["article", "div.txt", "div.news-block"],
    },
    {
        "name": "ICCO News",
        "url": "https://www.icco.org/news/",
        "selectors": ["article", "h3 a", "div.entry-content"],
    },
]

HTTP_TIMEOUT = 10
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
MAX_CHARS_PER_SOURCE = 2000
MIN_SOURCES_REQUIRED = 2

VALIDATION = {
    "resume_min_chars": 200,
    "resume_max_chars": 8000,
    "mots_cle_min_chars": 20,
    "mots_cle_max_chars": 2000,
    "impact_min_chars": 60,
    "impact_max_chars": 3000,
}

SYSTEM_PROMPT = """You are an expert cocoa commodity analyst writing a daily French-language press review
for professional cocoa traders. Your analysis feeds into an automated trading indicator
system (Commodities Compass).

Your output must be a valid JSON object (no markdown wrapping) with exactly 3 fields:

- "resume": A French market analysis (400-1200 words, proportional to source richness).
  Structure with the following sections — include a section ONLY if today's sources provide
  relevant information for it:
  * MARCHE (always include): Today's price action on London (ICE) and New York using the
    provided Close price and any price data found in sources
  * FONDAMENTAUX: Surplus/deficit projections, grindings data, demand trends — only if
    mentioned in today's sources
  * OFFRE: Ivory Coast arrivals, Ghana situation, weather impact, production outlook — only
    if mentioned in today's sources
  * SENTIMENT MARCHE: Short-term vs medium-term outlook, key risks — synthesize only from
    signals present in sources
  On a thin news day, MARCHE alone with brief sentiment is acceptable.

- "mots_cle": A single string of semicolon-separated keywords extracting ONLY numbers and
  data points that appear in the provided sources. Can be short if few data points are
  available. Example format:
  "Londres CAH26 2 750 GBP/t (-7%) ; New York 3 797 $/t (-7,44%) ; surplus 2025/26 287 kt"

- "impact_synthetiques": A single French paragraph (100-250 words) synthesizing the net
  market impact for a cocoa hedger/trader based on available information.

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
London Cocoa Close: {close} GBP/t

Sources available today ({source_count} sources scraped):
{sources_text}

Generate the daily cocoa press review. Calibrate depth and length to the richness of the
sources above — do not pad with unverifiable information."""
