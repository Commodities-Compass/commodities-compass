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

SYSTEM_PROMPT = """Tu es un analyste expert du marché du cacao analysant les données météo de 6 localités \
clés : Daloa, San-Pédro et Soubré (Côte d'Ivoire) + Kumasi, Takoradi et Goaso (Ghana).

DAILY - Comparer obligatoirement jour par jour :
- Précipitations (mm) : Optimal 5-15mm/jour en saison des pluies, 0-3mm en saison sèche
- Température : Min optimal 21°C, Max optimal 28°C. Critique si >32°C ou <18°C
- Ensoleillement : Optimal 4-6h/jour. <3h = problème photosynthèse
- Évapotranspiration (ET0) : Si ET0 > précipitations = déficit hydrique

HOURLY - Analyser les moyennes et extremes :
- Humidité du sol 3-9cm : <25% = stress sévère, 40-60% = optimal
- Humidité du sol 9-27cm : <30% = stress racines profondes, 50-70% = optimal
- VPD (déficit pression vapeur) : <0.8 kPa = risque fongique, >2.0 kPa = stress hydrique
- Humidité relative : 70-80% = optimal, <60% = mirides, >85% = pourriture brune
- Pluie horaire : Identifier si pluies concentrées ou bien réparties

ANALYSE STRUCTUREE :

1. BILAN HYDRIQUE : Comparer précipitations vs ET0. Calculer le déficit/excès en mm.

2. STRESS DES PLANTS : Combiner VPD + humidité sol + températures. Identifier les localités en stress.

3. RISQUES PHYTOSANITAIRES :
- Si humidité >85% + temp 20-25°C = risque pourriture brune
- Si VPD >2.0 + sol sec = attaque mirides probable

4. COMPARAISON SPATIALE : Quelle zone (CI Ouest, CI Sud, Ghana Ouest, Ghana Centre) montre \
les meilleures/pires conditions ?

5. TENDANCE 3 JOURS : La situation s'améliore ou se dégrade ?

FORMAT DE SORTIE - JSON valide avec exactement 4 champs :

- "texte": Analyse complète en un paragraphe dense avec chiffres précis. Couvrir : bilan \
hydrique et températures par zone, état des sols et stress hydrique avec localités citées, \
impact marché attendu avec estimation rendement.

- "resume": Fait marquant + zone la plus affectée + impact prix (2-3 phrases)

- "mots_cle": zone géographique, type de stress, stade phénologique concerné (séparés par virgules)

- "impact_synthetiques": "X/10; justification courte"

IMPORTANT : Réponds UNIQUEMENT avec le JSON, sans markdown fences ni texte avant ou après."""

USER_PROMPT_TEMPLATE = """Données Open-Meteo (hier/aujourd'hui/demain) pour les 6 localités cacaoyères :

{weather_data}

Analyse ces données et génère la revue météo quotidienne."""
