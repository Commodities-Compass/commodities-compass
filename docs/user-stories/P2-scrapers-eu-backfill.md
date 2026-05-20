# EU Scrapers Backfill — Stock EU (14y) + ICE COT EU (3-5y)

**Statut :** Proposed (non implémenté)
**Date :** 2026-05-20
**Owner :** Hedi (déclenchement) — code review léger par le mainteneur courant
**Slug :** `scrapers-eu-backfill`
**Cible repo :** `docs/user-stories/P2-scrapers-eu-backfill.md`

---

## 1. Contexte

Les 2 scrapers EU **Palier 1+2 de la campagne 5** (cf. [P1-scrapers-stock-cot-eu.md](P1-scrapers-stock-cot-eu.md)) sont implémentés, testés et déployés via [palier 3](../onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md). Ils tournent quotidiennement et accumulent **1 row/jour** chacun en production :

```
cc-ice-cot-eu-scraper          (10 22 * * 1-5)  → pl_cot_eu_weekly       (1 row/semaine, snapshot mardi)
cc-barchart-stocks-eu-scraper  (10 19 * * 1-5)  → pl_contract_data_daily (stock_eu_bags60kg, daily)
```

**Problème** : le Campaign 5 ensemble consomme ces données comme features pré-normalisées (z-scores 26w + percentiles). Avec ~0 rows historiques en prod, les rolling windows seront **vides ou dégradées** pendant 6+ mois.

**Solution** : un backfill one-shot des deux sources, similaire à ce qu'on a déjà fait pour ENSO + FX (14y / 12y respectivement) en palier 1.

**Bonus** : 14 ans de Stock EU + 3-5 ans de COT EU disponibles pour la R&D (backtests régimes, validations multi-cycle).

---

## 2. Goals & non-goals

### Goals (cette itération)

- Backfiller `pl_contract_data_daily.stock_eu_bags60kg` sur **14 ans** (2012-02-07 → today)
- Backfiller `pl_cot_eu_weekly` sur **3 à 5 ans** (~2021 → today) — borne historique limitée par ICE qui ne publie que les fichiers récents
- Conserver l'idempotence (UPSERT) : re-run safe si interrompu

### Non-goals

- Pas d'instrumentation `is_backfill` (les rows historiques sont sémantiquement identiques aux rows daily)
- Pas de modification des scrapers existants — le backfill réutilise leur logique de parsing
- Pas de backfill ICE Stock US ni CFTC (déjà couverts par leurs scrapers daily depuis le début)

---

## 3. Données disponibles

### 3.1 Stock EU (Barchart cmdty)

- **First Value Date** observé sur la page Barchart : `2012-02-07` (14+ ans)
- **Format** : la page actuelle ne sert que les 7 derniers jours en HTML. Pour l'historique, deux options :
  - **A — API Barchart cmdtyStats** (paywall) : abonnement payant ~$$$/mois, hors-scope.
  - **B — Scrape paginé via le sélecteur de période de la page** : la page a probablement un endpoint XHR qui sert l'historique. **Spike 0.5j requis** pour valider.
  - **C — Wayback Machine (web.archive.org)** : snapshots historiques de la page Barchart, parser daily les valeurs visibles. Lent (~14y × 365 = 5000 requêtes), risque rate-limit.
- **Recommandation** : essayer B en premier ; fallback C si la page ne sert pas d'historique sans auth.

### 3.2 ICE COT EU (ICE public CSV)

- **Source** : `https://www.theice.com/publicdocs/futures/COTHist{year}.csv` (1 fichier par année).
- **Profondeur** : ICE conserve les fichiers ~5 ans en accès public. À vérifier en spike : essayer `COTHist2020.csv`, `COTHist2019.csv` etc. jusqu'à 404.
- **Format** : identique au scraper existant — réutilisation directe de `parse_ice_cot_csv()`.
- **Volume estimé** : ~52 weeks × 5 years × 1 cocoa row = **~260 rows** (trivial).

---

## 4. Implementation plan

### 4.1 Stock EU backfill — module `scripts/barchart_stocks_eu_scraper/backfill.py`

**Strategy A (preferred — Barchart history endpoint)** :
1. Spike : ouvrir DevTools sur la page IC345DRW.CS, identifier l'endpoint XHR qui sert l'historique quand on change la période.
2. Si endpoint trouvé : implémenter `fetch_history(start_date, end_date)` qui retourne `list[StockEuHistoryRow]`.
3. Pour chaque date : `UPDATE pl_contract_data_daily SET stock_eu_bags60kg = :v WHERE date = :d`.
4. Fail-loud sur 404 / rate-limit. **Pas** de retry automatique (cf. `pipeline-error-handling.md`).
5. **Important** : la row OHLCV doit exister pour chaque date. Si gap (jour non-trading EU mais trading US, par exemple) → soit on accepte de NOT update, soit on étend le `barchart-scraper` backfill avant.

**Strategy B (fallback — Wayback Machine)** :
1. Pour chaque date : `https://web.archive.org/web/{date}/https://www.barchart.com/cmdty/data/fundamental/explore/IC345DRW.CS`
2. Parser le HTML snapshot avec le `parser.py` existant (compatible si Barchart n'a pas changé sa structure ces 14 ans — à vérifier).
3. Throttle ~1 req/sec (Wayback est généreux mais pas illimité).

**CLI** : `poetry run barchart-stocks-eu-scraper-backfill [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--strategy {history,wayback}] [--dry-run] [--verify]`

### 4.2 COT EU backfill — module `scripts/ice_cot_eu_scraper/backfill.py`

Trivial — réutilise le scraper existant :

```python
def main():
    for year in range(2026, 2018, -1):  # adjust upper bound after spike
        try:
            observations = scrape_year(year)
        except IceCotEuScraperError as e:
            if "HTTP 404" in str(e):
                logger.info("Year %d not available — backfill complete", year)
                break
            raise
        with get_session() as session:
            upsert_cot_eu_rows(session, observations)
            session.commit()
```

**CLI** : `poetry run ice-cot-eu-scraper-backfill [--start-year YYYY] [--dry-run] [--verify]`

### 4.3 Verify mode

Pour les deux : `--verify` lit la DB après le backfill et vérifie :
- Pas de trou > 7 jours dans Stock EU (sauf weekends / EU holidays)
- ≥ 52 rows par année dans pl_cot_eu_weekly (≥ 50 pour tolérer weeks skipped)
- Pas de NULL sur les colonnes critiques (open_interest, m_money_long, m_money_short pour COT)

### 4.4 Tests

- Reuse des fixtures existantes (`tests/test_ice_cot_eu_scraper.py` + `tests/test_barchart_stocks_eu_scraper.py`)
- **~10 tests** par module backfill : iteration over years, 404 handling (Stock COT EU stop condition), verify mode, idempotence (re-run same date noop).

---

## 5. Acceptance criteria

- [ ] Spike Barchart history endpoint terminé (décision strategy A vs B)
- [ ] `poetry run ice-cot-eu-scraper-backfill --dry-run` log les années disponibles + count
- [ ] `poetry run ice-cot-eu-scraper-backfill --verify` PASS sur prod après run (≥ 200 rows total dans `pl_cot_eu_weekly`)
- [ ] `poetry run barchart-stocks-eu-scraper-backfill --verify` PASS sur prod (≥ 3000 rows avec `stock_eu_bags60kg IS NOT NULL` dans `pl_contract_data_daily`)
- [ ] Tests unitaires backfill ≥ 90% coverage (~20 tests total)
- [ ] Pas de modification des scrapers daily (séparation backfill / daily, conformément aux backfills ENSO + FX)
- [ ] Run en prod via bastion tunnel (procédure standard, cf. `docs/runbooks/db-sync-from-gcp.md`)

---

## 6. Risques

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| Barchart bloque les requêtes répétées (rate-limit, captcha) | Moyenne | Élevé (bloque backfill complet) | Throttle 1 req/sec, fallback Wayback Machine, User-Agent réaliste |
| ICE retire les fichiers > 5 ans | Élevée | Faible (couvre quand même 3-5 ans, suffisant pour rolling 26w) | Documenter dans la US les années manquantes |
| HTML Barchart historique a une structure différente (parser breaks) | Moyenne | Moyen | Tests sur 1 année avant lancer 14 ans ; fail-loud sur format drift |
| Run prod long (~10h pour Stock EU strategy A, ~30h pour B Wayback) | Moyenne | Faible (one-shot, non-blocking) | Lancer en heures creuses, log progress toutes les N rows |
| Trous OHLCV (jour US trading non-EU) | Faible | Moyen (UPDATE échoue silencieusement → 0 rows) | Logger les `StockEuRowMissingError` count à la fin du backfill |

---

## 7. Estimation

| Phase | Effort |
|---|---|
| Spike Barchart history endpoint | 0.5j |
| Stock EU backfill module + tests | 1.5j |
| ICE COT EU backfill module + tests | 0.5j |
| Run prod + verify | 0.5j |
| **Total** | **~3j** |

---

## 8. Dependencies

- ✅ Palier 1 ICE COT EU scraper (commit `982fd49`)
- ✅ Palier 2 Stock EU scraper (commit `be2510c`)
- ✅ Palier 3 deploy + scheduler (CET US — cette PR)
- 🔄 Apply terraform en prod pour activer les crons (manuel, Hedi)

---

## 9. Out of scope

- ❌ Backfill ICE Stock US et CFTC (déjà couverts par leurs scrapers daily depuis le début)
- ❌ Activation du signal C5 sur le composite — c'est l'ensemble qui décide, pas le scraper backfill
- ❌ Validation R&D des données backfillées (Jhules / Julien review post-backfill)
- ❌ Stockage des fichiers ICE CSV brut pour audit (les rows DB suffisent ; les CSV peuvent être re-fetchés à l'identique)
