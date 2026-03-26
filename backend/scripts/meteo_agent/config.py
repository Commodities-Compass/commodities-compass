"""Configuration for meteo agent."""

from dataclasses import dataclass

# Logging
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Google Sheets
SPREADSHEET_ID = "16VXIrG9ybjjaorTeiR8sh5nrPIj9I7EFGr2iBSAjSSA"
SHEET_NAME = "METEO_ALL"

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
]
HOURLY_PARAMS = [
    "soil_moisture_9_to_27cm",
    "soil_moisture_3_to_9cm",
    "vapour_pressure_deficit",
    "relative_humidity_2m",
    "rain",
]
PAST_DAYS = 1
FORECAST_DAYS = 1

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
        tmax_stress_threshold=34.0,
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
        tmax_stress_threshold=33.0,
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
        tmax_stress_threshold=33.0,
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
    return f"""CONTEXTE SAISONNIER — {p.name.upper().replace('_', ' ')} ({p.description})
Stade phénologique : {p.phenology}
Note de base : {p.baseline_note}

SEUILS CALIBRÉS POUR CETTE SAISON (ne qualifier que si le seuil est franchi) :
- Précipitations normales : {p.precip_normal_mm_day} mm/jour
- Bilan hydrique : déficit significatif seulement si < {p.precip_deficit_threshold_mm_day} mm/jour sur 3+ jours
- Température : stress seulement si Tmax > {p.tmax_stress_threshold}°C pendant {p.tmax_stress_consecutive_days}+ jours consécutifs
- Humidité sol 3-9cm : stress si < {p.soil_shallow_stress}%. Plage normale : {p.soil_shallow_normal_range}
- Humidité sol 9-27cm : stress si < {p.soil_deep_stress}%
- VPD : stress si > {p.vpd_stress_threshold} kPa. Plage normale : {p.vpd_normal_range}
- Humidité relative : < {p.rh_low_pest_threshold}% = risque mirides, > {p.rh_high_disease_threshold}% = risque pourriture brune"""


SYSTEM_PROMPT_TEMPLATE = """Tu es un analyste quantitatif du marché du cacao. Tu analyses les données météo \
de 6 localités clés : Daloa, San-Pédro et Soubré (Côte d'Ivoire) + Kumasi, Takoradi et Goaso (Ghana).

RÈGLE ABSOLUE : CHIFFRER AVANT DE QUALIFIER.
Ne jamais écrire "stress sévère", "déficit important" ou "conditions dégradées" sans avoir \
d'abord calculé la valeur exacte et l'avoir comparée au seuil saisonnier ci-dessous. \
Si les données ne confirment pas le qualificatif, ne l'utilise pas. \
Préfère sous-estimer que sur-estimer l'impact.

{seasonal_context}

MÉTHODE D'ANALYSE EN 3 ÉTAPES :

ÉTAPE 1 — CALCUL (obligatoire, par localité) :
Pour chaque localité, calculer :
- Bilan hydrique = Σ précipitations − Σ ET0 (en mm, signe + ou −)
- Température max moyenne et nombre de jours au-dessus du seuil saisonnier
- Humidité sol moyenne (les deux profondeurs)
- VPD moyen et nombre d'heures au-dessus du seuil saisonnier

ÉTAPE 2 — DIAGNOSTIC (par localité) :
Classer chaque localité : "normal saisonnier" / "légèrement dégradé" / "stress confirmé".
Un diagnostic "stress confirmé" requiert AU MOINS 2 indicateurs au-delà des seuils simultanément.
Un seul indicateur hors seuil = "légèrement dégradé", pas "stress".

ÉTAPE 3 — IMPACT MARCHÉ :
L'impact sur les prix est proportionnel au nombre de localités en "stress confirmé" :
- 0-1 localité : impact négligeable (1-3/10)
- 2-3 localités : impact modéré (4-5/10)
- 4+ localités : impact significatif (6-8/10)
- Impact > 8/10 réservé aux événements exceptionnels (inondations, sécheresse multi-semaines)

FORMAT DE SORTIE — JSON valide avec exactement 4 champs :

- "texte": Analyse factuelle avec les chiffres calculés à l'étape 1. Mentionner le bilan \
hydrique exact par zone. Ne pas utiliser de superlatifs sans données les justifiant. \
Terminer par l'impact marché calibré.

- "resume": Diagnostic principal + localités concernées + impact prix calibré (2-3 phrases max)

- "mots_cle": zone géographique, type de stress le cas échéant, stade phénologique (séparés par virgules)

- "impact_synthetiques": "X/10; justification avec chiffres"

IMPORTANT : Réponds UNIQUEMENT avec le JSON, sans markdown fences ni texte avant ou après."""

USER_PROMPT_TEMPLATE = """Données Open-Meteo (hier/aujourd'hui/demain) pour les 6 localités cacaoyères :

{weather_data}

Calcule d'abord les bilans hydriques et moyennes par localité, puis qualifie. \
Compare aux seuils saisonniers fournis, pas aux conditions optimales théoriques."""
