# Optimizer — recap weekend 2026-05-17

## 1. Ce que fait Optimizer

**Mission unique** : produire en continu le meilleur algorithme de décision quotidien
**OPEN / HEDGE / MONITOR** pour le cacao London (LCE), et le remplacer dès qu'il
décroche. Pas une plateforme, pas un produit — un outil de recherche industrialisé.

**Postulat fondateur** : un algo reste calibré ~100 jours sur ce marché avant que les
régimes dérivent. Avant Optimizer, Julien re-fittait à la main chaque 15-30 jours
(cycle V6→V7→V8, profils TURBO / ELITE / AGGRESSIF / OVERNIGHT). Optimizer V3
industrialise ce cycle :

```text
Phase 1 — SÉLECTION                   Phase 2 — FORMULE
parmi 44 critères tech + fondam.      Z = f(critères, structure, params)
quels portent du signal sur la        optim. Random/Optuna TPE +
fenêtre courante (~100 j) ?           walk-forward purgé OOS
↓                                     ↓
sous-ensemble + classement de         algo candidat (Product /
stabilité                             SumOfProducts / PoweredSum /
                                      Modular / RegimeConditional)
└─────────────── fenêtre glisse ──────────────────────────────────┘
                la boucle tourne en continu
```

**Cibles 2025** (signature trader ELITE V8 assouplie) :

| Métrique | Cible |
|---|---|
| Taux de réussite (`perf_rate`) | > 78 % |
| Signaux à contresens (`false_signal_rate`) | < 10 % |
| Rendement décisionnel net (`total_accuracy`) | > 25 % |
| Couverture (`coverage`) | 25 – 75 % |
| Sharpe | > 1.0 |

---

## 2. Résultats du weekend 2026-05-16 / 17

### Pipeline livré (4 commits sur `clean-v3`)

| Hash | Titre | Effet |
|---|---|---|
| `f667c41` | Cockpit V4 cockpit-pilote complet | 4 onglets API-réels (Auto · Historique · Readiness · Méthode), logos Compass, modal Colab fonctionnel, Telegram alerte composite ≥ 0.88 |
| `199c5a6` | Scrapers locaux + DB legacy SQLite | Autonomie totale vs Hedi sur OHLCV LCE, COT, ENSO, ERA5. Read-path legacy-first, fallback Parquet Hedi |
| `cd90222` | Sentiment LLM (Phase 6) + fixes | Scraper Claude Haiku sur RSS publics, `is_business_day_lce` via ref_trading_calendar, extract_rd_dataset legacy-compat |
| `ea1d748` | Plist launchd `com.compass.optimizer.daily` | Orchestrateur 19h Paris jours ouvrés (skip weekend + fériés UK automatique) |

### État de la legacy DB locale (`data/legacy_db/optimizer.sqlite`)

| Table | Rows | Max date | Source |
|---|---|---|---|
| `pl_contract_data_daily` | 2 611 | **2026-05-15** (+4j vs Hedi) | Barchart Playwright |
| `pl_derived_indicators` | 2 611 | 2026-05-15 | Recalcul local depuis OHLCV |
| `pl_cot_eu_weekly` | 76 | 2026-05-12 | ICE Europe public CSV |
| `pl_cot_us_weekly` | 57 | 2026-05-12 | CFTC.gov ZIP |
| `pl_enso_monthly` | 916 | mars 2026 (ONI), avril 2026 (MEI) | NOAA CPC + PSL |
| `pl_era5_daily` | 68 | **2026-05-17 (today)** | Open-Meteo, 4 zones cocoa belt |
| `pl_article_segment` (sentiment) | 723 historiques + 15 frais | 2026-05-17 | Claude Haiku sur RSS Google News + Cocoa Post |

### 3 BestX en Readiness (surveillance live 5 jours vs ACTUAL)

| ID | Structure | target_window | Composite à l'ajout | Status |
|---|---|---|---|---|
| Best 1 | Product | 200 | 0.9518 | live, 1 eval (TEST=HEDGE vs ACTUAL=OPEN au 11/05) |
| Best 2 | SumOfProducts | 50 | 0.9500 | live, 1 eval |
| Best 3 | Modular | 50 | 1.0000 | live, 1 eval |

J+5 du 11/05 = 18/05 (lundi prochain) → premier PnL réalisé évaluable. Si TEST bat
ACTUAL 5/5 jours consécutifs → Telegram automatique « READY pour prod ».

### Signal marché capté par les scrapers (semaine 11-15/05)

- **LCE close** : 3484 → 3431 → 3272 → 3110 → 3040 (baisse -13% sur 5 sessions)
- **COT Money Manager EU net** : -31k (mi-avril) → -20k (05/05) → **-11k (12/05)** (short covering massif sur le rally)
- **Money Manager US net** : -10k stable, moins extrême
- **Sentiment LLM agrégé** : +0.45 (rally 05/05) → +0.30 (sommet 11/05) → **-0.80 (14/05)** → -0.01 (15/05 mix)
- **Météo cocoa belt** : 26-28°C, précip variable 0.4-14mm/j (saison pluies CI/Ghana qui se rétablit progressivement)
- **ENSO** : ONI +0.11 (neutral), MEI -0.64

→ Cohérence trader : LLM a parfaitement capté le pivot bullish→bearish entre le
13 et 14 mai, en avance d'un jour sur la clôture.

---

## 3. Ce qu'on attend encore de Hedi

### Bloquant moyen (V1.1 — 2-3 semaines)

| Sujet | Détail | Pourquoi |
|---|---|---|
| **Tax customs CI + Achats + Grainage** | Excels `Db_Master_Tax.xlsx`, `Db_Master_Achats.xlsx`, `Bilan_Grainage` | Fondamentaux internes Compass non scrapables. Dataset perd 20+ colonnes sans eux. Carry-forward 2 mois acceptable mais idéalement push hebdo. |
| **Snapshot DB rafraîchi** | Cf `docs/SNAPSHOT_REFRESH.md` | Couvre les tables Hedi-only : `pl_sentiment_feature`, `pl_signal_component` (ACTUAL legacy 1.0.1), `pl_seasonal_score`. Cadence actuelle ad-hoc, idéalement hebdo. |
| **Stocks ICE EU (`stock_eu_bags60kg`)** | Colonne ajoutée à `pl_contract_data_daily` mais non encore en prod | Permettrait de fermer la boucle stocks (US + EU). |

### Pas bloquant (V1.2 — quand t'as le temps)

| Sujet | Détail |
|---|---|
| **Prédiction J+1 dans le cockpit** | Cf `docs/NOTE_HEDI_2026-05-16.md` § 1. Besoin de confirmation cycle de rafraîchissement dataset + politique carry-forward des fondamentaux. |
| **Inventaire scraps Com Compass** | Cf `docs/NOTE_HEDI_2026-05-16.md` § 2. Si Com Compass scrape des sources avec délai < 1 jour, ce serait des candidats pour enrichir le dataset Optimizer V1.3. |
| **Calendar spread H/K** | Nécessite snapshot multi-contrats simultanés dans `pl_contract_data_daily` (actuellement 1 row/date). |

### Découplé — fait localement (S8 livrée)

- LCE OHLCV daily : **scrappé local Barchart Playwright**.
- COT EU + US : **scrappé local ICE Europe + CFTC.gov public ZIPs**.
- ENSO ONI + MEI : **scrappé local NOAA**.
- Météo cocoa belt : **Open-Meteo daily, 4 zones CI/Ghana**.
- Sentiment LLM : **scrappé local Google News RSS + Claude Haiku** (coût ~$0.02/jour).
- Recalcul indicateurs techniques (RSI/MACD/ATR/etc.) : **local depuis OHLCV**.
- Calendrier trading UK : **`ref_trading_calendar` (snapshot Hedi)**.

→ **Le moteur tourne en mode autonome.** Si Hedi décroche complètement, Optimizer
reste fonctionnel sur 38/44 critères du registre.

---

## 4. Comment Hedi peut se connecter et recevoir les Telegram

### Recevoir les Telegram du bot Compass

Le bot Telegram envoie déjà 3 types de notifications :

| Évènement | Trigger | Payload |
|---|---|---|
| **Nouveau best** | `continuous_optimizer` détecte un composite > seuil + ratio sain | Composite, structure, target_window, critères, métriques OOS, verdict /trader 4 niveaux (CHAMPION / VIABLE / MARGINAL / NOISE) |
| **Composite remarquable** | Composite ≥ 0.88 même si pas best officiel | Idem, marqué `📊 COMPOSITE REMARQUABLE` |
| **Dérive prod** | `drift_watcher` détecte que `perf_rate` ACTUAL chute sous 70 % sur 5 j glissants | Alerte re-fit immédiat hors planning |
| **Ready for prod** | BestX bat ACTUAL 5/5 jours consécutifs sur marché réel | « 🚀 BestX READY pour prod » avec analyse /trader |

**Pour que Hedi reçoive aussi** :

1. **Cas 1 — même chat group** : si le bot envoie déjà dans un groupe Telegram, Hedi
   rejoint le groupe (lien d'invitation depuis Julien).
2. **Cas 2 — chat individuel** :
   - Hedi cherche `@CompassOptimizerBot` (ou nom du bot, à confirmer côté Julien)
   - Envoie `/start` au bot
   - Le bot répond avec son `chat_id` Telegram (ex : `1234567890`)
   - Hedi communique ce `chat_id` à Julien
   - Julien ajoute dans `.env` : `TELEGRAM_CHAT_ID_HEDI=1234567890`
   - Julien fait évoluer le code pour broadcast multi-chat (modif simple
     `notifications.py` : list au lieu de single chat_id)

Setup détaillé : `docs/SETUP_TELEGRAM.md` (5 min via @BotFather si nouveau bot).

### Se connecter à l'iMac (lire le state Optimizer)

Le moteur tourne 24/7 sur l'iMac de Julien (4 services launchd) :

```text
com.compass.optimizer.api          API Flask :5005 (cockpit + endpoints)
com.compass.optimizer.continuous   Boucle d'optimisation (Optuna TPE, ~150 runs/jour)
com.compass.optimizer.drift        Détecteur de dérive prod (poll 5 min)
com.compass.optimizer.daily        Orchestrateur S8 (scrape + eval Readiness, 19h Paris)
```

**Options pour Hedi** :

- **Option A — observateur git** : `git pull` régulier + lecture des fichiers
  `data/algos/test_current.json`, `data/algos/last_daily_update.json`, `data/readiness/*.json`.
  Pas de SSH iMac requis, donne le state à un instant T.
- **Option B — accès SSH iMac via Tailscale** : si Hedi est sur le réseau Tailscale
  COMPASS, `ssh julienmarboeuf@macju` après ssh-copy-id (clé publique installée).
  Permet d'inspecter logs live, restart services, etc.
- **Option C — Cockpit en navigateur** : `http://macju.<tailscale-name>.ts.net:5005`
  via Tailscale Funnel (à exposer côté Julien — actuellement local only). Vue
  graphique des 4 onglets, mêmes données que Julien.

### Documents de référence

- `CLAUDE.md` — vision Optimizer + cibles + filiation V8→V3 + rigueur statistique
- `docs/OPTIMIZER_V3_PLAN.md` — plan d'architecture du moteur
- `docs/SETUP_TELEGRAM.md` — config bot Telegram
- `docs/SNAPSHOT_REFRESH.md` — procédure refresh DB snapshot (Hedi-only)
- `docs/PLAN_SCRAPS_IN_OPTIMIZER.md` — plan d'implémentation S8 (livré)
- `docs/NOTE_HEDI_2026-05-16.md` — demandes prédiction J+1 + scraps Com Compass
- `tasks/todo.md` — workplan vivant, état réel de l'avancement

---

## 5. TL;DR

- Optimizer V3 est **autonome côté data** depuis ce weekend (S8 livrée).
- 3 BestX en surveillance Readiness vs ACTUAL, premiers PnL J+5 attendus 18-19 mai.
- Sentiment LLM **capte le pivot du marché** : bullish jusqu'au 13/05, bearish 14-15/05.
- LCE a perdu -13 % cette semaine (3484 → 3040 £/t). COT MM short coverant.
- **Bascule iMac en cours** ce 17/05 (launchd plist daily à activer).
- **Attendu Hedi** : Tax/Achats/Grainage, snapshot refresh régulier, stocks EU.
- **Telegram Hedi** : envoie /start au bot, communique chat_id à Julien.
