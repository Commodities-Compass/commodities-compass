# JULIEN_DATA_MAP — Cartographie exhaustive des données utilisées par Julien

> **Source** : branche `clean-v3` de Julien, snapshot inspecté le 2026-05-19.
> **Périmètre** : tout ce que ses expériences `EXP-BT-NNN` (compass_backtest) consomment.
> **Usage** : alignement du produit Compass sur les données qu'il valide en R&D.

---

## 1. Vue d'ensemble — 3 piliers de données

```
┌────────────────────────────────────────────────────────────────────────────┐
│  PILIER 1 — CORE DATASET (daily, 2016-2026, 86-108 cols selon snapshot)    │
│    compass_backtest/data/rd_extract/cocoa_rd_dataset_YYYYMMDD.csv          │
│    → 5 groupes : OHLCV+IV / Technicals / COT EU / Sentiment LLM / Fondam.  │
└────────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────────┐
│  PILIER 2 — DONNÉES EXTERNES (joined-on-demand, source statique)           │
│    compass_backtest/data/cot_eu_lce/      (CFTC TFF brut + features dériv.) │
│    compass_backtest/data/rd_extract/era5-et-enso/ (NetCDF météo + MEI/ONI) │
│    compass_backtest/data/stock_eu/         (stocks LIFFE CAY00)            │
└────────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────────────┐
│  PILIER 3 — SCRAPERS LOCAUX (autonomie totale Julien, S8 stack)            │
│    compass_backtest/optimizer_v3/scrapers/                                  │
│    → 6 modules + DB SQLite legacy locale (data/legacy_db/optimizer.sqlite) │
└────────────────────────────────────────────────────────────────────────────┘
```

Cadence : daily prod (PILIER 1), refresh manuel mensuel (PILIER 2 ENSO/ERA5), scraping continu (PILIER 3).

---

## 2. PILIER 1 — Core dataset

### 2.1 Fichier(s) de référence

| Snapshot | Path | Rows | Cols | Range | SHA256 |
|---|---|---|---|---|---|
| **20260512** | [compass_backtest/data/rd_extract/cocoa_rd_dataset_20260512.csv](compass_backtest/data/rd_extract/cocoa_rd_dataset_20260512.csv) | 2602 | 108 | 2016-01-04 → 2026-05-11 | `01b1a1...0de382` |
| **20260513** | (path référencé dans config.py — fichier absent du repo car gitignored) | — | — | — | `c31c1f...87eccef` |
| **20260517** | [compass_backtest/data/rd_extract/cocoa_rd_dataset_20260517.csv](compass_backtest/data/rd_extract/cocoa_rd_dataset_20260517.csv) | 2606 | 86 | 2016-01-04 → 2026-05-17 | (non publié) |

Dictionnaire détaillé (92 cols documentées, scope-tagué [ABSOLUTE]/[METHOD-TIED]) : [compass_backtest/data/rd_extract/cocoa_rd_dataset_20260512.dictionary.md](compass_backtest/data/rd_extract/cocoa_rd_dataset_20260512.dictionary.md).

Lag policy déclarée (meta.json) :
- COT as-of tolerance : **14 jours** (release CFTC = mardi as-of + 3 cal days)
- Fundamentals : **2 mois** de lag (Db_Master_Tax publié à M+2)
- Sentiment article : **ffill 7 jours** (couvre week-ends + jours creux)

### 2.2 Groupes de colonnes — taxonomie complète

#### Groupe A — OHLCV + IV + Stocks + COT US (table prod `pl_contract_data_daily`)

| Col | Type | Null% (20260512) | Notes |
|---|---|---|---|
| `date` | DATE | 0.0 | Clé primaire |
| `contract_code` | TEXT | 0.0 | Front-month, ICE London #7 (ex. `CAK26`) |
| `contract_month` | TEXT | 0.0 | Suffixe livraison (`H/K/N/U/Z` + année) |
| `open` | FLOAT | 15.14 | NULL fréquent (pré-2018) |
| `high` | FLOAT | 0.0 | |
| `low` | FLOAT | 0.0 | |
| `close` | FLOAT | 0.0 | |
| `volume` | FLOAT | 0.0 | Daily total volume |
| `oi` | FLOAT | 0.0 | Open Interest |
| `implied_volatility` | FLOAT | **88.05** | Très sparse — utilisable à partir de 2024 seulement |
| `stock_us` | FLOAT | **87.86** | Stocks NY (CFTC, hebdo) |
| `stock_eu_bags60kg` | FLOAT | **87.43** | Stocks LIFFE (LCE) — uniquement présent dans le snapshot 20260512 |
| `com_net_us` | FLOAT | **87.86** | COT US net commerciaux |

> ⚠️ Les colonnes `implied_volatility`, `stock_us`, `stock_eu_bags60kg`, `com_net_us` ont >87% de NULL. Julien a flagué `implied_volatility` colinéaire à `atr_14d` (EXP-033, rejet).

#### Groupe B — Indicateurs techniques (table prod `pl_derived_indicators`)

15 colonnes [METHOD-TIED] : `pivot`, `ema12`, `ema26`, `macd`, `macd_signal`, `rsi_14d`, `stochastic_k_14`, `stochastic_d_14`, `atr`, `atr_14d`, `bollinger_upper/lower/width`, `close_pivot_ratio`, `volume_oi_ratio`, `daily_return`.

Fallback : [compass_backtest/optimizer_v3/](compass_backtest/optimizer_v3/) recompute via pandas si la table prod a des trous.

#### Groupe C — COT EU positioning (table prod `pl_cot_eu_weekly`, market=cocoa, variant=futures_only)

22 colonnes [ABSOLUTE] :
- 1 clé jointure : `cot_as_of_date`, `release_date` (= as_of + 3 cal days)
- 1 contexte : `cot_open_interest_all`
- 14 positions raw : `cot_{m_money|prod_merc|swap|other_rept|nonrept}_{long|short|spread}_all`
- 3 nets dérivés : `cot_{m_money|prod_merc|swap}_net`
- 3 normalisés 26 semaines : `cot_m_money_net_z_26w`, `cot_m_money_net_pctile_26w`, `cot_prod_merc_net_z_26w`

Join policy : `merge_asof backward` (tolerance = 14 j) sur `release_date` → pas de look-ahead.

> 🔬 **Finding EXP-040** : `cot_m_money_net_z_26w` ρ=-0.195 vs return h=22d. GO partiel (signal régime-stratifié).

#### Groupe D — Sentiment LLM (table prod `pl_article_segment`)

Pivot wide par **zone × thème**.
- **Zones (5)** : `afrique_ouest`, `all`, `civ` (Côte d'Ivoire), `ghana`, `monde`
- **Thèmes (8)** : `chocolat`, `demand`, `economie`, `macro`, `production`, `transformation` (+ variantes par zone)

Colonnes produites (sentiment + counts, snapshot 20260517) :
- **`sent_<zone>_<theme>`** (18 cols) : score sentiment moyen [-1, +1]
- **`n_articles_<zone>_<theme>`** (18 cols) : nombre d'articles agrégés

Null rates **très élevés** (90-99%) → utilisable uniquement en counts (n_articles, 0% nulls), pas en sentiment raw.
Lag policy : ffill 7 jours.

#### Groupe E — Fondamentaux internes Compass (snapshot 20260512 uniquement)

19 colonnes [ABSOLUTE], sources `Db_Master_Tax.xlsx + Db_Master_Achats.xlsx + Bilan_Grainage.xlsx` (lag 2 mois) :
- Volumes par catégorie produit (kg) : `vol_BEURRE`, `vol_CHOCOLAT`, `vol_FEVES`, `vol_HORS_GRADE`, `vol_MASSE`, `vol_POUDRE`
- Mix : `feves_share`, `processing_ratio`, `port_abj_share`
- Concentration acheteurs : `dest_hhi`, `top3_exporter_share`, `procurement_hhi`, `n_exporters`
- Activité : `total_volume_kg`, `n_transactions`, `total_procurement_kg`, `mean_caf_per_kg`
- Qualité : `avg_bean_count`, `grainage_anomaly`

> ⚠️ **Manquent dans 20260517** : Julien a retiré le bloc fondamentaux de la dernière régénération. À clarifier (perte de signal validée vs simple oubli).

### 2.3 Fichiers auxiliaires (rd_extract)

- [compute_pattern_features.py](compass_backtest/data/rd_extract/compute_pattern_features.py) — calcul des patterns chandelier (NR7/NR10, Inside Bar, Hammer, Outside Bar, WRB)
- [oldalgo_decisions.csv](compass_backtest/data/rd_extract/oldalgo_decisions.csv) — historique des décisions OPEN/HEDGE/MONITOR de l'algo prod (référence pour le `delta vs Always-HEDGE`)

---

## 3. PILIER 2 — Données externes

### 3.1 COT EU LCE — CFTC Disaggregated TFF

📁 [compass_backtest/data/cot_eu_lce/](compass_backtest/data/cot_eu_lce/)

| Fichier | Couverture | Notes |
|---|---|---|
| `COTHist2016.csv` → `COTHist2026.csv` | 11 ans | 1 fichier/an, format CFTC bulk |
| `cocoa_lce_cot_features.csv` | 2016-01 → présent | Features dérivées prêtes-à-joindre |
| [INVENTORY.md](compass_backtest/data/cot_eu_lce/INVENTORY.md) | doc | 92 colonnes exploitables détaillées |

**Source** : CFTC Disaggregated COT (Traders in Financial Futures, TFF), bulk historical. Téléchargé manuellement 2026-05-12. Cadence prod = hebdomadaire (release vendredi pour as-of mardi).

**Marchés conservés** : ICE Cocoa (LCE EU) + ICE Robusta Coffee + ICE White Sugar — chacun en variantes "Futures only" et "Combined". Volumétrie cocoa : 540 obs × 2 variantes = 1080 lignes.

**Quirk de format** : fichiers 2016-2020 utilisent `Swap__Positions_*` (double underscore, typo CFTC), corrigé en 2021+ → normaliser au load via `col.replace("__", "_")`.

**Features dérivées** ([cocoa_lce_cot_features.csv](compass_backtest/data/cot_eu_lce/cocoa_lce_cot_features.csv), 17 cols) :
- `cot_lce_oi` : open interest total
- Pour chaque catégorie {mm=managed money, pm=prod/merc, sw=swap dealers} :
  - `cot_lce_<cat>_{long,short,net}` — raw + net
  - `cot_lce_<cat>_net_z_26w` — z-score 26 semaines
  - `cot_lce_<cat>_net_pctile_26w` — percentile 26 semaines

### 3.2 ENSO — Indices NOAA

📁 [compass_backtest/data/rd_extract/era5-et-enso/](compass_backtest/data/rd_extract/era5-et-enso/)

| Fichier | Format | Source | Cadence | Lag |
|---|---|---|---|---|
| `enso_mei.csv` | `year,month,mei_v2` | NOAA PSL — MEI v2 | mensuel | publication ~M+1 |
| `enso_oni.csv` | `season,year,sst_total,oni_anom` | NOAA CPC — ONI 3-month rolling | mensuel | publication ~M+1 |

**Quirk MEI** : ligne 0 contient `mei_v2 = 2026.0` (artefact export) → filtrer `abs(mei_v2) <= 10`.
**Quirk ONI** : saison NDJ d'année Y = `Nov(Y)-Jan(Y+1)`, mois central = `Dec(Y)`. NOAA convention `year` = année de janvier → décrémenter year pour NDJ.

Join policy ([enso_join.py](compass_backtest/data/enso_join.py)) : `merge_asof backward` mensuel→daily + forward-fill. Lag d'1 mois appliqué systématiquement (publication début de mois suivant).

**Features dérivées** :
- `enso_mei`, `enso_oni_anom`, `enso_sst_total` — raw joined
- `enso_mei_z26w` — z-score rolling 182 jours
- `enso_signal = 0.6 × MEI + 0.4 × ONI_anom` — composite [-1, +1]
- `enso_phase_num` : `el_nino=+1`, `neutral=0`, `la_nina=-1`

### 3.3 ERA5 — Météo cocoa belt (Copernicus / ECMWF)

📁 [compass_backtest/data/rd_extract/era5-et-enso/](compass_backtest/data/rd_extract/era5-et-enso/)

11 fichiers NetCDF (un par an, 2016 → 2026) : `era5_YYYY_cocoa_belt.nc`. + sous-dossier `unzipped/` (versions extraites pour I/O direct).

**Grid** : V1 utilise Open-Meteo (gratuit, no-auth) sur 2 points : Daloa (CI, 7°N -5°E) + Kumasi (Ghana, 6.5°N -1.5°E). V1.1 (TODO) bascule sur Copernicus CDS pour grid précis 4-12°N × 9°W-2°E.

**Variables daily** :
- `era5_t2m_c` — température 2m (°C), moyenne belt (0.1% nulls EXP-049)
- `era5_precip_mm` — précipitations (mm/jour) (0.1% nulls EXP-049)

### 3.4 Stocks EU LIFFE

📁 [compass_backtest/data/stock_eu/](compass_backtest/data/stock_eu/)

| Fichier | Format | Cadence |
|---|---|---|
| `cocoa_cay00_stocks_bags60kg.csv` | `Date;Jour;Stocks (sacs 60kg)` | daily, CSV séparateur `;` |

Couverture : 2024-11-11 → présent (drop manuel).

---

## 4. PILIER 3 — Scrapers locaux (S8 autonomy stack)

📁 [compass_backtest/optimizer_v3/scrapers/](compass_backtest/optimizer_v3/scrapers/)

DB cible : `data/legacy_db/optimizer.sqlite` — schéma calqué sur Postgres prod Hedi pour rester compatible avec le read-path `scripts/data_loader`. Bootstrap initial = lecture des Parquet snapshots Hedi (seed historique 2016-2026).

| Scraper | Source publique | Table cible | Cadence |
|---|---|---|---|
| [_db.py](compass_backtest/optimizer_v3/scrapers/_db.py) | — (engine + bootstrap) | toutes | one-shot |
| [lce_ohlcv.py](compass_backtest/optimizer_v3/scrapers/lce_ohlcv.py) | Barchart London Cocoa Futures (Playwright + HTML fallback) | `pl_contract_data_daily` | daily incrémental (7 derniers jours ouvrés) |
| [cot_cftc.py](compass_backtest/optimizer_v3/scrapers/cot_cftc.py) | ICE Europe COT (`theice.com/publicdocs/futures/COTHist{YYYY}.csv`) + CFTC.gov (`fut_disagg_txt_{YYYY}.zip`) | `pl_cot_eu_weekly` + équivalent US | weekly |
| [enso_noaa.py](compass_backtest/optimizer_v3/scrapers/enso_noaa.py) | NOAA PSL MEI v2 (`meiv2.data`) + NOAA CPC ONI (`oni.ascii.txt`) | `pl_enso_monthly` | mensuel |
| [era5_cds.py](compass_backtest/optimizer_v3/scrapers/era5_cds.py) | Open-Meteo Archive API (V1) → Copernicus CDS (V1.1 TODO) | `pl_era5_daily` (`date, zone, t2m_c, precip_mm`) | daily |
| [sentiment_llm.py](compass_backtest/optimizer_v3/scrapers/sentiment_llm.py) | RSS (Google News × 3, Cocoa Post, ICCO) + Claude Haiku | `pl_article_segment` (15 cols) | daily |

**Garanties** : idempotence `ON CONFLICT (...) DO UPDATE`, SHA-256 audit sur les downloads, anti-look-ahead strict (`lce_ohlcv` ne touche pas `stock_us`/`com_net_us`/`implied_volatility` — scraper dédié séparé).

---

## 5. Mapping expérience ↔ données

Branche `clean-v3`, sous [compass_backtest/experiments/](compass_backtest/experiments/) :

| Exp | Données consommées | Features clé | Verdict |
|---|---|---|---|
| **EXP-034** mean reversion T+6 | OHLC + `close` + régime HMM | rolling mean N∈{75,100,150,200,250} × σ∈{1,1.5,2,2.5} | inversion T+1→T+6 |
| **EXP-036** hedge timing T+6 | RSI, ATR, Bollinger, stochastique, vol gate | combinaisons multi-indicateurs (RSI×vol, BB×momentum…) | exploratoire |
| **EXP-037** patterns chandelier | OHLC seul | NR7, Inside Bar, Hammer/Shooting Star, WRB, Outside Bar | NR10 post-rupture 63.6% (n≈85) |
| **EXP-039** NR post-rupture deep | OHLC + régime HMM + filtres directionnels (ATR, BB) | NR7/10, NR2 (compression prolongée), NR×Bull/Elevated-vol | confirmation EXP-037 sous bootstrap 2000× |
| **EXP-041** signal final OB+NR+ERA5+ENSO | OHLC + ERA5_t2m + ERA5_precip + ENSO_MEI + ENSO_OI | scoring composite (tech 3pts + fond 2pts), cascade ENSO→OB/NR | cible ≥56% acc + cov≥15% |
| **EXP-049** ERA5 + ENSO contribution | ERA5_t2m, ERA5_precip, ENSO_MEI/ONI/phase | rolling 90j anomalies, El Niño gate, stress thermique | ERA5_ENSO_composite 53.7% [51.1, 56.1] ✓ |

**Pattern récurrent** : OHLC + indicateurs techniques + COT EU (positioning) + ERA5/ENSO (météo/climat) sont les 4 blocs réutilisés. Le sentiment LLM est ingéré mais peu exploité (null rate >90%). Les fondamentaux internes (Db_Master_*) ont disparu du snapshot 20260517 — à clarifier.

---

## 6. Conventions horizon & validation (config.py)

- **Horizon principal** : T+6 trading days
- **Embargo** (purged k-fold López de Prado) : 8 jours (T+6 + 2j marge autocorr ATR)
- **Train minimum** : 504 jours (2 ans)
- **Fold step** : 60 jours
- **Folds minimum** : 15
- **Rupture structurelle** : `2024-01-30` (Bai-Perron + HMM concordants, EXP-005)
- **HMM** : 4 régimes (Crash / Normal / Elevated-vol / Bull), seuil certitude min = 0.65
- **Bootstrap** : 1000 itérations BCa, FDR Benjamini-Hochberg α=0.05
- **Seed** : 42 (reproductibilité bit-identique exigée par CLAUDE.md)

---

## 7. Implications produit — pistes d'alignement

Pour faire converger le produit Compass avec ce que Julien valide en R&D :

1. **OHLCV + IV + Stocks + COT US** sont déjà en prod (table `pl_contract_data_daily`) — pas de gap.
2. **Indicateurs techniques** : ses 15 colonnes [METHOD-TIED] sont identiques à `pl_derived_indicators`. Aligné.
3. **COT EU positioning** : table `pl_cot_eu_weekly` existe côté prod mais EXP-040 (GO partiel) suggère de mettre `cot_m_money_net_z_26w` en signal conditionnel sur le dashboard.
4. **ENSO MEI/ONI** : pas encore en prod. **À ajouter** : un scraper léger NOAA (Julien a déjà la version locale [enso_noaa.py](compass_backtest/optimizer_v3/scrapers/enso_noaa.py)) + table `pl_enso_monthly` + join_asof daily.
5. **ERA5 météo cocoa belt** : pas en prod. **À évaluer** : Copernicus CDS (vrai grid) coûte une clé API + cdsapi lib. V1 Open-Meteo (gratuit) suffit pour démarrer.
6. **Stocks EU LIFFE** : drop manuel chez Julien (`cocoa_cay00_stocks_bags60kg.csv`). À automatiser via scraper LIFFE/Barchart si on veut le pousser en prod.
7. **Sentiment LLM** : table `pl_article_segment` existe mais null rate >90% sur le sentiment score raw. Counts (`n_articles_*`) sont utilisables. À questionner avant d'investir produit.
8. **Fondamentaux internes** (Db_Master_*) : disparus du snapshot 20260517. Soit signal rejeté côté R&D (à confirmer avec Julien), soit oubli. Avant d'investir produit, savoir lequel.

---

## 8. Pour reproduire les expériences (commandes Julien)

```bash
# 1. Régénérer le core dataset depuis snapshot DB Hedi
python -m scripts.assemble_backtest_dataset
#   → écrit compass_backtest/data/rd_extract/cocoa_rd_dataset_YYYYMMDD.csv
#   → imprime le SHA256 (à pinner dans compass_backtest/config.py)

# 2. Placer manuellement les CSV NOAA ENSO sous compass_backtest/data/rd_extract/era5-et-enso/

# 3. Run baseline reference EXP-BT-000
python compass_backtest/baselines/naive.py

# 4. Run un experiment
python compass_backtest/experiments/exp049_era5_enso.py
```

Validation reproductibilité : run 2 fois, le CSV de sortie doit être byte-identique (modulo timestamps). Sinon il y a une fuite de seed.

---

## 9. Fichiers de référence (raccourcis)

| Sujet | Path |
|---|---|
| Vue d'ensemble du module | [compass_backtest/README.md](compass_backtest/README.md) |
| Config centrale (paths, seeds, seuils) | [compass_backtest/config.py](compass_backtest/config.py) |
| Dictionnaire de colonnes | [compass_backtest/data/rd_extract/cocoa_rd_dataset_20260512.dictionary.md](compass_backtest/data/rd_extract/cocoa_rd_dataset_20260512.dictionary.md) |
| Inventaire COT EU détaillé | [compass_backtest/data/cot_eu_lce/INVENTORY.md](compass_backtest/data/cot_eu_lce/INVENTORY.md) |
| Plan Optimizer V3 | [docs/OPTIMIZER_V3_PLAN.md](docs/OPTIMIZER_V3_PLAN.md) |
| Module ENSO join | [compass_backtest/data/enso_join.py](compass_backtest/data/enso_join.py) |
| Patterns chandelier | [compass_backtest/data/rd_extract/compute_pattern_features.py](compass_backtest/data/rd_extract/compute_pattern_features.py) |
| Labels T+6 + walk-forward purged | [compass_backtest/validation/labels.py](compass_backtest/validation/labels.py) |
| HMM 4 régimes | [compass_backtest/models/hmm.py](compass_backtest/models/hmm.py) |
| Baselines naïves + bootstrap BCa | [compass_backtest/baselines/naive.py](compass_backtest/baselines/naive.py) |
