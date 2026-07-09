# Jobs & Scrapers — Catalogue exhaustif

> Inventaire complet des **jobs Cloud Run** et **schedulers** du pipeline Compass Cocoa. Pour chaque job : description, source, cron, output, quel(s) pipeline(s) le consomme, statut (actif / déprécié / out-of-scope), et tolérance de scraping. Document indépendant — peut être lu seul pour comprendre la photographie complète.

> **Périmètre** : 20 jobs Cloud Run actifs aujourd'hui + 17 schedulers + 2 jobs candidats. Voir aussi [PIPELINE_LEGACY.md](./PIPELINE_LEGACY.md) et [PIPELINE_ENSEMBLE.md](./PIPELINE_ENSEMBLE.md) pour le contexte business.

---

## 1 — Vue d'ensemble : timeline UTC weekdays

```
Time UTC | Job                                   | Track       | Type
─────────┼───────────────────────────────────────┼─────────────┼──────────────────
13:00    | cc-eca-grindings-scraper              | shared      | Calendar-gated quarterly
14:00    | cc-nca-grindings-scraper              | shared      | Calendar-gated quarterly
16:00    | cc-publication-calendar-watchdog      | shared      | Daily safety watchdog
18:30    | cc-fx-scraper                         | shared      | Phase A (FX, ECB daily)
19:00    | cc-barchart-scraper                   | shared      | Phase A (OHLCV+IV)
19:00    | cc-meteo-agent                        | both        | Phase B (eve-gated)
19:05    | cc-ice-stocks-scraper                 | shared      | Phase A (STOCK US)
19:05    | cc-cftc-scraper                       | shared      | Phase A (COM NET US)
19:05    | cc-press-review-agent                 | both        | Phase B (eve-gated)
19:10    | cc-barchart-stocks-eu-scraper         | shared      | Phase A (stock_eu)
19:15    | cc-compute-indicators                 | shared      | Phase A (engine)
19:18    | cc-ensemble-compute                   | ENSEMBLE    | Phase B (eve-gated, ML decision)
19:20    | cc-daily-analysis                     | LEGACY      | Phase B (eve-gated, LLM)
19:25    | cc-ensemble-explainer                 | ENSEMBLE    | Phase B (eve-gated, LLM)
19:30    | cc-compass-brief                      | LEGACY      | Phase B (eve-gated, Drive)
19:35    | cc-compass-brief-ensemble             | ENSEMBLE    | Phase B (eve-gated, Drive)
20:00-09 | cc-publish-session (×/30 window)      | both        | Publication gate → dashboard flip
22:10    | cc-ice-cot-eu-scraper                 | ENSEMBLE-only| Phase A (weekly snapshot)
─────────┼───────────────────────────────────────┼─────────────┼──────────────────
Monthly  | cc-enso-scraper                       | ENSEMBLE-only| 20 of month at 22:00 UTC
On-demand| cc-ensemble-bootstrap-artifacts       | ENSEMBLE     | Manual (no scheduler)
```

**Légende du Track** :
- `shared` : alimente les 2 pipelines (legacy + ensemble)
- `LEGACY` : exclusif au pipeline legacy
- `ENSEMBLE` : exclusif au pipeline ensemble
- `both` : Phase B agents qui écrivent pour les 2 tracks (le brief consume)

**Légende du Type** :
- `Phase A` : Market close (weekdays, sur session T)
- `Phase B` : Eve of next trading day (daily cron + agent gate `is_eve_of_trading_day()`)
- `Calendar-gated quarterly` : Daily cron, agent gate sur `ref_publication_calendar`
- `Daily safety watchdog` : Daily cron, agent alerte si publications en retard
- `Publication gate` : Cron `*/30` fenêtre soir→matin, release une séance quand data + audio prêts → flip atomique du dashboard (repli data-only le lendemain 09:00 UTC)

---

## 2 — Catalogue master (tableau)

| Job | Cron UTC | Track | Input source | Output table | Statut |
|---|---|---|---|---|---|
| **cc-barchart-scraper** | `0 19 * * 1-5` | shared | Barchart.com HTML/XHR (CAK26) | `pl_contract_data_daily` (OHLCV+IV) | ✅ Actif |
| **cc-ice-stocks-scraper** | `5 19 * * 1-5` | shared | ICE public XLS report | `pl_stock_observation` (region='us', tonnes) | ✅ Actif (refactor 2026-05-27) |
| **cc-cftc-scraper** | `5 19 * * 1-5` | shared | CFTC.gov HTML | `pl_cot_us_weekly` (Disaggregated COT — long/short/MM) | ✅ Actif (refactor 2026-05-27) |
| **cc-barchart-stocks-eu-scraper** | `10 19 * * 1-5` | shared | Barchart cmdty page | `pl_stock_observation` (region='eu', bags_60kg + tonnes) | ✅ Actif (refactor 2026-05-27) |
| **cc-ice-cot-eu-scraper** | `10 22 * * 1-5` | ENSEMBLE-only | ICE public CSV `COTHistYYYY.csv` | `pl_cot_eu_weekly` | ✅ Actif |
| **cc-fx-scraper** | `30 18 * * 1-5` | shared | ECB SDMX 2.1 CSV | `pl_external_indicator.fx_*` | ✅ Actif |
| **cc-enso-scraper** | `0 22 20 * *` | ENSEMBLE-only | NOAA PSL ASCII | `pl_external_indicator.enso_*` | ✅ Actif (monthly) |
| **cc-eca-grindings-scraper** | `0 13 * * 1-5` | shared | eurococoa.com listing + PDFs | `pl_supply_demand_observation` (ECA rows) | ✅ Actif (gated) |
| **cc-nca-grindings-scraper** | `0 14 * * 1-5` | shared | candyusa.com listing + PDFs | `pl_supply_demand_observation` (NCA rows) | ✅ Actif (gated) |
| **cc-publication-calendar-watchdog** | `0 16 * * 1-5` | shared | `ref_publication_calendar` query | Sentry capture (no DB write) | ✅ Actif |
| **cc-press-review-agent** | `5 19 * * *` | both | 6 news sources + Google News RSS | `pl_fundamental_article`, `pl_article_segment`, `pl_sentiment_feature` | ✅ Actif (P2b daily-gated) |
| **cc-meteo-agent** | `0 19 * * *` | both | Open-Meteo API | `pl_weather_observation`, `pl_seasonal_score` | ✅ Actif (P2b daily-gated) |
| **cc-compute-indicators** | `15 19 * * 1-5` | shared | `pl_contract_data_daily` | `pl_derived_indicators`, `pl_indicator_daily` (numerics) | ✅ Actif |
| **cc-ensemble-compute** | `18 19 * * *` (eve-gated) | ENSEMBLE | `pl_derived_indicators`, `pl_article_segment`, `pl_external_indicator`, `pl_cot_eu_weekly`, `pl_model_artifact` | `pl_specialist_prediction` (14), `pl_orchestrator_decision`, `pl_indicator_daily` (ensemble row partielle) | ✅ Actif |
| **cc-ensemble-explainer** | `25 19 * * *` | ENSEMBLE | `pl_orchestrator_decision`, `pl_specialist_prediction`, `pl_fundamental_article`, `pl_weather_observation`, `pl_contract_data_daily` | UPDATE `pl_indicator_daily` ensemble row (narrative legacy-style via DBAnalysisEngine auto-align) | ✅ Actif (P2b daily-gated, thin wrapper sur le moteur legacy depuis 2026-05-27) |
| **cc-daily-analysis** | `20 19 * * *` | LEGACY | `pl_contract_data_daily`, `pl_derived_indicators`, `pl_indicator_daily`, `pl_fundamental_article`, `pl_weather_observation` | UPDATE `pl_indicator_daily` legacy row (LLM) | ✅ Actif (P2b daily-gated, `--algorithm-version legacy`) |
| **cc-compass-brief** | `30 19 * * *` | LEGACY | `pl_indicator_daily` (active row), `pl_contract_data_daily` last 2 dates, `pl_fundamental_article`, `pl_weather_observation` | Drive: `YYYYMMDD-CompassBrief.txt` | ✅ Actif (P2b daily-gated) |
| **cc-compass-brief-ensemble** | `35 19 * * *` | ENSEMBLE | Ensemble row + orchestrator + 14 specialists + press + meteo + technicals | Drive: `YYYYMMDD-CompassBrief-Ensemble.txt` | 🆕 P4 (2026-05) |
| **cc-publish-session** | `*/30 20-23,0-9 * * *` | both | `pl_indicator_daily` + `pl_fundamental_article` + `pl_weather_observation` + Drive audio | `pl_session_release` (1 row / séance publiée) | 🆕 (2026-07) |
| **cc-ensemble-bootstrap-artifacts** | (manual) | ENSEMBLE | R&D frozen artifact pack | `pl_model_artifact` BYTEA rows | ✅ Actif (no scheduler) |

---

## 3 — Section par job

### 3.1 `cc-barchart-scraper`

> Code : [backend/scripts/barchart_scraper/](../../backend/scripts/barchart_scraper/)

**Track** : shared (legacy + ensemble lisent ses outputs)

**Description fonctionnelle** : scrape les OHLCV (Open, High, Low, Close, Volume, Open Interest, Implied Volatility) du contrat actif (CAK26, London Cocoa #7, ICE Europe) depuis Barchart.com. Source primaire des données de marché.

**Source** : `https://www.barchart.com/futures/quotes/{contract}/overview` + `/{contract}/volatility-greeks`. Playwright browser + parsing JSON inline + XHR API en backup.

**Cron** : `0 19 * * 1-5` (19:00 UTC weekdays)

**Output** : `pl_contract_data_daily` row pour le `(date, contract_id)` avec close, high, low, volume, oi, implied_volatility. `display_date = next_trading_day(date)` calculé via la trading calendar.

**Tolérance / latence** : Barchart publie ~16:00 UTC. 3h de marge avant notre run. Pas de retry — fail-loud.

**Failure recovery** : [docs/runbooks/pipeline-failure-recovery.md](../runbooks/pipeline-failure-recovery.md) scenario A. Manuel : `gcloud run jobs execute cc-barchart-scraper`.

**Known issues** : voir CLAUDE.md "Known Issues & Lessons" — bugs résolus 2026-02-18 sur la sélection du raw block + rolling de contrat CA*0.

### 3.2 `cc-ice-stocks-scraper`

> Code : [backend/scripts/ice_stocks_scraper/](../../backend/scripts/ice_stocks_scraper/)

**Track** : shared

**Description** : scrape le rapport certified cocoa stocks dans les warehouses ICE US (en tonnes, depuis le format XLS bags × 70/1000).

**Source** : `https://www.ice.com/publicdocs/futures_us_reports/cocoa/cocoa_cert_stock_YYYYMMDD.xls`. Pure httpx + pandas, no browser.

**Cron** : `5 19 * * 1-5`

**Output** (refactor 2026-05-27) : UPSERT `pl_stock_observation` keyed on `(region='us', report_date, contract_market='cocoa')`. `report_date` = la date écrite dans le XLS par ICE (PAS aujourd'hui). Walks back jusqu'à 60 business days si le rapport du jour n'existe pas (variantes `a`-suffix), et l'`actual_date` du fichier trouvé est ce qui est stocké. Tag `source='ice_us_report41'`.

**Avant la migration r2m3n4o5p6q7** : écrivait sur `pl_contract_data_daily.stock_us` keyed on session date (today), ce qui perdait le vrai report_date.

### 3.3 `cc-cftc-scraper`

> Code : [backend/scripts/cftc_scraper/](../../backend/scripts/cftc_scraper/)

**Track** : shared

**Description** (refactor 2026-05-27) : scrape le **Disaggregated COT report** CFTC pour cocoa (ICE Futures U.S.). Extrait désormais Open Interest, Producer/Merchant L/S, Swap L/S/Spread, **Managed Money L/S/Spread** (parité avec ICE EU), Other Reportables L/S, Non-Reportable L/S — au lieu du seul net Producer/Merchant.

**Source** : `https://www.cftc.gov/dea/futures/ag_lf.htm`. Pure httpx + regex, no browser. Idempotent — re-run safe.

**Date extraction** : header `Disaggregated Commitments of Traders - Futures Only, <Month> <Day>, <Year>` → `report_date` (Tuesday). `release_date = report_date + 3 days` (CFTC publication convention). Fail-loud si le report a plus de 14 jours (publisher freeze détecté).

**Cron** : `5 19 * * 1-5`. Nouvelle data uniquement les vendredis ~21:30 CET (publication officielle).

**Output** : UPSERT `pl_cot_us_weekly` keyed on `(release_date, contract_market='cocoa')`. `prod_merc_net` et `m_money_net` sont des colonnes Postgres GENERATED.

**Avant la migration r2m3n4o5p6q7** : UPDATE `pl_contract_data_daily.com_net_us` (juste le net Producer/Merchant, écrasé chaque weekday).

### 3.4 `cc-barchart-stocks-eu-scraper`

> Code : [backend/scripts/barchart_stocks_eu_scraper/](../../backend/scripts/barchart_stocks_eu_scraper/)

**Track** : shared (lu par ensemble specialists FX cluster)

**Description** : scrape les certified cocoa stocks ICE Europe (60kg bags) depuis Barchart cmdty page. ICE Europe publie chaque mardi midi GMT.

**Source** : `https://www.barchart.com/cmdty/data/fundamental/explore/IC345DRW.CS`. Pure httpx + BeautifulSoup. Validate native unit `60 Kg Bag` + multiplier 1 — fail-loud si drift.

**Cron** : `10 19 * * 1-5`

**Output** (refactor 2026-05-27) : UPSERT `pl_stock_observation` keyed on `(region='eu', report_date, contract_market='cocoa')`. `report_date` = `Most Recent Date` parsé sur la page Barchart (= mardi de publication ICE EU). Stocke `value_native` en `bags_60kg` + `value_tonnes` (calcul × 60 / 1000 fait par le shared writer). Tag `source='barchart_ic345drw'`.

**Drift detection** : si `obs.date > 14 jours`, log ERROR + Sentry alert — Barchart ou ICE EU a probablement arrêté de publier.

**Avant la migration r2m3n4o5p6q7** : UPDATE `pl_contract_data_daily.stock_eu_bags60kg` keyed on session date, écrasait la même valeur lun-ven jusqu'au mardi suivant. Dépendait d'une row OHLCV pré-existante (fail-loud `StockEuRowMissingError`) — désormais auto-suffisant, plus de couplage à OHLCV.

### 3.5 `cc-ice-cot-eu-scraper`

> Code : [backend/scripts/ice_cot_eu_scraper/](../../backend/scripts/ice_cot_eu_scraper/)

**Track** : ENSEMBLE-only (3 features Managed Money + Producer/Merchant z-scores 26w consommées par specialists FX cluster)

**Description** : scrape le COT Europe (ICE) weekly report. Décomposition Producer/Merchant, Managed Money, Other Reportables, Non-Reportable + OI.

**Source** : `https://www.theice.com/publicdocs/futures/COTHist{YYYY}.csv` (1 fichier par année calendaire, ~175 colonnes, UTF-8 BOM). Pure httpx + stdlib csv.

**Cron** : `10 22 * * 1-5` (22:10 UTC weekdays). ICE publie vendredi ~21:30 CET pour le snapshot mardi précédent.

**Output** : `pl_cot_eu_weekly` (1 row par release_date). Net columns `prod_merc_net`, `m_money_net` sont GENERATED columns Postgres.

**Note** : daily cron + UPSERT idempotent → catches late publishes sans coupler le cron à l'heure exacte ICE.

### 3.6 `cc-fx-scraper`

> Code : [backend/scripts/fx_scraper/](../../backend/scripts/fx_scraper/)

**Track** : shared (9/14 ensemble specialists + legacy LLM Call #1 indirectement)

**Description** : scrape les taux de change ECB SDMX 2.1 (USD/EUR + GBP/EUR), calcule 4 colonnes dérivées (`fx_dxy_proxy`, `fx_gbpusd`, `fx_eurusd`, `fx_gbpeur`).

**Source** : `https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?format=csvdata` + `D.GBP.EUR.SP00.A`. Pure httpx + stdlib csv.

**Cron** : `30 18 * * 1-5` (18:30 UTC). ECB publie ~16:00 CET business days. 30min de marge.

**Output** : `pl_external_indicator` (partial UPSERT — préserve les colonnes ENSO).

**Backfill** : `poetry run fx-scraper-backfill --verify` importe `docs/onboarding/FX/{dxy_proxy,gbpusd}_daily.csv` (~3164 rows, 2014-2026).

### 3.7 `cc-enso-scraper`

> Code : [backend/scripts/enso_scraper/](../../backend/scripts/enso_scraper/)

**Track** : ENSEMBLE-only (6/14 specialists du cluster Spring — notamment `exp_optim_011` top scorer)

**Description** : scrape les climatology features NOAA PSL (Oceanic Niño Index + Niño 3.4 anomaly mensuelle).

**Source** : `https://psl.noaa.gov/data/correlation/oni.data` + `nina34.anom.data`. Pure httpx + stdlib parser (PSL ASCII).

**Cron** : `0 22 20 * *` (le 20 de chaque mois, 22:00 UTC). NOAA publie mid-month pour le mois précédent.

**Output** : `pl_external_indicator` (partial UPSERT — préserve FX columns).

**Lag policy** : 14 jours, appliqué au compute-time par l'engine (`pd.merge_asof(direction="backward")`), pas par le scraper.

**Backfill** : `poetry run enso-scraper-backfill --verify` → ~1830 rows (1950-2026).

### 3.8 `cc-eca-grindings-scraper`

> Code : [backend/scripts/eca_grindings_scraper/](../../backend/scripts/eca_grindings_scraper/)

**Track** : shared (peut alimenter brief ensemble section future « Supply/Demand »)

**Description** : scrape les broyages Western Europe trimestriels (ECA, 19 firmes, ~40% mondial). 2 metrics : volume_tonnes + yoy_pct.

**Source** : listing `https://www.eurococoa.com/grind-stats/` → PDFs (URL inconsistante, scraping listing nécessaire). 7 ans d'archives.

**Cron** : `0 13 * * 1-5`. ECA publie jeudis ~14:00 CET.

**Calendar-gated** : query `ref_publication_calendar` au démarrage. Si aucune publi ECA n'est attendue dans ±14j → exit 0. Daily cron donc cheap (~250 no-ops/an).

**Output** : `pl_supply_demand_observation` rows ECA (volume_tonnes + yoy_pct par trimestre) + UPDATE `ref_publication_calendar.actual_publication_date`.

### 3.9 `cc-nca-grindings-scraper`

> Code : [backend/scripts/nca_grindings_scraper/](../../backend/scripts/nca_grindings_scraper/)

**Track** : shared

**Description** : scrape les broyages North America trimestriels (NCA, ~13 plants, supplied to ICE Futures US).

**Source** : listing `https://candyusa.com/cocoa-grinds-report/` → PDFs hébergés sur candyusa.com (filenames inconsistants). 5 ans d'archives. On cible candyusa.com directement (l'ancien host `chocolatecouncil.org` redirige et est derrière un WAF anti-bot SiteGround qui challenge par intermittence les IP Cloud Run — Sentry 2026-07-02).

**Cron** : `0 14 * * 1-5`. NCA publie ~mid-day ET.

**Calendar-gated** : même pattern qu'ECA.

**Output** : `pl_supply_demand_observation` rows NCA. yoy_pct calculé en parser depuis current/prior volumes (robuste à 2 formats de delta).

### 3.10 `cc-publication-calendar-watchdog`

> Code : [backend/scripts/publication_calendar_watchdog/](../../backend/scripts/publication_calendar_watchdog/)

**Track** : shared (safety net pour les scrapers gated)

**Description** : query daily `ref_publication_calendar` pour les rows where `actual_publication_date IS NULL` ET `expected_publication_date < today - 21j`. Log ERROR + Sentry capture + exit non-zero.

**Cron** : `0 16 * * 1-5`.

**Pourquoi** : ECA/NCA scrapers exit 0 quand pas de publi attendue → indistinguable d'un « silence publisher » du point de vue Sentry. Le watchdog rend la silence visible.

### 3.11 `cc-press-review-agent`

> Code : [backend/scripts/press_review_agent/](../../backend/scripts/press_review_agent/)

**Track** : both (legacy LLM Call #1 lit `pl_fundamental_article` + ensemble specialists lisent `pl_article_segment` via MacroEventLayer)

**Description** : agent LLM qui consomme 6 sources news + RSS Google News, produit une revue de presse en français + extrait des sentiment features structurés.

**Source** : 6 sources spécialisées cocoa + 8 RSS Google News queries. OpenAI `o4-mini` (production provider, autres providers `gpt-4-turbo` + Claude + Gemini disponibles pour tests).

**Cron** : `5 19 * * *` (P2b daily-gated). Écrit pour `target_date = next_session_date()`.

**Output** :
- `pl_fundamental_article` (1 row par jour avec `is_active=true` pour le provider production)
- `pl_article_segment` (~4 rows par jour, 1 par thème : production / chocolat / transformation / economie)
- `pl_sentiment_feature` (shadow mode, ~4 rows par jour)

### 3.12 `cc-meteo-agent`

> Code : [backend/scripts/meteo_agent/](../../backend/scripts/meteo_agent/)

**Track** : both (legacy LLM Call #1 + ensemble brief section V Weather Watch)

**Description** : fetch weather data Open-Meteo pour 6 cocoa locations (Ghana + Côte d'Ivoire), produit une analyse française via OpenAI gpt-4.1.

**Source** : Open-Meteo API. Free, no auth.

**Cron** : `0 19 * * *` (P2b daily-gated). 6 locations : Daloa, San-Pédro, Soubré, Kumasi, Takoradi, Goaso.

**Output** :
- `pl_weather_observation` (1 row par jour avec summary + impact_assessment + per-location status JSON)
- `pl_seasonal_score` (campaign memory, mise à jour quotidienne)

### 3.13 `cc-compute-indicators`

> Code : [backend/app/engine/](../../backend/app/engine/)

**Track** : shared (alimente legacy decision engine ET ensemble specialists via `pl_derived_indicators`)

**Description** : engine déterministe qui calcule 27 indicators dérivés (RSI Wilder, MACD, Stochastic, Bollinger, ATR, EMA, pivots, ratios) + 5j SMA smoothing + 252j rolling z-scores + composite power formula score.

**Source** : `pl_contract_data_daily` (lookback 252+ jours par contrat).

**Cron** : `15 19 * * 1-5`.

**Output** :
- `pl_derived_indicators` (27 colonnes par date × contract)
- `pl_indicator_daily` (z-scores + final_indicator par date × contract × algorithm_version_id)

**Note importante** : tourne pour TOUTES les versions `compute_enabled=TRUE` (aujourd'hui : legacy v1.0.1 + ensemble v1.0.0). Donc remplit 2 rows par date dans `pl_indicator_daily`.

### 3.14 `cc-ensemble-compute`

> Code : [backend/scripts/ensemble_compute/](../../backend/scripts/ensemble_compute/)

**Track** : ENSEMBLE-only

**Description** : pipeline ML qui charge 38 artifacts BYTEA depuis `pl_model_artifact`, infère 14 specialists, soft-gate Bayésien combine, Compass wrapper applique 4 détecteurs → décision finale.

**Source** :
- `v_contract_data_chained` VIEW (front-month-by-OI cross-contract pour GARCH lookback 600d)
- `pl_derived_indicators` 600d
- `pl_orchestrator_decision` lookback 10d + `pl_specialist_prediction` 10d (rolling)
- `pl_article_segment` 90d (confidence ≥0.70) via MacroEventLayer
- `pl_external_indicator` (ENSO + FX) + `pl_cot_eu_weekly`

**Cron** : `18 19 * * *` (P2b daily, eve-of-trading gate ; 13min après cc-press-review-agent à 19:05 pour lire les `pl_article_segment` fraîchement écrits). Fire Mon-Thu eve + Sunday eve, skip Friday + Saturday eves. Sur Sunday eve, écrit la row pour `data_date = Friday` avec le MacroSignal incluant les news du weekend.

**Output** :
- 14× `pl_specialist_prediction` (specialist_name, pred, window_months)
- 1× `pl_orchestrator_decision` (25+ diagnostics : soft_gate_decision, decision_wrapped, wrapper_active, 4 fired_*, running_acc_5d, anomaly_score_z, etc.)
- 1× `pl_indicator_daily` ENSEMBLE row UPSERT (decision + conclusion auto-generated). `eco`, `confidence`, `direction` restent NULL — enrichies plus tard par `cc-ensemble-explainer`.

**Note** : `pl_algorithm_version.compute_enabled` n'est PAS check dans le code — le job tourne quoi qu'il arrive.

**Failure recovery** : [docs/runbooks/ensemble-failure-recovery.md](../runbooks/ensemble-failure-recovery.md).

### 3.15 `cc-ensemble-explainer` (refactor 2026-05-27 : thin wrapper sur DBAnalysisEngine)

> Code : [backend/scripts/ensemble_explainer/main.py](../../backend/scripts/ensemble_explainer/main.py) (≤200 lignes wrapper)

**Track** : ENSEMBLE

**Description** : invoque le pipeline legacy `DBAnalysisEngine.run()` **sans pinner `--algorithm-version`** → l'auto-align détecte la row ensemble dans `pl_orchestrator_decision`, utilise `CALL_2_PROMPT_ENSEMBLE` (qui injecte les 25 diagnostics structurés), et écrit la narrative legacy-style sur la row ensemble. Aucun prompt / parser / writer custom — réutilisation totale du code legacy. Pre-flight `EnsembleRowMissingError` fail-loud si cc-ensemble-compute n'a pas écrit la row.

**Source** (via `DBAnalysisEngine.DBReader`) : `pl_orchestrator_decision` + 14× `pl_specialist_prediction` + `pl_fundamental_article` (date = data_date) + `pl_weather_observation` (date = data_date) + `pl_contract_data_daily` (last 2 sessions pour technicals today+yesterday).

**Cron** : `25 19 * * *` (P2b daily-gated, après cc-ensemble-compute).

**LLM** : 2× `gpt-4-turbo` (Call#1 macro/weather + Call#2 ensemble-aware decision). Format conclusion strict legacy `> ... • ... > A SURVEILLER AUJOURD'HUI: ...` × 3 alertes.

**Output** : UPDATE `pl_indicator_daily` ENSEMBLE row → set `eco`, `macroeco_bonus`, `macroeco_score`, `final_indicator`, `decision` (= `decision_wrapped`, pinné), `confidence`, `direction`, `conclusion` long-form.

**Cost** : ~$0.13/jour × 250/an ≈ $32.5/an. Trade-off vs version originale gpt-4o-mini ($0.001/jour) : la parité de format avec le frontend recommandation parser (3 tabs Recommandation / Supply / Technical) impose le verbose legacy.

### 3.16 `cc-daily-analysis`

> Code : [backend/scripts/daily_analysis/](../../backend/scripts/daily_analysis/)

**Track** : LEGACY (pinned via `--algorithm-version legacy` flag dans deploy.yml)

**Description** : pipeline historique LLM en 2 appels (Call #1 macro/weather + Call #2 decision). Écrit la row legacy de `pl_indicator_daily`.

**Cron** : `20 19 * * *` (P2b daily-gated, après cc-ensemble-compute pour pouvoir lire ensemble diagnostics et auto-aligner si présent).

**Output** : UPDATE `pl_indicator_daily` LEGACY row → set `decision`, `confidence`, `direction`, `conclusion`, `eco`, `macroeco_bonus`, `macroeco_score`, `final_indicator`.

Voir détail dans [PIPELINE_LEGACY.md](./PIPELINE_LEGACY.md) §3.2-3.5.

### 3.17 `cc-compass-brief`

> Code : [backend/scripts/compass_brief/](../../backend/scripts/compass_brief/)

**Track** : LEGACY (lit `pl_algorithm_version.is_active=true` JOIN → ressort la row legacy aujourd'hui)

**Description** : assemble un .txt yesterday + today depuis `pl_indicator_daily` + `pl_contract_data_daily` + `pl_fundamental_article` + `pl_weather_observation`. Upload sur Drive.

**Cron** : `30 19 * * *` (P2b daily-gated).

**Output** : `YYYYMMDD-CompassBrief.txt` sur Google Drive folder `GOOGLE_DRIVE_BRIEFS_FOLDER_ID`. NotebookLM ingère → produit `YYYYMMDD-CompassAudio.{wav|m4a|mp4}` overnight.

Voir détail dans [PIPELINE_LEGACY.md](./PIPELINE_LEGACY.md) §3.6.

### 3.18 `cc-compass-brief-ensemble` 🆕 (P4)

> Code : [backend/scripts/compass_brief_ensemble/](../../backend/scripts/compass_brief_ensemble/)

**Track** : ENSEMBLE

**Description** : assemble le brief ensemble en **7 sections** (signal + decomposition 14 specialists + macro radar + LLM eco + weather + technicals + recommandations). Lit la row ensemble enrichie par `cc-ensemble-explainer`.

**Cron** : `35 19 * * *` (P2b daily-gated, après cc-ensemble-explainer).

**Output** : `YYYYMMDD-CompassBrief-Ensemble.txt` sur Drive (même folder, filename discriminant). NotebookLM produit `YYYYMMDD-CompassAudio-Ensemble.{ext}`.

Voir détail dans [PIPELINE_ENSEMBLE.md](./PIPELINE_ENSEMBLE.md) §7.

### 3.19 `cc-ensemble-bootstrap-artifacts`

> Code : [backend/scripts/ensemble_bootstrap/](../../backend/scripts/ensemble_bootstrap/)

**Track** : ENSEMBLE (utility)

**Description** : seed 38 BYTEA rows dans `pl_model_artifact` depuis le frozen R&D pack (14 specialists + 5 long-run layers + 4 configs + 15 metadata). SHA-256 verified.

**Cron** : aucun (no scheduler) — déployé sans scheduler, triggered manuellement quand R&D ship une nouvelle version mensuelle.

**Trigger manuel** : `gcloud run jobs execute cc-ensemble-bootstrap-artifacts --region europe-west9 --project cacaooo`.

**Output** : 38 rows dans `pl_model_artifact`.

### 3.20 `cc-publish-session`

> Code : [backend/scripts/publish_session/](../../backend/scripts/publish_session/)

**Track** : both (gate de publication du dashboard, indépendant du track)

**Description** : release une séance dans `pl_session_release` une fois sa data complète (indicator + press + meteo) ET l'audio NotebookLM présent dans Drive → le dashboard bascule sur la nouvelle séance **de façon atomique et le soir même**, au lieu d'attendre le lendemain. Repli matinal (passé `display_date(T)` 09:00 UTC) : release en données-seules pour ne jamais bloquer le dashboard sur la veille (l'audio joue quand même dès son upload — le endpoint audio lit Drive directement, `has_audio` n'est qu'une métadonnée).

**Cron** : `*/30 20-23,0-9 * * *` — toutes les 30 min, fenêtre soir (après le dernier job Phase B à 19:35) → 09:30 UTC le lendemain. No-op tant que data+audio pas prêts, puis publie. Idempotent (une séance publiée n'est jamais re-traitée).

**Output** : `pl_session_release` (`session_date` PK, `published_at`, `has_audio`, `source`). Le endpoint dashboard `latest_trading_day` = la séance publiée la plus récente (`MAX(display_date)` join `pl_session_release`), avec repli sûr vers l'ancien `MAX(display_date) <= today` tant que la table est vide → **non cassant**.

**Runbook** : [session-publish-gate.md](../runbooks/session-publish-gate.md).

---

## 4 — Graphe de dépendances

```
                              ┌─────────────────────────┐
                              │  cc-fx-scraper (18:30)  │
                              └────────────┬────────────┘
                                           ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  Phase A — market close inputs                                │
   │  ┌───────────────────┐                                        │
   │  │ cc-barchart       │───────────► pl_contract_data_daily     │
   │  │   (19:00)         │             (OHLCV+IV)                 │
   │  └───────┬───────────┘                       ▲                │
   │          │                                   │                │
   │          ▼                                   │                │
   │  ┌───────────────────┐         ┌────────────┴───────────────┐ │
   │  │ cc-ice-stocks     │────────►│ cc-cftc                    │ │
   │  │ cc-barchart-eu    │  update │   (UPDATE stock_*/com_net) │ │
   │  └───────────────────┘ same row└─────────────────────────────┘ │
   │                                                                 │
   │           ┌──────────────────┐                                  │
   │           │ cc-compute-      │──────► pl_derived_indicators     │
   │           │  indicators(19:15)│       pl_indicator_daily (z)   │
   │           └──────┬───────────┘                                  │
   │                  │                                              │
   │                  ▼                                              │
   │           ┌──────────────────┐                                  │
   │           │ cc-ensemble-     │────► pl_specialist_prediction   │
   │           │  compute (19:18) │      pl_orchestrator_decision   │
   │           │  reads:          │      pl_indicator_daily (ENS)   │
   │           │  - pl_derived_*  │                                  │
   │           │  - article_seg   │                                  │
   │           │  - external_ind  │                                  │
   │           │  - cot_eu_weekly │                                  │
   │           │  - model_artifact│                                  │
   │           └──────────────────┘                                  │
   └────────────────────────────────────────────────────────────────┘

                          (independent — Phase B)
   ┌──────────────────────────────────────────────────────────────┐
   │  cc-meteo-agent (19:00) ────────► pl_weather_observation     │
   │  cc-press-review-agent (19:05) ──► pl_fundamental_article    │
   │                                    pl_article_segment        │
   │                                    (consumed by ensemble too)│
   └──────────────────────────────────────────────────────────────┘

                          (Phase B — LLM writers)
   ┌──────────────────────────────────────────────────────────────┐
   │  cc-daily-analysis (19:20)  ──UPDATE──► pl_indicator_daily   │
   │  --algorithm-version legacy             (LEGACY row LLM)      │
   │                                                                │
   │  cc-ensemble-explainer (19:25) ─UPDATE──► pl_indicator_daily │
   │  reads orchestrator+specialists+press+    (ENSEMBLE row LLM)  │
   │  meteo                                                         │
   └──────────────────────────────────────────────────────────────┘

                          (Phase B — Drive uploads)
   ┌──────────────────────────────────────────────────────────────┐
   │  cc-compass-brief (19:30) ──reads is_active=true─► Drive     │
   │                                                  (legacy.txt)│
   │                                                                │
   │  cc-compass-brief-ensemble (19:35) ──reads ENSEMBLE row─►Drive│
   │                                              (-Ensemble.txt) │
   └──────────────────────────────────────────────────────────────┘

                          (separate non-Phase)
   ┌──────────────────────────────────────────────────────────────┐
   │  cc-eca-grindings (13:00) calendar-gated ─► pl_supply_demand │
   │  cc-nca-grindings (14:00) calendar-gated                     │
   │  cc-publication-watchdog (16:00) ─► Sentry alerts             │
   │  cc-ice-cot-eu (22:10) ──► pl_cot_eu_weekly                  │
   │  cc-enso (monthly 20th) ─► pl_external_indicator (ENSO)      │
   └──────────────────────────────────────────────────────────────┘
```

**Cascade en cas de failure** :

| Job qui fail | Impact downstream |
|---|---|
| `cc-barchart-scraper` | ❌ Tous les downstream (no OHLCV → compute-indicators fail → ensemble + daily-analysis fail → no brief) |
| `cc-ice-stocks-scraper` ou `cc-cftc` | ⚠️ Tolerable — depuis 2026-05-27, ces tables sont indépendantes de l'OHLCV row. Pas de fail-loud. Le dashboard / brief continueront d'afficher la dernière obs en date (forward-fill on/before pattern) avec le `*_report_date` affiché côté frontend pour signaler la fraîcheur. |
| `cc-compute-indicators` | ❌ ensemble + daily-analysis fail (no indicators) |
| `cc-ensemble-compute` | ⚠️ cc-ensemble-explainer fail (no ensemble row), cc-compass-brief-ensemble fail. Legacy brief intact. |
| `cc-daily-analysis` | ⚠️ Legacy brief incomplet (decision/eco missing). Ensemble brief intact. |
| `cc-ensemble-explainer` | ⚠️ Ensemble brief sans narrative (decision OK mais eco/conclusion NULL → brief affichera "(pas de conclusion narrative)"). Legacy brief intact. |
| `cc-press-review-agent` ou `cc-meteo-agent` | ⚠️ Les 2 briefs auront une section press/meteo vide. |
| `cc-eca` / `cc-nca` | ⚠️ Pas d'impact court terme (les briefs ne lisent pas encore supply_demand_observation). Watchdog alertera après 21j. |

---

## 5 — Données partagées vs spécifiques

| Table DB | Écrit par | Lu par | Track utilisation |
|---|---|---|---|
| `pl_contract_data_daily` | barchart-scraper (uniquement OHLCV+IV depuis 2026-05-27) | compute-indicators, daily-analysis, ensemble-compute, ensemble-explainer, compass-brief, compass-brief-ensemble, frontend | shared |
| `pl_derived_indicators` | compute-indicators | daily-analysis, ensemble-compute, ensemble-explainer, compass-brief, compass-brief-ensemble | shared |
| `pl_indicator_daily` (numerics) | compute-indicators | compass-brief, compass-brief-ensemble | shared |
| `pl_indicator_daily.decision` legacy | daily-analysis (with `--algorithm-version legacy`) | compass-brief, frontend (fallback) | LEGACY |
| `pl_indicator_daily.decision` ensemble | ensemble-compute | compass-brief-ensemble, frontend (primary) | ENSEMBLE |
| `pl_indicator_daily.{eco,conf,dir,concl}` legacy | daily-analysis | compass-brief | LEGACY |
| `pl_indicator_daily.{eco,conf,dir,concl}` ensemble | ensemble-explainer | compass-brief-ensemble | ENSEMBLE |
| `pl_orchestrator_decision` | ensemble-compute | ensemble-explainer, compass-brief-ensemble, frontend (`/ensemble-diagnostics`) | ENSEMBLE |
| `pl_specialist_prediction` | ensemble-compute | ensemble-explainer, compass-brief-ensemble, frontend (`/ensemble-diagnostics`) | ENSEMBLE |
| `pl_stock_observation` | ice-stocks-scraper (region='us'), barchart-stocks-eu-scraper (region='eu') | positioning_service (dashboard gauges), daily-analysis (STOCKTOD), compass-brief (STOCK US), watchlist_eval | shared (NEW 2026-05-27) |
| `pl_cot_us_weekly` | cftc-scraper (Disaggregated COT, depuis 2026-05-27) | positioning_service (dashboard gauges + COT US release date), daily-analysis (COMNETTOD), compass-brief (COM NET US), watchlist_eval | shared (NEW 2026-05-27) |
| `pl_fundamental_article` | press-review-agent | daily-analysis (Call #1), ensemble-explainer, compass-brief, compass-brief-ensemble, frontend | shared |
| `pl_article_segment` | press-review-agent | ensemble-compute (MacroEventLayer) | ENSEMBLE-relevant |
| `pl_weather_observation` | meteo-agent | daily-analysis (Call #1), ensemble-explainer, compass-brief, compass-brief-ensemble, frontend | shared |
| `pl_seasonal_score` | meteo-agent | frontend (Weather card) | shared |
| `pl_external_indicator` | enso-scraper, fx-scraper | ensemble-compute specialists | ENSEMBLE |
| `pl_cot_eu_weekly` | ice-cot-eu-scraper | ensemble-compute specialists, positioning_service | ENSEMBLE + shared |
| `pl_supply_demand_observation` | eca-grindings, nca-grindings | (réservé future — brief enrichments) | shared, dormant |
| `ref_publication_calendar` | (seeded by migration), UPDATE by ECA/NCA scrapers | ECA/NCA scrapers, watchdog | shared |
| `pl_model_artifact` | ensemble-bootstrap-artifacts | ensemble-compute | ENSEMBLE |
| `pl_algorithm_version` | (seed migrations only) | daily-analysis, ensemble-compute, compass-brief, dashboard | shared |
| `pl_algorithm_config` | (seed migrations only) | compute-indicators, ensemble-compute (compass_wrapper threshold) | shared |
| `pl_signal_component` | daily-analysis | (audit) | LEGACY |

---

## 6 — Jobs anciens / dépréciés

Tables et jobs présents dans la base mais plus utilisés en production :

| Asset | Statut | Pourquoi déprécié | Plan |
|---|---|---|---|
| Table `technicals` | Déprécié | Remplacée par `pl_contract_data_daily` + `pl_derived_indicators` (split contract-centric) | Drop dans une future migration |
| Table `indicator` | Déprécié | Remplacée par `pl_indicator_daily` (avec scope algorithm_version_id) | Drop future |
| Table `market_research` | Déprécié | Remplacée par `pl_fundamental_article` (multi-provider via is_active flag) | Drop future, mais reste lu en fallback par certains lecteurs (à nettoyer) |
| Table `weather_data` | Déprécié | Remplacée par `pl_weather_observation` | Drop future, idem fallback |
| Google Sheets ETL | Supprimé | Migration vers Postgres-only complète | Plus de scripts ETL Sheets |
| Job Railway crons | Migré → Cloud Run | Plateforme changée | Aucun reste |

⚠️ **Note importante** : les tables dépréciées existent toujours en DB et sont parfois lues en fallback par les lecteurs (cf. `compass_brief/db_reader.py` qui essaie d'abord `pl_fundamental_article` puis fallback `market_research`). À nettoyer dans une refonte future.

---

## 7 — Jobs candidats / futurs (out-of-scope actuelle)

| Job candidat | Sémantique | Statut | Référence |
|---|---|---|---|
| `cc-ccc-arrivals-scraper` | Arrivages cocoa CIV (CCC) hebdomadaire | À implémenter | [P3-fundamental-data-scrapers-grindings.md](../user-stories/P3-fundamental-data-scrapers-grindings.md) |
| `cc-cocobod-scraper` | Production Ghana COCOBOD mensuelle | À implémenter | idem |
| `cc-cga-scraper` | Broyages Asie (CGA) trimestriels | À investiguer (site Wix) | idem |
| `cc-icco-scraper` | ICCO Monthly Review (production, surplus/deficit) | Différé — data structurée paywallée | idem |
| `cc-macro-climate-agent` | NOAA CPC ENSO + IRI forecasts + BoM, narrative LLM | Partiellement réalisé (ENSO scraper OK, agent narrative non) | [P1-macro-climate-signal.md](../user-stories/P1-macro-climate-signal.md) |
| `cc-pipeline-orchestrator` | Orchestrateur unique multi-jobs avec retry + completeness gate | Spec écrite, non implémenté | [P2-pipeline-orchestrator.md](../user-stories/P2-pipeline-orchestrator.md) |
| `cc-grindings-press-attention` | Détecter publi grindings dans press_review pour cross-check | Idea | (none) |

---

## 8 — Pour aller plus loin

- [PIPELINE_LEGACY.md](./PIPELINE_LEGACY.md) — comment le pipeline LLM legacy produit son brief
- [PIPELINE_ENSEMBLE.md](./PIPELINE_ENSEMBLE.md) — comment le pipeline ML ensemble produit le sien
- [docs/runbooks/brief-dual-track.md](../runbooks/brief-dual-track.md) — opérations du dual-track
- [docs/runbooks/pipeline-failure-recovery.md](../runbooks/pipeline-failure-recovery.md) — récupération en cas de panne
- [docs/runbooks/ensemble-failure-recovery.md](../runbooks/ensemble-failure-recovery.md) — récupération ensemble spécifique
- [docs/onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md](../onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md) — déploiement initial ensemble
- [docs/onboarding/HEDI_DATA_MAP.md](../onboarding/HEDI_DATA_MAP.md) — détail features ensemble par specialist
- [CLAUDE.md](../../CLAUDE.md) — référence complète du projet (commandes, architecture, déploiement)
