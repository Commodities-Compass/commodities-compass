# Press Review Backfill — 10 ans d'historique pour activation anticipée du signal sentiment

**Statut :** Proposed (non implémenté)
**Date :** 2026-05-12
**Owner :** TBD
**Slug :** `press-review-backfill-10y`
**Cible repo :** `docs/user-stories/P1-press-review-backfill-10y.md`

---

## 1. Contexte

Le `press_review_agent` tourne quotidiennement depuis quelques semaines. Sa sortie alimente une chaîne mode-shadow qui n'est pas encore branchée au composite signal :

```
press_review_agent (daily cron)
  → pl_fundamental_article (1 row/jour)
  → pl_article_segment (~4 rows/jour, 1 par thème : production / chocolat / transformation / economie)
  → compute_sentiment_features (rolling 21j z-score + delta 3j)
  → pl_sentiment_feature (~4 rows/jour)
  → [NON BRANCHÉ AU COMPOSITE] — activation prévue ~octobre 2026 quand n > 250
```

**Validation statistique préalable** : EXP-014 a établi que `zscore_delta` (rolling 21j, delta 3j) préserve un signal Granger exploitable (production p=0.017, chocolat p=0.025). L'instrumentation est correcte ; c'est l'accumulation naturelle qui prend ~5 mois supplémentaires.

**Problème** : à raison de ~1 row/jour, atteindre n > 250 sans accélération signifie attendre octobre 2026 (~5 mois). Pendant ce temps, le signal sentiment ne contribue pas aux décisions du composite.

**Opportunité** : un backfill historique via GDELT permet d'accumuler 2500+ jours en quelques jours de calcul. Coût LLM ~$60 (o4-mini), confiance moyenne-haute. Bonus : 10 ans d'historique disponibles pour des backtests futurs (régimes ENSO, crises supply, cycles demande, etc.).

**Pourquoi maintenant** : ne pas attendre octobre pour avoir un signal qui existe déjà statistiquement. Le backfill est un investissement one-shot.

---

## 2. Goals & non-goals

### Goals (cette itération)

- Backfiller `pl_fundamental_article` + `pl_article_segment` sur 10 ans (2016-05-12 → 2026-04-30) via GDELT 2.0
- Permettre l'activation du signal sentiment **dès maintenant** au lieu d'octobre 2026
- Conserver une traçabilité explicite des rows backfillées via une nouvelle colonne `is_backfill`
- Architecture **isolée** du `press_review_agent` prod (ZÉRO modification du code prod du press review)
- Module **one-shot** : code supprimable après run + validation
- Bonus : disponibilité de 10 ans d'historique sentiment pour backtests futurs

### Non-goals

- Activation du signal sentiment dans le composite signal (algo v1.0.2) — **PR séparée** après validation Phase 4
- Modifications du `press_review_agent` prod (config, prompt, scrapers, db_writer)
- Backfill des autres tables (`pl_weather_observation`, `pl_indicator_daily`, etc.)
- Nouveau Cloud Run Job ou cron (le backfill est un script local one-shot)
- Nouvelle UI dashboard
- Suppression de la colonne `is_backfill` après run (utile pour audit ; à conserver)

---

## 3. Diagnostic & bottleneck

Le pipeline de production est :

```
articles (8 sources live) → LLM (o4-mini) → pl_article_segment → compute_sentiment_features → pl_sentiment_feature
```

**Le seul élément non-déterministe à backfiller est `pl_article_segment`**. À partir de là, `compute_sentiment_features` reconstruit `pl_sentiment_feature` de façon déterministe (`poetry run compute-sentiment-features`).

**Bottleneck identifié** : les 8 sources actuelles ne sont PAS archivables :
- Investing, CocoaIntel, ICCO, Confectionery News, Abidjan.net, Cacao.ci, The Cocoa Post, Agence Ecofin → scrapées en mode "page courante", pas d'API archive
- Google News RSS → fixé à `when:3d`

**Solution** : remplacer le fetcher live par un fetcher historique GDELT 2.0 dans un module isolé.

---

## 4. Source GDELT 2.0

**API** : `https://api.gdeltproject.org/api/v2/doc/doc`

**Paramètres** :
- `query=cocoa OR cacao`
- `startdatetime=YYYYMMDDHHMMSS&enddatetime=YYYYMMDDHHMMSS`
- `sourcelang:eng,fre`
- `format=json&maxrecords=75`
- Optionnel : `theme:ECON_COMMODITIES`

**Caractéristiques** :
- Free, no API key, rate-limit pratique ~5 req/s
- Retourne URLs + titres + tone scores GDELT (ignorés, on garde notre LLM existant)
- Couvre : Reuters, Bloomberg, Investing.com, AFP, AP, Confectionery News, ICCO press releases
- Couvre mal : Cacao.ci, Abidjan.net, Agence Ecofin (~15% des sources live actuelles)

**Caveat couverture temporelle** :

| Période | Couverture | Skip rate attendu |
|---|---|---|
| 2018-2026 (8 ans) | HAUTE — volume cocoa robuste | < 2% |
| 2016-2018 (early v2.0) | MOYENNE — volume ~50-70% de 2024+ | 5-10% (dates avec < 3 articles → skip) |
| Pre-2016 | Non recommandé (ramp-up GDELT 2.0 incomplet) | N/A |

**Estimation finale** : sur 2500 trading days candidats, ~2250-2500 rows valides après skip.

**Window de fetch par jour** : `[session_date 00h UTC → session_date+1 18h UTC]` — capte les articles jusqu'au close ICE Europe (18h UTC), anti look-ahead bias.

---

## 5. Architecture : module isolé

### 5.1 Principe d'isolation

```
backend/scripts/
├── press_review_agent/         # PROD — INTACT, NON MODIFIÉ
│   ├── main.py
│   ├── config.py
│   ├── llm_client.py
│   ├── validator.py
│   ├── news_fetcher.py
│   └── db_writer.py
│
└── press_review_backfill/      # NEW — one-shot, supprimable après run
    ├── README.md
    ├── main.py                 # CLI orchestrateur
    ├── gdelt_fetcher.py        # GDELT 2.0 client
    ├── context_resolver.py     # close + contract historique
    ├── writer.py               # INSERT direct (is_backfill=TRUE)
    └── tests/
        ├── test_gdelt_fetcher.py
        └── test_context_resolver.py
```

### 5.2 Imports autorisés depuis prod (read-only)

Le module backfill peut importer ces symboles de `press_review_agent/` :
- `config.SYSTEM_PROMPT` (system prompt LLM, ne change pas pour le backfill)
- `config.USER_PROMPT_TEMPLATE` (date-agnostic, confirmé)
- `llm_client.OpenAIClient` (réutiliser tel quel)
- `validator.validate_output` (réutiliser tel quel)

**Si quelqu'un refactor `config.py` ou bouge ces symboles, le backfill peut casser** — c'est OK puisque c'est one-shot et exécuté une seule fois avant suppression.

### 5.3 Interdictions explicites pour le module backfill

- ❌ Modifier `press_review_agent/`
- ❌ Ajouter une dépendance au pipeline cron (Cloud Run Jobs)
- ❌ Exposer un endpoint API
- ❌ Être déployé en Cloud Run Job
- ❌ Toucher `compute_sentiment_features` (le filtre `extraction_version="inline_v1"` capte automatiquement les rows backfillées car on tag avec le même `extraction_version`)

---

## 6. Schéma DB

### 6.1 Migration : `is_backfill` column

Migration Alembic dans `backend/alembic/versions/<rev>_add_is_backfill_column.py` :

```sql
ALTER TABLE pl_fundamental_article
  ADD COLUMN IF NOT EXISTS is_backfill BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS ix_pl_fundamental_article_is_backfill
  ON pl_fundamental_article(is_backfill) WHERE is_backfill = TRUE;

ALTER TABLE pl_article_segment
  ADD COLUMN IF NOT EXISTS is_backfill BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS ix_pl_article_segment_is_backfill
  ON pl_article_segment(is_backfill) WHERE is_backfill = TRUE;
```

**Idempotente** (`IF NOT EXISTS`), **non-breaking** (`DEFAULT FALSE` → lectures existantes inchangées), partial index sur `WHERE is_backfill = TRUE` (économe).

### 6.2 Modèles SQLAlchemy

Étendre `PlFundamentalArticle` et `PlArticleSegment` dans `backend/app/models/pipeline.py` :

```python
is_backfill: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

**Pas de modification** d'autres champs, contraintes, ou index existants.

### 6.3 Rows backfillées : tagging

Chaque row backfillée porte :
- `is_backfill=TRUE` (nouveau)
- `is_active=TRUE` (cohérence dashboard — l'utilisateur a validé ce choix)
- `extraction_version="inline_v1"` (identique au live → `compute_sentiment_features` capte sans modif)
- `llm_provider="openai"` (production provider)
- `llm_model="o4-mini-2025-..."` (snapshot date du run)
- `source="GDELT (backfill)"` (distingue dans `pl_fundamental_article.source`)

---

## 7. Module : `backend/scripts/press_review_backfill/`

### 7.1 `context_resolver.py`

```python
@dataclass(frozen=True)
class BackfillContext:
    session_date: date
    close: float                 # GBP/tonne
    contract_code: str           # ex: CAN26
    contract_month: str          # ex: 2026-07

def resolve_context(session: Session, session_date: date) -> BackfillContext | None:
    """Lookup close + contract from pl_contract_data_daily for a historical date.

    Returns None if no data is available for that date (skip with warning).
    """
```

Logique :
- `SELECT close, contract_id FROM pl_contract_data_daily WHERE date = ? ORDER BY oi DESC NULLS LAST LIMIT 1` (front-month proxy via OI maximum)
- JOIN `ref_contract` pour récupérer `code` et `delivery_month`
- Si pas de row → return None → orchestrateur skip la date avec log warning

### 7.2 `gdelt_fetcher.py`

```python
@dataclass(frozen=True)
class GdeltArticle:
    url: str
    title: str
    seendate: datetime           # UTC
    source_domain: str
    excerpt: str | None          # GDELT snippet

async def fetch_articles_for_date(
    session_date: date,
    max_articles: int = 40,
    languages: tuple[str, ...] = ("eng", "fre"),
) -> list[dict]:
    """Returns articles in the format expected by USER_PROMPT_TEMPLATE.

    Pipeline:
    1. Query GDELT for query=cocoa OR cacao, langs, window [00:00 → +1 18:00 UTC]
    2. Filter: seendate ≤ session_date 18h UTC (anti look-ahead)
    3. Dedup by domain + Jaccard title similarity > 0.8
    4. Fetch content async (httpx, timeout 5s, max 40 articles, skip échecs)
    5. Fallback: si fetch URL 404, garder title + excerpt comme contenu minimal
    6. Skip date entière si < 3 articles → return [] + log warning

    Returns list[dict{title, content, url, source}] ready for prompt injection.
    """
```

### 7.3 `writer.py`

```python
def write_backfill(
    session: Session,
    ctx: BackfillContext,
    sources: list[dict],
    llm_payload: dict,             # validated output: resume, mots_cle, impact_synthetiques, theme_sentiments
    force_replace: bool = False,
) -> None:
    """INSERT pl_fundamental_article + pl_article_segment with is_backfill=TRUE.

    If (date, llm_provider="openai") already exists:
      - force_replace=False → skip with log info (idempotent)
      - force_replace=True  → DELETE existing then INSERT
    """
```

### 7.4 `main.py` (CLI)

```bash
poetry run press-review-backfill \
  --start 2016-05-12 \
  --end 2026-04-30 \
  [--dry-run] \
  [--limit N] \
  [--force-replace] \
  [--concurrency 3] \
  [--verbose]
```

**Comportement** :
- Itère sur business days entre `--start` et `--end` via lookup `ref_trading_calendar` (skip weekends + holidays ICE Europe)
- Pour chaque date : `resolve_context` → `fetch_articles` → render prompt → `OpenAIClient.call()` → `validate` → `write_backfill`
- **Concurrency** : N dates en parallèle (default 3, max 5) avec semaphore — respecte rate-limit OpenAI + GDELT
- **Resume** : si crash, relance via `--start <last_processed_date>` (idempotent par défaut)
- **Logs métriques** : `articles/jour moyen`, `taux succès LLM`, `coût cumulé estimé`, `ETA` toutes les 50 dates
- **Soft cap coût** : warning à $100, hard stop à $150

### 7.5 `README.md`

Document la procédure complète :
1. Comment lancer (commandes)
2. Comment valider les résultats (queries SQL)
3. **Procédure de cleanup** :
   - Cleanup code : `rm -rf backend/scripts/press_review_backfill` + remove poetry script
   - Cleanup data (optionnel, si rejet) : `DELETE FROM pl_* WHERE is_backfill=TRUE` + recompute features
   - **Ne pas dropper** `is_backfill` column par défaut (utile pour audit)

---

## 8. Choix délibéré : pas de modif à `compute-sentiment-features`

`backend/scripts/compute_sentiment_features/main.py` filtre déjà sur `extraction_version="inline_v1"`. Le backfill écrit avec ce même tag → la query d'agrégation capte automatiquement les segments backfillés. **Aucune modification nécessaire**.

`is_backfill` sert uniquement à l'audit + cleanup éventuel, pas à filtrer dans le pipeline analytique.

---

## 9. Plan d'exécution (4 phases)

### Phase 1 — Migration + setup module (~0.5 jour)

1. Migration Alembic `add_is_backfill_column` (idempotente)
2. Étendre `PlFundamentalArticle` + `PlArticleSegment` (`is_backfill: Mapped[bool]`)
3. Squelette `backend/scripts/press_review_backfill/` (fichiers vides + README initial)
4. Entry-point poetry dans `backend/pyproject.toml`
5. Test migration local : `poetry run alembic upgrade head` → vérifier colonnes + index
6. Smoke test : `SELECT * FROM pl_fundamental_article LIMIT 1` → vérifier non-régression dashboard

### Phase 2 — GDELT fetcher + context resolver (~1 jour)

**TDD léger** : 1 test par fonction critique, mocks HTTP.

1. `context_resolver.resolve_context(date)` + tests :
   - Date normale avec data
   - Date sans data → return None
   - Date avec roll de contrat (multiple contract_id ce jour-là) → choisir front-month
2. `gdelt_fetcher.fetch_articles_for_date(date)` + tests :
   - Mock GDELT response : vide / cocoa-rare-day / cocoa-busy-day
   - Mock content fetch : 200 OK / 404 / timeout / cloudflare-block
   - Anti-leakage : article avec `seendate=2025-06-15 23h` filtré pour `session_date=2025-06-15`
   - Skip date si < 3 articles

### Phase 3 — Orchestrateur + writer + run (~1 jour)

1. `writer.write_backfill(...)` + tests :
   - INSERT nominal
   - Skip silencieux si row existante (default)
   - DELETE + INSERT si `force_replace=True`
2. `main.py` CLI :
   - Itération business days
   - Concurrency avec semaphore
   - Logs métriques + ETA
   - Soft cap / hard stop coût
3. **Run progressif** (sécurité) :
   - 3a : `--dry-run` sur 5 dates → vérifier articles GDELT + prompt rendu
   - 3b : run réel sur 30 jours récents en DB locale → inspection manuelle
   - 3c : run sur 1 an en DB locale → vérifier perf + coût estimé
   - 3d : run sur 10 ans complets → ~20-30h runtime avec concurrency=3

### Phase 4 — Validation (~1 jour)

1. **Smoke test corrélation backfill vs live** :
   - 5 dates récentes avec live rows (`is_backfill=FALSE`)
   - Run backfill avec `extraction_version="backfill_compare_v1"` (label temporaire, ne pas écraser le live)
   - Comparer segment scores par thème : corrélation Pearson > 0.5 → GO ; < 0.3 → STOP, itérer
   - Cleanup : `DELETE FROM pl_article_segment WHERE extraction_version='backfill_compare_v1'`
2. **Sanity check qualitatif** sur 3 dates avec événements connus :
   - 2024-04 forte hausse prix cocoa
   - 2025-09 ICCO supply alert
   - 2026-02 mouvement majeur
   - Vérifier manuellement `summary`, `mots_cle`, `impact_synthetiques`
3. **Validation rolling z-score** post-backfill complet :
   ```bash
   poetry run compute-sentiment-features --dry-run
   # vérifier : n par thème ≥ 2250, distribution zscore_delta centrée 0, std ~0.5-1.5
   ```
4. **Décision GO/NO-GO documentée** dans `docs/decisions/2026-XX-XX-press-review-backfill.md` :
   - Métriques corrélation par thème
   - Coût LLM réel
   - Taux d'échec par date
   - Distribution skip rate par ère (2016-2018 vs 2018-2026)
   - Recommandation Phase 5 (PR séparée pour activation algo v1.0.2)

---

## 10. Procédure de cleanup (one-shot)

Documentée dans `press_review_backfill/README.md`.

### 10.1 Cleanup du code (post-validation + post-Phase 5)

```bash
rm -rf backend/scripts/press_review_backfill
# Editer backend/pyproject.toml pour retirer l'entry-point press-review-backfill
git rm -r backend/scripts/press_review_backfill
```

### 10.2 Cleanup de la data (OPTIONNEL — uniquement si rejet ou re-run)

```sql
DELETE FROM pl_article_segment WHERE is_backfill = TRUE;
DELETE FROM pl_fundamental_article WHERE is_backfill = TRUE;
```

Puis :

```bash
poetry run compute-sentiment-features  # recompute pl_sentiment_feature propre
```

### 10.3 Cleanup du schéma (FACULTATIF — déconseillé)

La colonne `is_backfill` est utile à terme pour audit + future possibilité de distinguer dans le dashboard. **Ne pas la dropper par défaut**. Si décision contraire, créer une migration `drop_is_backfill_column` dédiée.

---

## 11. Niveau de confiance attendu

| Dimension | Confidence | Justification |
|---|---|---|
| Événements majeurs (récolte, ICCO, prix shock) | **HAUTE (80-90%)** | GDELT capte bien les wires (Reuters, Bloomberg, AFP) |
| Direction du sentiment par thème (bullish/bearish) | **MOYENNE-HAUTE (70-80%)** | Direction généralement correcte, magnitude bruitée |
| Magnitude / nuance fine | **MOYENNE (50-70%)** | Sources africaines spécialisées sous-représentées (~15%) |
| Couverture GDELT 2018-2026 (8 ans) | **HAUTE** | Volume mainstream stable, sources EN/FR bien indexées |
| Couverture GDELT 2016-2018 (early v2.0) | **MOYENNE** | Volume cocoa ~50-70% du 2024+, skip rate 5-10% attendu |
| Validité statistique du z-score rolling | **TRÈS HAUTE (90%+)** | Avec ~2250-2500 jours valides, n très largement > 250, fenêtre rolling 21j auto-normalise |
| **Contribution nette au composite signal** | **MOYENNE-HAUTE (65-75%)** | Direction préservée + grande quantité de données pour calibration |

**Pourquoi "good enough"** :
- Métrique consommée = `zscore_delta`, pas `raw_score` absolu → normalisation rolling 21j supprime les biais de niveau entre backfill et live
- EXP-014 a prouvé qu'un signal existe ; le backfill accélère l'accumulation + bonus 10 ans pour backtests futurs
- Au bout de 21 jours après activation, la fenêtre rolling ne contient plus aucune ligne backfillée → conversion progressive vers la qualité live
- 2500 jours >> 250 → marge confortable même si ~20% des rows ont du noise élevé

---

## 12. Risques et mitigations

| # | Risque | Mitigation |
|---|---|---|
| 1 | Look-ahead bias GDELT (`seendate` après close ICE) | Filtre `seendate ≤ session_date 18h UTC` |
| 2 | Couverture GDELT inégale 2016-2018 | Log articles/jour, skip si < 3, valider corrélation par ère en Phase 4 |
| 3 | Coût LLM dérape (nominal $62, peut grimper avec retries) | Soft cap $100 warning, hard stop $150 kill |
| 4 | Runtime trop long (~20-30h, concurrency=3) | Resume via `--start <date>`, logs réguliers, ETA affiché |
| 5 | DB connection drops sur run de 30h | Session-per-date pattern (commit après chaque date) |
| 6 | GDELT down ou rate-limit | Retry 3x backoff expo, log + skip si toujours KO |
| 7 | Mauvaise qualité 2016-2018 invalide hypothèse 10 ans | Phase 4 valide corr 2016-2018 vs 2024-2026 ; si corr < 0.3 → restreindre fenêtre activable à 2018+ et documenter |
| 8 | Coupling involontaire avec `press_review_agent` | Import explicite + test smoke avant la run finale ; one-shot donc impact limité |
| 9 | Doublons / collisions avec live rows | Skip silencieux par défaut sur `(date, llm_provider)` existante ; `--force-replace` explicite si besoin |

---

## 13. Critères d'acceptance

### MVP shipped quand :

- [ ] Migration `add_is_backfill_column` appliquée en local et en GCP prod
- [ ] Module `backend/scripts/press_review_backfill/` créé avec tous les fichiers (main, gdelt_fetcher, context_resolver, writer, README, tests)
- [ ] Entry-point `press-review-backfill` ajouté à `backend/pyproject.toml`
- [ ] Tests unitaires passent : coverage ≥ 80% sur le nouveau module
- [ ] Phase 3 progressive complétée : dry-run OK → 30j OK → 1 an OK → 10 ans run lancé
- [ ] Phase 4 validation : corrélation Pearson backfill vs live ≥ 0.5 sur ≥ 3/4 thèmes
- [ ] Skip rate global < 10% sur les 10 ans
- [ ] `pl_fundamental_article` contient ≥ 2250 rows avec `is_backfill=TRUE`
- [ ] `pl_article_segment` contient ≥ 9000 rows avec `is_backfill=TRUE` (4 thèmes × 2250+ dates)
- [ ] `pl_sentiment_feature` recomputé : n par thème ≥ 2250 après `compute-sentiment-features`
- [ ] Décision GO/NO-GO documentée dans `docs/decisions/2026-XX-XX-press-review-backfill.md`
- [ ] README de cleanup présent dans `backend/scripts/press_review_backfill/`

### Rejet si :

- Le module backfill modifie un fichier dans `press_review_agent/` (viole l'isolation)
- Le module backfill est déployé en Cloud Run Job (viole "one-shot")
- Auto-retry / fallback silencieux ajouté (viole `.claude/rules/pipeline-error-handling.md`)
- `compute-sentiment-features` modifié (l'extraction_version="inline_v1" doit suffire)
- Codes contrats hardcodés (viole feedback memory `feedback_no_hardcoded_contracts.md`)
- Pas de filtre anti look-ahead bias dans le fetcher GDELT

---

## 14. Plan de vérification

### 14.1 Tests unitaires

```bash
cd backend && poetry run pytest scripts/press_review_backfill/tests/ -v --cov=scripts/press_review_backfill
```

Cible : ≥ 80% coverage sur le nouveau module.

### 14.2 Migration

```bash
cd backend && poetry run alembic upgrade head
psql -h localhost -p 5433 -U postgres -d commodities_compass -c "
  SELECT column_name, data_type, column_default
  FROM information_schema.columns
  WHERE table_name IN ('pl_fundamental_article','pl_article_segment')
    AND column_name = 'is_backfill';
"
```

### 14.3 Smoke run (Phase 3 progressif, local)

```bash
# 3a : dry-run sur 5 dates
poetry run press-review-backfill --start 2026-04-10 --end 2026-04-15 --dry-run --verbose

# 3b : run réel sur 30 jours locaux
poetry run press-review-backfill --start 2026-04-01 --end 2026-04-30 --concurrency 3

# Inspection
psql -c "
  SELECT date, is_backfill, source_count, LENGTH(summary) AS summary_len
  FROM pl_fundamental_article
  WHERE is_backfill = TRUE
  ORDER BY date DESC LIMIT 30;
"

# 3c : 1 an
poetry run press-review-backfill --start 2025-05-01 --end 2026-04-30 --concurrency 3
```

### 14.4 Run final 10 ans (Phase 3d)

```bash
# Décision : local DB puis sync vers GCP, ou run direct contre GCP via bastion ?
# Recommandation : local d'abord, puis batch upload SQL vers GCP

poetry run press-review-backfill --start 2016-05-12 --end 2026-04-30 --concurrency 3
```

Logs attendus toutes les 50 dates :
```
[INFO] Processed 1500/2500 dates | success=1485 | skip=15 | cost=$37.20 | ETA=8h22m
```

### 14.5 Validation statistique (Phase 4)

```bash
# Smoke test corrélation (5 dates récentes)
poetry run press-review-backfill --start 2026-04-15 --end 2026-04-19 \
  --concurrency 1 --extraction-version-override backfill_compare_v1

psql -c "
  WITH paired AS (
    SELECT
      a.article_date,
      a.theme,
      a.sentiment_score AS live_score,
      b.sentiment_score AS backfill_score
    FROM pl_article_segment a
    JOIN pl_article_segment b USING (article_date, theme)
    WHERE a.extraction_version = 'inline_v1' AND a.is_backfill = FALSE
      AND b.extraction_version = 'backfill_compare_v1'
  )
  SELECT theme, corr(live_score::numeric, backfill_score::numeric) AS pearson
  FROM paired
  GROUP BY theme;
"

# Recompute sentiment features
poetry run compute-sentiment-features --dry-run

# Validation finale
psql -c "
  SELECT theme, COUNT(*) AS n,
         AVG(zscore_delta) AS mean_zd,
         STDDEV(zscore_delta) AS std_zd,
         MIN(zscore_delta) AS min_zd,
         MAX(zscore_delta) AS max_zd
  FROM pl_sentiment_feature
  GROUP BY theme;
"
```

### 14.6 Validation sur GCP (post-run local)

Deux stratégies possibles, à arbitrer en Phase 3 :

**Option A — Run local + export SQL** :
1. Run complet en local
2. `pg_dump --table=pl_fundamental_article --table=pl_article_segment --data-only --column-inserts > backfill.sql`
3. Filter pour ne garder que les `is_backfill=TRUE`
4. Upload via bastion : `psql -h 127.0.0.1 -p 5434 -U cc_app -d commodities_compass -f backfill.sql`
5. `gcloud run jobs execute cc-compute-sentiment-features --region=europe-west9 --project=cacaooo`

**Option B — Run direct contre GCP via bastion tunnel** :
1. Bastion SSH tunnel ouvert pendant 30h (risque de coupure)
2. Run depuis local pointant `DATABASE_URL=postgres://127.0.0.1:5434/...`
3. Plus simple mais fragile sur runtime long

**Recommandation** : Option A, plus robuste.

---

## 15. Décisions ouvertes / à arbitrer

| # | Question | Owner | Statut |
|---|---|---|---|
| 1 | Quelle stratégie pour pousser les données vers GCP (Option A export SQL vs Option B run via bastion) ? | Tech lead | Open |
| 2 | Faut-il un badge "Archive (backfill)" dans le `NewsCard` du dashboard pour les dates où `is_backfill=TRUE` ? | Product | Open (recommandation : pas pour ce MVP, à voir en suivant retours) |
| 3 | Si Phase 4 montre corr < 0.5 sur certains thèmes, doit-on retenter avec un fetcher enrichi (Wayback Machine, NewsAPI payant) ou accepter la limite ? | Tech lead | Open (à arbitrer après Phase 4) |
| 4 | Phase 5 (activation algo v1.0.2) : doit-on attendre 21 jours après le backfill pour avoir une fenêtre rolling propre, ou activer immédiatement avec disclaimer ? | Tech lead | Open (recommandation : immédiatement, monitoring 21j post-activation) |

---

## Annexe A — Fichiers à créer / modifier

### Créer

```
docs/user-stories/P1-press-review-backfill-10y.md      (ce document)
backend/alembic/versions/<rev>_add_is_backfill_column.py
backend/scripts/press_review_backfill/__init__.py
backend/scripts/press_review_backfill/README.md
backend/scripts/press_review_backfill/main.py
backend/scripts/press_review_backfill/gdelt_fetcher.py
backend/scripts/press_review_backfill/context_resolver.py
backend/scripts/press_review_backfill/writer.py
backend/scripts/press_review_backfill/tests/__init__.py
backend/scripts/press_review_backfill/tests/test_gdelt_fetcher.py
backend/scripts/press_review_backfill/tests/test_context_resolver.py
backend/scripts/press_review_backfill/tests/test_writer.py
docs/decisions/2026-XX-XX-press-review-backfill.md     (rapport GO/NO-GO Phase 4)
```

### Modifier (additif, non-breaking)

```
backend/app/models/pipeline.py            (ajouter is_backfill sur PlFundamentalArticle + PlArticleSegment)
backend/pyproject.toml                    (poetry script press-review-backfill)
```

### Ne pas toucher (interdiction explicite)

```
backend/scripts/press_review_agent/       (PROD intact)
backend/scripts/compute_sentiment_features/  (filtre extraction_version inline_v1 suffit)
backend/app/engine/                       (Phase 5 différée)
infra/terraform/                          (pas de déploiement Cloud Run)
.github/workflows/deploy.yml              (pas de déploiement)
frontend/                                 (pas d'UI)
```

---

## Annexe B — Références externes

- GDELT Project 2.0 : <https://www.gdeltproject.org/>
- GDELT DOC 2.0 API : <https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/>
- GDELT API helper : <https://api.gdeltproject.org/api/v2/doc/doc>
- OpenAI o4-mini pricing : <https://openai.com/api/pricing/>
- EXP-014 — Granger validation z-score delta (interne, lien : `docs/experiments/EXP-014-sentiment-granger.md`)

---

## Annexe C — Références internes (codebase)

- Pattern agent existant : `backend/scripts/press_review_agent/` (architecture à imiter sans modifier)
- Modèles à étendre : `backend/app/models/pipeline.py` (PlFundamentalArticle ligne 248-271, PlArticleSegment ligne 326-375)
- Pipeline shadow mode actuel : `backend/app/engine/sentiment_features.py`, `backend/scripts/compute_sentiment_features/main.py`
- Doc shadow mode : `backend/app/models/pipeline.py:378-400` (PlSentimentFeature docstring)
- Pattern context resolver : `backend/app/utils/contract_resolver.py` (à étendre pour dates historiques)
- Pattern business day iteration : `backend/scripts/seasonal_backtest/` (parcours dates ≥ 5 ans)
- Pattern fail-loud : `.claude/rules/pipeline-error-handling.md`
- Pattern north-star alignment : `.claude/rules/north-star-alignment.md` (config-as-data, contract-centric)
- Précédent backtest 10 ans : `docs/backtests/2024-2025-seasonal/report.md` (méthodologie + format rapport)
- Rule mémoire : `feedback_no_hardcoded_contracts.md` (utiliser `pl_contract_data_daily` pour résolution historique)
