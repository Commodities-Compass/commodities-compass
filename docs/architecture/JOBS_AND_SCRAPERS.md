# Jobs & Scrapers — Catalogue exhaustif

> Inventaire complet des **jobs Cloud Run** et **schedulers** du pipeline Compass Cocoa. Pour chaque job : description, source, cron, output, quel(s) pipeline(s) le consomme, statut (actif / déprécié / out-of-scope), et tolérance de scraping. Document indépendant — peut être lu seul pour comprendre la photographie complète.

> **Périmètre** (vérifié contre GCP le 2026-08-19) : **19 jobs Cloud Run**, tous
> déployés par `deploy.yml`, et **18 schedulers**. Le 19ᵉ job n'a pas de scheduler :
> `cc-regime-bootstrap-artifacts`, utilitaire one-shot. Les 6 jobs legacy/ensemble
> ont été supprimés le 2026-08-19 — contexte business dans
> [docs/archive/pipelines/](../archive/pipelines/).

---

## 1 — Vue d'ensemble : timeline UTC weekdays

```
Time UTC | Job                                   | Track       | Type
─────────┼───────────────────────────────────────┼─────────────┼──────────────────
08:00-16:00 */15 | cc-intraday-monitor              | shared      | Alertes intraday (gate London)
13:00    | cc-eca-grindings-scraper              | shared      | Calendar-gated quarterly
14:00    | cc-nca-grindings-scraper              | shared      | Calendar-gated quarterly
16:00    | cc-publication-calendar-watchdog      | shared      | Daily safety watchdog
18:30    | cc-fx-scraper                         | shared      | Phase A (FX, ECB daily)
19:00    | cc-barchart-scraper                   | shared      | Phase A (OHLCV+IV)
19:00    | cc-meteo-agent                        | REGIME      | Phase B (eve-gated)
19:05    | cc-ice-stocks-scraper                 | shared      | Phase A (STOCK US)
19:05    | cc-cftc-scraper                       | shared      | Phase A (COM NET US)
19:05    | cc-press-review-agent                 | REGIME      | Phase B (eve-gated)
19:10    | cc-barchart-stocks-eu-scraper         | shared      | Phase A (stock_eu)
19:15    | cc-compute-indicators                 | shared      | Phase A (engine) + jauges (--stage all)
19:45    | cc-roll-watchdog                      | shared      | Nudge roll (Sentry only)
19:50    | cc-regime-shadow                      | REGIME      | Phase B — LA DÉCISION SERVIE
19:55    | cc-regime-brief                       | REGIME      | Phase B — narratif + Drive
22:10    | cc-ice-cot-eu-scraper                 | shared      | Phase A (weekly snapshot)
─────────┼───────────────────────────────────────┼─────────────┼──────────────────
20:00-09:30 */30 | cc-publish-session               | shared      | Gate de publication
Monthly  | cc-enso-scraper                       | shared      | 20 of month at 22:00 UTC
```

**Légende du Track** :
- `shared` : données de marché, consommées par la décision, les jauges ou le dashboard
- `REGIME` : la piste servie depuis le 2026-08-19 (regime + judge + brief)

⚠️ Les mentions `ENSEMBLE-only` qui subsistent plus bas dans ce document datent de
l'époque à deux pistes. Les scrapers ainsi étiquetés (`cc-ice-cot-eu-scraper`,
`cc-enso-scraper`) **tournent toujours** : ils alimentent `pl_cot_eu_weekly` et
`pl_external_indicator`, que le dashboard et le panneau macro lisent. Ce que
l'étiquette voulait dire, c'est « pas consommé par le moteur legacy » — ce qui
n'a plus d'objet.

**Légende du Type** :
- `Phase A` : Market close (weekdays, sur session T)
- `Phase B` : Eve of next trading day (daily cron + agent gate `is_eve_of_trading_day()`)
- `Calendar-gated quarterly` : Daily cron, agent gate sur `ref_publication_calendar`
- `Daily safety watchdog` : Daily cron, agent alerte si publications en retard

---

## 2 — Catalogue master (tableau)

> **Hors catalogue — `watchai-sync`.** Les flux physiques origine (bloc ② WatchAI) n'ont **ni Cloud Run Job ni scheduler** : la source est un checkout de fichiers `watch-ai`, pas une API, donc l'ingestion est une **CLI manuelle** lancée par un humain (`poetry run watchai-sync`). Elle écrit `pl_origin_*` et ne touche à aucune table du pipeline quotidien. Ce n'est pas un oubli de ce catalogue : il n'y a rien à ordonnancer. Procédure — y compris le chargement prod via bastion : [watchai-ingestion.md](../runbooks/watchai-ingestion.md).


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
| **cc-compute-indicators** | `15 19 * * 1-5` | shared | `pl_contract_data_daily` | `pl_derived_indicators`, `pl_indicator_daily` (numerics), **`pl_dashboard_gauge`** | ✅ Actif — `--stage all` depuis 2026-08. L'étage `gauges` est algo-indépendant et relançable seul (`--stage gauges`) |
| **cc-regime-shadow** | `50 19 * * *` (eve-gated) | REGIME+JUDGE | `v_contract_data_chained` (self-computed features), `pl_model_artifact`, `pl_fundamental_article` (en), `pl_weather_observation` (en) | `pl_regime_shadow`, `pl_judge_shadow`, **adapter row** dans `pl_indicator_daily` | ✅ **SERVI** (`serving_rank = 1` depuis 2026-08-19) |
| **cc-regime-brief** | `55 19 * * *` | REGIME+JUDGE | `pl_regime_shadow`, `pl_judge_shadow`, presse, météo, technicals, farmgate, YTD | UPDATE `pl_indicator_daily` (narration native fr+en) + Drive `YYYYMMDD-CompassBrief-Regime{,-EN}.txt` | ✅ **SERVI** — écrit la narration de la ligne servie |
| **cc-regime-bootstrap-artifacts** | (manual) | REGIME | R&D frozen regime pack | `pl_model_artifact` BYTEA rows | ✅ Actif (no scheduler) |
| **cc-intraday-monitor** | `*/15 8-16 * * 1-5` | shared | Barchart core-api (httpx, delayed ~15 min) + `pl_derived_indicators` (S1/R1) + `ref_alert_rule` | `pl_contract_data_intraday` (append) + `aud_alert_event` + Telegram sendMessage | 🆕 2026-07 (shadow ALERT_CHANNEL=console) |
| **cc-roll-watchdog** | `45 19 * * 1-5` | shared | `v_contract_data_chained` (OI + volume) vs calendrier de roll | Sentry nudge (no DB write) | ✅ Actif |
| **cc-publish-session** | `*/30 20-23,0-9 * * *` | shared | complétude `pl_indicator_daily` + présence audio Drive | `pl_session_release` (bascule atomique du dashboard) | ✅ Actif |

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

### 3.14-3.18 — jobs retirés le 2026-08-19

`cc-ensemble-compute`, `cc-ensemble-explainer`, `cc-daily-analysis`,
`cc-compass-brief`, `cc-compass-brief-ensemble`. Leurs fiches détaillées sont
dans [docs/archive/pipelines/](../archive/pipelines/). Remplacés par
`cc-regime-shadow` (19:50) et `cc-regime-brief` (19:55).

### 3.19 — `cc-ensemble-bootstrap-artifacts`, retiré le 2026-08-19

Semait 38 lignes BYTEA dans `pl_model_artifact` depuis le pack R&D gelé. Le job
Cloud Run a été supprimé avec les cinq autres ; **les 38 artefacts restent en
base**, c'est ce qui rend un replay possible. Voir
[docs/archive/pipelines/](../archive/pipelines/#how-to-replay-one-of-them-now).

### 3.19 bis `cc-regime-bootstrap-artifacts`

> Code : [backend/scripts/regime_shadow/bootstrap.py](../../backend/scripts/regime_shadow/bootstrap.py)

**Track** : REGIME (utility) — le seul job vivant sans scheduler.

**Cron** : aucun. Déclenché à la main quand la R&D livre un nouveau pack.

**Trigger manuel** : `gcloud run jobs execute cc-regime-bootstrap-artifacts --region europe-west9 --project cacaooo`.

### 3.20 `cc-intraday-monitor` 🆕 (2026-07)

> Code : [backend/scripts/intraday_monitor/](../../backend/scripts/intraday_monitor/) · US : [P1-intraday-threshold-alerts-telegram.md](../user-stories/P1-intraday-threshold-alerts-telegram.md)

**Track** : shared (aval des deux tracks — lit la décision affichée, ensemble-préférée)

**Description** : toutes les 15 min en séance de Londres, fetch le prix différé (~10-15 min) du front-month via httpx pur (two-step cookie `XSRF-TOKEN` → core-api `raw=1`, pas de Playwright), append `pl_contract_data_intraday`, et compare aux niveaux « À surveiller » (S1/R1 de `pl_derived_indicators` à la **dernière session complétée** — les niveaux affichés sur le dashboard le jour même). Franchissement edge-triggered `(prev, curr)` → alerte **first-cross-only par (règle, session)**, dédup data-level `UNIQUE(rule_id, session_date, crossing_seq)` + `ON CONFLICT DO NOTHING` (un re-run ne re-spamme jamais). Delivery via interface `AlertSender` : `TelegramSender` (canal privé broadcast-only, un `sendMessage` = fan-out) ou `ConsoleSender` (`ALERT_CHANNEL=console`, shadow/dev).

**Règles (config-as-data, `ref_alert_rule`)** : `close_below_s1` (bearish) + `close_above_r1` (bullish). Pas de RSI intraday (valeur daily non figée en séance).

**Gates** : `should_skip_non_trading_day()` + `in_london_session()` (09:30-16:55 Europe/London, heures officielles ICE, DST via zoneinfo) — tick hors séance = exit 0 (Sentry cron = succès).

**Cron** : `*/15 8-16 * * 1-5` UTC (large pour couvrir GMT/BST, ~29 ticks utiles/séance).

**Env** : `ALERT_CHANNEL` (`console` default / `telegram`), `TELEGRAM_BOT_TOKEN` (Secret Manager), `TELEGRAM_CHANNEL_ID` (chat_id numérique du canal privé).

**CLI** : `poetry run intraday-monitor [--dry-run] [--verbose] [--force]`.

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
   │                  │  NB : cc-compute-indicators alimente aussi   │
   │                  │  pl_dashboard_gauge (algorithm-independent)  │
   │                  ▼                                              │
   │           (les jauges du dashboard, indépendantes de l'algo)    │
   └────────────────────────────────────────────────────────────────┘

                          (independent — Phase B)
   ┌──────────────────────────────────────────────────────────────┐
   │  cc-meteo-agent (19:00) ────────► pl_weather_observation     │
   │  cc-press-review-agent (19:05) ──► pl_fundamental_article    │
   │                                    pl_article_segment        │
   │                                    (lus par le judge L3)     │
   └──────────────────────────────────────────────────────────────┘

                     (Phase B — la décision servie)
   ┌──────────────────────────────────────────────────────────────┐
   │  cc-regime-shadow (19:50) — une exécution, trois étapes :    │
   │                                                              │
   │   L1+L2 régime ──► pl_regime_shadow                          │
   │     self-compute depuis les prix bruts,                      │
   │     ne lit JAMAIS pl_derived_indicators                      │
   │        │                                                     │
   │        ▼                                                     │
   │   L3 judge  ────► pl_judge_shadow                            │
   │     lit press + meteo en base (o4-mini)                      │
   │        │                                                     │
   │        ▼                                                     │
   │   adapter row ──► pl_indicator_daily  ◄── SERVI              │
   │     structurel seulement (decision/confidence/direction)     │
   └──────────────────────────────────────────────────────────────┘

                     (Phase B — la prose, puis Drive)
   ┌──────────────────────────────────────────────────────────────┐
   │  cc-regime-brief --language both (19:55)                     │
   │    ├─► UPDATE pl_indicator_daily (conclusion/eco/rationale)  │
   │    └─► Drive  YYYYMMDD-CompassBrief-Regime{,-EN}.txt         │
   │           natif par langue, jamais traduit                   │
   └──────────────────────────────────────────────────────────────┘

                     (publication — toutes les 30 min)
   ┌──────────────────────────────────────────────────────────────┐
   │  cc-publish-session (20:00→09:30) ──► pl_session_release     │
   │    bascule atomique une fois données + audio prêts           │
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
| `cc-press-review-agent` ou `cc-meteo-agent` | ⚠️ Les 2 briefs auront une section press/meteo vide. |
| `cc-regime-shadow` | ⚠️ Aucun impact utilisateur tant que `serving_rank` de regime est NULL. Post-bascule : ❌ pas de décision du jour, et `cc-regime-brief` fail-loud (pas d'adapter row à enrichir). |
| `cc-regime-brief` | ⚠️ Aucun impact tant qu'inerte. Post-bascule : section Recommandation vide (aucun fallback inter-algo) + pas de brief Drive → pas d'audio. |
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

⚠️ **Note importante** : les tables dépréciées existent toujours en DB. Le lecteur
qui les interrogeait en fallback (`compass_brief/db_reader.py`) a disparu avec la
suppression du 2026-08-19 ; `regime_brief` ne lit **que** les tables `pl_*`. Il
reste à vérifier si un autre consommateur les touche encore avant de les dropper.

⚠️ **Jobs retirés le 2026-08-19** — `cc-daily-analysis`, `cc-compass-brief`,
`cc-compass-brief-ensemble`, `cc-ensemble-compute`, `cc-ensemble-explainer`,
`cc-ensemble-bootstrap-artifacts`. Schedulers détruits le 18, jobs Cloud Run
supprimés le 19. Leurs tables gardent chaque ligne. Les noms de jobs qui
subsistent en §5 sont de la **provenance historique** (« qui a écrit cette
table »), pas des producteurs actifs. Replay :
[docs/archive/pipelines/](../archive/pipelines/#how-to-replay-one-of-them-now).

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

- [PIPELINE_LEGACY.md](../archive/pipelines/PIPELINE_LEGACY.md) — comment le pipeline LLM legacy produit son brief
- [PIPELINE_ENSEMBLE.md](../archive/pipelines/PIPELINE_ENSEMBLE.md) — comment le pipeline ML ensemble produit le sien
- [docs/archive/pipelines/brief-dual-track.md](../archive/pipelines/brief-dual-track.md) — opérations du dual-track
- [docs/runbooks/pipeline-failure-recovery.md](../runbooks/pipeline-failure-recovery.md) — récupération en cas de panne
- [docs/archive/pipelines/ensemble-failure-recovery.md](../archive/pipelines/ensemble-failure-recovery.md) — récupération ensemble spécifique
- [docs/onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md](../archive/onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md) — déploiement initial ensemble
- [docs/onboarding/HEDI_DATA_MAP.md](../archive/onboarding/HEDI_DATA_MAP.md) — détail features ensemble par specialist
- [CLAUDE.md](../../CLAUDE.md) — référence complète du projet (commandes, architecture, déploiement)
