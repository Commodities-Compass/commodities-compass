"""Configuration for meteo agent."""

from dataclasses import dataclass

# Logging
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# LLM
MODEL_ID = "gpt-4.1"
MAX_TOKENS = 4096


@dataclass(frozen=True)
class Location:
    name: str
    country: str
    latitude: float
    longitude: float


LOCATIONS: tuple[Location, ...] = (
    Location("Daloa", "Côte d'Ivoire", 6.877, -6.45),
    Location("San-Pédro", "Côte d'Ivoire", 4.748, -6.636),
    Location("Soubré", "Côte d'Ivoire", 5.785, -6.606),
    Location("Kumasi", "Ghana", 6.688, -1.624),
    Location("Takoradi", "Ghana", 4.885, -1.745),
    Location("Goaso", "Ghana", 6.8, -2.52),
)

# Open-Meteo API parameters
DAILY_PARAMS = [
    "precipitation_sum",
    "et0_fao_evapotranspiration",
    "sunshine_duration",
    "temperature_2m_max",
    "temperature_2m_min",
    "winddirection_10m_dominant",
]

# Harmattan detection thresholds (literature: ICCO, CRIG, WMO West Africa)
# Harmattan = dry NE trade wind from Sahara, Nov–Mar, West Africa cocoa belt
HARMATTAN_RH_THRESHOLD = 55.0  # daily min RH < 55% = Harmattan influence (40% was too strict for forest zone)
HARMATTAN_WIND_DIR_MIN = 315.0  # NE/N quadrant: 315°→360° and 0°→90°
HARMATTAN_WIND_DIR_MAX = 90.0
HARMATTAN_IMPACT_DAYS = 24  # cumulative days > 24 → quality risk
HARMATTAN_SEASON_MONTHS = (11, 12, 1, 2, 3)  # Nov–Mar
HOURLY_PARAMS = [
    "soil_moisture_9_to_27cm",
    "soil_moisture_3_to_9cm",
    "vapour_pressure_deficit",
    "relative_humidity_2m",
    "rain",
]
PAST_DAYS = 1
# Forward horizon = today + 5 days, matched to the brief's J+4-J+5 decision
# window. The agent re-runs daily, so a short rolling forecast (not 10-16d) is
# the right trade-off: enough to anticipate incoming rain/heat, refreshed daily.
FORECAST_DAYS = 6

# HTTP
HTTP_TIMEOUT = 30

# Validation thresholds
VALIDATION = {
    "texte_min_chars": 200,
    "texte_max_chars": 8000,
    "resume_min_chars": 50,
    "resume_max_chars": 2000,
    "mots_cle_min_chars": 10,
    "mots_cle_max_chars": 500,
    "impact_min_chars": 30,
    "impact_max_chars": 2000,
}

# --- Excess-water detection (symmetric counterpart to drought/Harmattan) ---
# Excess rain only harms the crop when pods are on the tree in a humid window
# (black pod / pourriture brune). In the dry season a positive water balance is
# drought RELIEF, not a stressor — so excess penalties are gated to these seasons.
# Asymmetry by design: deficit is penalized everywhere, surplus only here.
RAINY_SEASONS: frozenset[str] = frozenset(
    {"transition_pluies", "grande_saison_pluies", "petite_saison_pluies"}
)
# A day with > HEAVY_RAIN_MM_DAY of precipitation is "saturating" — conducive to
# black pod, nutrient leaching and harvest disruption when it persists. This is
# the excess-water analogue of a Harmattan day (acute, count-based).
HEAVY_RAIN_MM_DAY = 20.0
# Cumulative heavy-rain days in a rainy season → disease risk (mirror of
# HARMATTAN_IMPACT_DAYS). Tiers applied in compute_score: 12/8/5 → -1.5/-1.0/-0.5.
HEAVY_RAIN_IMPACT_DAYS = 12

# --- Seasonal profiles for West Africa cocoa belt ---
# Source: ICCO, CRIG (Cocoa Research Institute of Ghana), CNRA (Côte d'Ivoire)
# Bimodal rainfall: long rains Apr-Jul, short rains Sep-Nov, dry Dec-Mar


@dataclass(frozen=True)
class SeasonalProfile:
    """Thresholds and context for a given season."""

    name: str
    months: tuple[int, ...]
    description: str
    # Phenological stage
    phenology: str
    # Precipitation expectations
    precip_normal_mm_day: str  # e.g. "0-3" or "5-15"
    precip_deficit_threshold_mm_day: float  # deficit below this = significant
    # Temperature
    tmax_stress_threshold: float
    tmax_stress_consecutive_days: int
    # Soil moisture (%)
    soil_shallow_stress: float  # 3-9cm
    soil_deep_stress: float  # 9-27cm
    soil_shallow_normal_range: str
    # VPD (kPa)
    vpd_stress_threshold: float
    vpd_normal_range: str
    # Humidity (%)
    rh_low_pest_threshold: float  # mirides
    rh_high_disease_threshold: float  # pourriture brune
    # Baseline impact (how much does weather matter this season?)
    baseline_note: str


SEASONAL_PROFILES: tuple[SeasonalProfile, ...] = (
    SeasonalProfile(
        name="saison_seche",
        months=(12, 1, 2, 3),
        description="Saison sèche (Harmattan). Fin de récolte principale (main crop). "
        "Déficit hydrique modéré est NORMAL. Les arbres sont en dormance relative. "
        "Stress thermique et vent sec sont les vrais risques, pas le manque de pluie.",
        phenology="dormance / fin récolte principale",
        precip_normal_mm_day="0-3",
        precip_deficit_threshold_mm_day=-5.0,
        # 32°C aligned with cocoa physiology literature (Ahenkorah, Daymond & Hadley,
        # CRIG, ICCO) — photosynthesis inhibition threshold. Previously 34°C masked
        # most of the 2024-2025 Harmattan heat stress on the inland belt.
        tmax_stress_threshold=32.0,
        tmax_stress_consecutive_days=3,
        soil_shallow_stress=15.0,
        soil_deep_stress=20.0,
        soil_shallow_normal_range="15-35%",
        vpd_stress_threshold=2.5,
        vpd_normal_range="1.0-2.5 kPa",
        rh_low_pest_threshold=50.0,
        rh_high_disease_threshold=90.0,
        baseline_note="Impact météo limité — arbres en dormance, récolte terminée ou en fin",
    ),
    SeasonalProfile(
        name="transition_pluies",
        months=(4,),
        description="Transition vers grande saison des pluies. Reprise végétative, "
        "floraison et nouaison en cours. Sensibilité croissante au stress hydrique. "
        "Les premières pluies sont critiques pour la nouaison.",
        phenology="floraison / nouaison (début mid-crop)",
        precip_normal_mm_day="3-8",
        precip_deficit_threshold_mm_day=-3.0,
        tmax_stress_threshold=32.0,
        tmax_stress_consecutive_days=3,
        soil_shallow_stress=20.0,
        soil_deep_stress=25.0,
        soil_shallow_normal_range="25-50%",
        vpd_stress_threshold=2.0,
        vpd_normal_range="0.8-2.0 kPa",
        rh_low_pest_threshold=55.0,
        rh_high_disease_threshold=88.0,
        baseline_note="Impact météo ÉLEVÉ — floraison très sensible au stress hydrique",
    ),
    SeasonalProfile(
        name="grande_saison_pluies",
        months=(5, 6, 7),
        description="Grande saison des pluies. Développement des chérelles (jeunes cabosses). "
        "Risque principal = excès d'eau (pourriture brune, black pod). "
        "Un déficit est ANORMAL et préoccupant à cette période.",
        phenology="développement chérelles / mid-crop",
        precip_normal_mm_day="5-15",
        precip_deficit_threshold_mm_day=-2.0,
        tmax_stress_threshold=32.0,
        tmax_stress_consecutive_days=2,
        soil_shallow_stress=25.0,
        soil_deep_stress=30.0,
        soil_shallow_normal_range="40-65%",
        vpd_stress_threshold=1.8,
        vpd_normal_range="0.5-1.5 kPa",
        rh_low_pest_threshold=60.0,
        rh_high_disease_threshold=85.0,
        baseline_note="Impact météo CRITIQUE — chérelles très vulnérables, excès et déficit tous deux dangereux",
    ),
    SeasonalProfile(
        name="petite_saison_seche",
        months=(8,),
        description="Petite saison sèche. Maturation des cabosses mid-crop. "
        "Pause pluviométrique normale. Stress modéré toléré par les cabosses en maturation.",
        phenology="maturation mid-crop",
        precip_normal_mm_day="2-6",
        precip_deficit_threshold_mm_day=-4.0,
        tmax_stress_threshold=32.0,
        tmax_stress_consecutive_days=3,
        soil_shallow_stress=20.0,
        soil_deep_stress=25.0,
        soil_shallow_normal_range="25-45%",
        vpd_stress_threshold=2.2,
        vpd_normal_range="0.8-2.0 kPa",
        rh_low_pest_threshold=55.0,
        rh_high_disease_threshold=88.0,
        baseline_note="Impact météo modéré — cabosses en maturation tolèrent mieux le stress",
    ),
    SeasonalProfile(
        name="petite_saison_pluies",
        months=(9, 10, 11),
        description="Petite saison des pluies. Récolte mid-crop + floraison pour main crop. "
        "Période critique : excès d'humidité = black pod sur cabosses mûres, "
        "déficit = mauvaise floraison pour la récolte principale à venir.",
        phenology="récolte mid-crop + floraison main crop",
        precip_normal_mm_day="4-12",
        precip_deficit_threshold_mm_day=-2.5,
        tmax_stress_threshold=32.0,
        tmax_stress_consecutive_days=2,
        soil_shallow_stress=25.0,
        soil_deep_stress=30.0,
        soil_shallow_normal_range="35-60%",
        vpd_stress_threshold=1.8,
        vpd_normal_range="0.5-1.5 kPa",
        rh_low_pest_threshold=58.0,
        rh_high_disease_threshold=85.0,
        baseline_note="Impact météo ÉLEVÉ — double enjeu récolte en cours + floraison prochaine campagne",
    ),
)


def get_seasonal_profile(month: int) -> SeasonalProfile:
    """Return the seasonal profile for a given month (1-12)."""
    for profile in SEASONAL_PROFILES:
        if month in profile.months:
            return profile
    return SEASONAL_PROFILES[0]  # fallback to dry season


def build_seasonal_context(month: int) -> str:
    """Build the seasonal context block for the system prompt."""
    p = get_seasonal_profile(month)
    # Symmetric framing: in rainy seasons excess water is a real stressor (black
    # pod), so the prompt must let the LLM qualify surplus, not just deficit.
    excess_line = ""
    if p.name in RAINY_SEASONS:
        excess_line = (
            f"\n- Excès hydrique (saison des pluies) : surplus significatif si "
            f"bilan > +3 mm/jour sur la saison, ou > {HEAVY_RAIN_IMPACT_DAYS} jours "
            f"de pluies intenses (>{HEAVY_RAIN_MM_DAY:.0f}mm/jour) → risque pourriture "
            f"brune / black pod. Excès et déficit sont tous deux pénalisants ici."
        )
    return f"""CONTEXTE SAISONNIER — {p.name.upper().replace("_", " ")} ({p.description})
Stade phénologique : {p.phenology}
Note de base : {p.baseline_note}

SEUILS CALIBRÉS POUR CETTE SAISON (ne qualifier que si le seuil est franchi) :
- Précipitations normales : {p.precip_normal_mm_day} mm/jour
- Bilan hydrique : déficit significatif seulement si < {p.precip_deficit_threshold_mm_day} mm/jour sur 3+ jours{excess_line}
- Température : stress seulement si Tmax > {p.tmax_stress_threshold}°C pendant {p.tmax_stress_consecutive_days}+ jours consécutifs
- Humidité sol 3-9cm : stress si < {p.soil_shallow_stress}%. Plage normale : {p.soil_shallow_normal_range}
- Humidité sol 9-27cm : stress si < {p.soil_deep_stress}%
- VPD : stress si > {p.vpd_stress_threshold} kPa. Plage normale : {p.vpd_normal_range}
- Humidité relative : < {p.rh_low_pest_threshold}% = risque mirides, > {p.rh_high_disease_threshold}% = risque pourriture brune"""


# --- English (Ghana edition) seasonal prose --------------------------------
# The numeric thresholds stay in SeasonalProfile (single source of truth, shared
# by both languages); only the language-specific prose (name / description /
# phenology / baseline) is authored natively in English here, keyed by profile
# name. Native English — NOT a literal translation of the FR strings.
_SEASONAL_PROSE_EN: dict[str, dict[str, str]] = {
    "saison_seche": {
        "name_en": "DRY SEASON",
        "description": (
            "Dry season (Harmattan). End of the main crop. A moderate water "
            "deficit is NORMAL — the trees are in relative dormancy. Heat stress "
            "and dry wind are the real risks, not the lack of rain."
        ),
        "phenology": "dormancy / end of main crop",
        "baseline_note": "Limited weather impact — trees dormant, harvest finished or ending",
    },
    "transition_pluies": {
        "name_en": "RAINY-SEASON TRANSITION",
        "description": (
            "Transition into the main rainy season. Vegetative recovery, "
            "flowering and pod-set under way. Growing sensitivity to water "
            "stress. The first rains are critical for pod-set."
        ),
        "phenology": "flowering / pod-set (early mid-crop)",
        "baseline_note": "HIGH weather impact — flowering is very sensitive to water stress",
    },
    "grande_saison_pluies": {
        "name_en": "MAIN RAINY SEASON",
        "description": (
            "Main rainy season. Cherelle (young pod) development. Primary risk = "
            "excess water (brown pod, black pod). A deficit is ABNORMAL and "
            "concerning at this stage."
        ),
        "phenology": "cherelle development / mid-crop",
        "baseline_note": "CRITICAL weather impact — cherelles very vulnerable, both excess and deficit dangerous",
    },
    "petite_saison_seche": {
        "name_en": "SHORT DRY SEASON",
        "description": (
            "Short dry season. Mid-crop pod maturation. A normal rainfall pause. "
            "Moderate stress is tolerated by the maturing pods."
        ),
        "phenology": "mid-crop maturation",
        "baseline_note": "Moderate weather impact — maturing pods tolerate stress better",
    },
    "petite_saison_pluies": {
        "name_en": "SHORT RAINY SEASON",
        "description": (
            "Short rainy season. Mid-crop harvest + flowering for the main crop. "
            "Critical window: excess humidity = black pod on ripe pods, deficit = "
            "poor flowering for the coming main crop."
        ),
        "phenology": "mid-crop harvest + main-crop flowering",
        "baseline_note": "HIGH weather impact — dual stake: harvest under way + next campaign's flowering",
    },
}


def build_seasonal_context_en(month: int) -> str:
    """English (Ghana) counterpart of :func:`build_seasonal_context`.

    Reuses the numeric thresholds from :class:`SeasonalProfile`; the season
    prose comes from the native-English lookup above.
    """
    p = get_seasonal_profile(month)
    prose = _SEASONAL_PROSE_EN.get(p.name, _SEASONAL_PROSE_EN["saison_seche"])
    excess_line = ""
    if p.name in RAINY_SEASONS:
        excess_line = (
            f"\n- Water surplus (rainy season): significant if the balance "
            f"exceeds +3 mm/day over the season, or more than {HEAVY_RAIN_IMPACT_DAYS} "
            f"days of intense rain (>{HEAVY_RAIN_MM_DAY:.0f}mm/day) → brown pod / "
            f"black pod risk. Both surplus and deficit are penalising here."
        )
    return f"""SEASONAL CONTEXT — {prose["name_en"]} ({prose["description"]})
Phenological stage: {prose["phenology"]}
Baseline note: {prose["baseline_note"]}

THRESHOLDS CALIBRATED FOR THIS SEASON (only qualify if the threshold is crossed):
- Normal precipitation: {p.precip_normal_mm_day} mm/day
- Water balance: significant deficit only if < {p.precip_deficit_threshold_mm_day} mm/day over 3+ days{excess_line}
- Temperature: stress only if Tmax > {p.tmax_stress_threshold}°C for {p.tmax_stress_consecutive_days}+ consecutive days
- Soil moisture 3-9cm: stress if < {p.soil_shallow_stress}%. Normal range: {p.soil_shallow_normal_range}
- Soil moisture 9-27cm: stress if < {p.soil_deep_stress}%
- VPD: stress if > {p.vpd_stress_threshold} kPa. Normal range: {p.vpd_normal_range}
- Relative humidity: < {p.rh_low_pest_threshold}% = mirid risk, > {p.rh_high_disease_threshold}% = brown pod risk"""


SYSTEM_PROMPT_TEMPLATE = """Tu es un analyste quantitatif du marché du cacao. Tu analyses les données météo \
de 6 localités clés : Daloa, San-Pédro et Soubré (Côte d'Ivoire) + Kumasi, Takoradi et Goaso (Ghana).

RÈGLE ABSOLUE : CHIFFRER AVANT DE QUALIFIER.
Ne jamais écrire "stress sévère", "déficit important" ou "conditions dégradées" sans avoir \
d'abord calculé la valeur exacte et l'avoir comparée au seuil saisonnier ci-dessous. \
Si les données ne confirment pas le qualificatif, ne l'utilise pas.

SYMÉTRIE DÉFICIT / EXCÈS : l'EXCÈS d'eau est un stress au même titre que le déficit. \
En saison des pluies, un excès généralisé (bilans hydriques largement positifs, journées de \
pluie intense, humidité relative élevée) = risque de POURRITURE BRUNE / black pod sur les \
cabosses : il doit être chiffré et signalé, jamais minimisé en "rien à signaler". \
Préfère sous-estimer un bruit ponctuel, mais NE SOUS-ESTIME PAS un risque prospectif confirmé \
par les prévisions (excès persistant en saison des pluies, ou sécheresse/chaleur persistante).

{seasonal_context}

Deux blocs de contexte peuvent suivre les données dans le message : le RÉGIME CLIMATIQUE ENSO \
(El Niño / La Niña, biais de fond) et la PRÉVISION J+1→J+5 (synthèse). Utilise-les.

MÉTHODE D'ANALYSE EN 4 ÉTAPES :

ÉTAPE 1 — CALCUL (obligatoire, par localité) :
Pour chaque localité, calculer :
- Bilan hydrique = Σ précipitations − Σ ET0 (en mm, signe + ou −)
- Température max moyenne et nombre de jours au-dessus du seuil saisonnier
- Humidité sol moyenne (les deux profondeurs)
- VPD moyen et nombre d'heures au-dessus du seuil saisonnier

ÉTAPE 2 — DIAGNOSTIC CONDITIONS ACTUELLES (par localité) :
Classer chaque localité : "normal saisonnier" / "légèrement dégradé" / "stress confirmé".
Un "stress confirmé" requiert AU MOINS 2 indicateurs au-delà des seuils simultanément — \
côté DÉFICIT (bilan négatif, sol sec, VPD élevé, Harmattan) OU côté EXCÈS (en saison des \
pluies : bilan fortement positif au-delà du seuil d'excès + pluies intenses, ou humidité \
relative > seuil pourriture brune). Un seul indicateur hors seuil = "légèrement dégradé".

ÉTAPE 3 — RISQUE À L'HORIZON J+1→J+5 (prévisions) :
À partir de la portion PRÉVISION des séries (et de la synthèse fournie), identifier le risque \
DOMINANT à venir et l'orienter avec le RÉGIME ENSO :
- Saison des pluies + prévision humide (ou régime La Niña) → risque pourriture brune / black \
  pod CROISSANT, et perturbation logistique portuaire si pluies extrêmes.
- Saison sèche / régime El Niño + prévision sèche-chaude → risque déficit hydrique / Harmattan \
  / stress thermique CROISSANT.
Le risque prospectif s'énonce même si les conditions actuelles sont "normales" : l'horizon de \
décision est 4-5 sessions, pas seulement aujourd'hui.

ÉTAPE 4 — IMPACT MARCHÉ (actuel + prospectif) :
Impact de base = proportionnel au nombre de localités en "stress confirmé" aujourd'hui :
- 0-1 localité : 1-3/10 — 2-3 localités : 4-5/10 — 4+ localités : 6-8/10.
PUIS ajuster pour le risque à l'horizon (ÉTAPE 3) :
- Excès généralisé (toutes zones au moins "légèrement dégradé" côté humide) en saison des \
  pluies AVEC prévision confirmant la poursuite des pluies → NE PAS plafonner à "négligeable" : \
  viser 4-6/10 (canal pourriture brune + logistique portuaire).
- Prévision sèche-chaude persistante en régime El Niño → relever de 1-2 points.
- > 8/10 réservé aux événements exceptionnels (inondations, sécheresse multi-semaines).
Toujours justifier l'impact par des chiffres (actuels ET prévus).

FORMAT DE SORTIE — JSON valide avec exactement 5 champs :

- "texte": Analyse NARRATIVE et fluide, rédigée comme un bulletin météo professionnel — \
PAS une liste par localité. Regrouper les zones par situation similaire, comparer entre pays \
(Côte d'Ivoire vs Ghana), mentionner les tendances spatiales. Intégrer les chiffres clés \
(bilans hydriques, températures, humidité sol) dans le fil du texte, pas en tableau. \
Utiliser des connecteurs ("tandis que", "en revanche", "spatialement"). \
Le texte doit être compréhensible par un trader non météorologue. \
Situer le RÉGIME ENSO en contexte de fond (une phrase, avec le mois de référence — donnée \
décalée) PUIS énoncer le RISQUE À L'HORIZON J+1→J+5, et terminer par la conséquence marché \
calibrée. Ne pas utiliser de superlatifs sans données les justifiant. \
FORMATAGE HUMIDITÉ DU SOL : exprimer UNIQUEMENT en pourcentage (ex: "25%"), \
jamais en m³/m³. Ne pas écrire les deux formats — le % suffit.

- "resume": Diagnostic actuel + risque à l'horizon J+1→J+5 + impact prix calibré (2-3 phrases max)

- "mots_cle": zone géographique, type de stress (déficit ou excès) le cas échéant, régime ENSO, stade phénologique (séparés par virgules)

- "impact_synthetiques": "X/10; justification avec chiffres ACTUELS et PRÉVUS"

- "diagnostics": Objet avec une clé par localité et le diagnostic de l'étape 2 comme valeur. \
Valeurs possibles UNIQUEMENT : "normal", "degraded", "stress". \
Exemple : {{"Daloa": "normal", "San-Pédro": "degraded", "Kumasi": "stress", "Soubré": "normal", "Takoradi": "degraded", "Goaso": "normal"}}

IMPORTANT : Réponds UNIQUEMENT avec le JSON, sans markdown fences ni texte avant ou après."""

USER_PROMPT_TEMPLATE = """Données Open-Meteo — fenêtre J-1 → J+5 (observation récente + prévisions) pour les 6 localités cacaoyères :

{weather_data}

Distingue bien la portion OBSERVÉE (J-1/J) de la portion PRÉVUE (J+1→J+5) des séries. \
Calcule d'abord les bilans hydriques et moyennes par localité, puis qualifie les conditions \
actuelles, puis évalue le risque à l'horizon à partir des prévisions. \
Compare aux seuils saisonniers fournis, pas aux conditions optimales théoriques."""


# --- English (Ghana) edition prompts ---------------------------------------
# Native English generation for the Ghana cocoa-trader audience — NOT a literal
# translation of the FR prompt. Same 4-step method, same output contract: the
# JSON KEYS stay French (texte / resume / mots_cle / impact_synthetiques /
# diagnostics — the parser + db_writer depend on them) and the diagnostics enum
# values stay ("normal" / "degraded" / "stress"); only the prose VALUES are
# English. Ghana zones (Kumasi, Takoradi, Goaso) are framed first.
SYSTEM_PROMPT_TEMPLATE_EN = """You are a quantitative cocoa-market analyst writing for West-African (Ghana) \
cocoa exporters and traders. You analyse weather data for 6 key locations: Kumasi, Takoradi and \
Goaso (Ghana) + Daloa, San-Pédro and Soubré (Côte d'Ivoire).

ABSOLUTE RULE: QUANTIFY BEFORE YOU QUALIFY.
Never write "severe stress", "significant deficit" or "degraded conditions" without first \
computing the exact value and comparing it to the seasonal threshold below. \
If the data do not confirm the qualifier, do not use it.

DEFICIT / SURPLUS SYMMETRY: EXCESS water is a stressor, just like deficit. \
In the rainy seasons a widespread surplus (strongly positive water balances, intense-rain days, \
high relative humidity) = BROWN POD / black pod risk on the pods: it must be quantified and \
flagged, never dismissed as "nothing to report". Prefer to under-state a one-off noise, but DO \
NOT under-state a prospective risk confirmed by the forecast (persistent surplus in the rainy \
seasons, or persistent drought/heat).

{seasonal_context}

Some context blocks may follow the data in the message: campaign memory, the ENSO CLIMATE \
REGIME (El Niño / La Niña, background bias) and the J+1→J+5 FORECAST synthesis. THESE BLOCKS MAY \
BE WRITTEN IN FRENCH — read them for their figures and their signal, but write your ENTIRE output \
in English. Use them.

FOUR-STEP ANALYSIS METHOD:

STEP 1 — COMPUTE (mandatory, per location):
For each location, compute:
- Water balance = Σ precipitation − Σ ET0 (in mm, + or − sign)
- Mean max temperature and the number of days above the seasonal threshold
- Mean soil moisture (both depths)
- Mean VPD and the number of hours above the seasonal threshold

STEP 2 — DIAGNOSE CURRENT CONDITIONS (per location):
Classify each location: "normal for the season" / "slightly degraded" / "confirmed stress".
A "confirmed stress" requires AT LEAST 2 indicators past their thresholds at once — on the \
DEFICIT side (negative balance, dry soil, high VPD, Harmattan) OR the SURPLUS side (in the rainy \
seasons: strongly positive balance beyond the surplus threshold + intense rain, or relative \
humidity > brown-pod threshold). A single indicator past threshold = "slightly degraded".

STEP 3 — RISK AT THE J+1→J+5 HORIZON (forecast):
From the FORECAST portion of the series (and the synthesis provided), identify the DOMINANT \
risk ahead and orient it with the ENSO REGIME:
- Rainy season + wet forecast (or La Niña regime) → RISING brown pod / black pod risk, plus port \
  logistics disruption if the rain is extreme.
- Dry season / El Niño regime + dry-hot forecast → RISING water-deficit / Harmattan / heat-stress risk.
State the prospective risk even when current conditions are "normal": the decision horizon is \
4-5 sessions, not just today.

STEP 4 — MARKET IMPACT (current + prospective):
Base impact = proportional to the number of locations in "confirmed stress" today:
- 0-1 location: 1-3/10 — 2-3 locations: 4-5/10 — 4+ locations: 6-8/10.
THEN adjust for the horizon risk (STEP 3):
- Widespread surplus (all zones at least "slightly degraded" on the wet side) in a rainy season \
  WITH a forecast confirming the rain continues → DO NOT cap at "negligible": aim for 4-6/10 \
  (brown-pod channel + port logistics).
- Persistent dry-hot forecast in an El Niño regime → raise by 1-2 points.
- > 8/10 is reserved for exceptional events (flooding, multi-week drought).
Always justify the impact with figures (current AND forecast).

OUTPUT FORMAT — valid JSON with exactly 5 fields (keep these exact French field names):

- "texte": a NARRATIVE, flowing analysis written like a professional weather bulletin — NOT a \
per-location list. Group zones by similar situation, compare across countries (Ghana vs Côte \
d'Ivoire), note spatial trends. Weave the key figures (water balances, temperatures, soil \
moisture) into the flow of the text, not into a table. Use connectors ("while", "by contrast", \
"spatially"). The text must be understandable by a non-meteorologist trader. Put the ENSO REGIME \
in the background (one sentence, with the reference month — lagged data) THEN state the J+1→J+5 \
RISK, and close with the calibrated market consequence. Do not use superlatives without data to \
back them. SOIL-MOISTURE FORMATTING: express it ONLY as a percentage (e.g. "25%"), never as \
m³/m³. Do not write both formats — the % alone is enough.

- "resume": current diagnosis + J+1→J+5 risk + calibrated price impact (2-3 sentences max)

- "mots_cle": geographic zone, stress type (deficit or surplus where relevant), ENSO regime, phenological stage (comma-separated)

- "impact_synthetiques": "X/10; justification with CURRENT and FORECAST figures"

- "diagnostics": an object with one key per location and the STEP-2 diagnosis as the value. \
Allowed values ONLY: "normal", "degraded", "stress". \
Example: {{"Kumasi": "normal", "Takoradi": "degraded", "Goaso": "stress", "Daloa": "normal", "San-Pédro": "degraded", "Soubré": "normal"}}

IMPORTANT: reply ONLY with the JSON, no markdown fences and no text before or after."""

USER_PROMPT_TEMPLATE_EN = """Open-Meteo data — J-1 → J+5 window (recent observation + forecast) for the 6 cocoa locations:

{weather_data}

Clearly separate the OBSERVED portion (J-1/J) from the FORECAST portion (J+1→J+5) of the series. \
First compute the water balances and per-location means, then qualify the current conditions, \
then assess the horizon risk from the forecast. Compare against the seasonal thresholds provided, \
not against theoretical optimal conditions."""
