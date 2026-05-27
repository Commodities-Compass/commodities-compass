# Brief Dual-Track — Runbook

> Two parallel daily briefs running side-by-side: legacy LLM and ensemble v1.0.0. Both fully functional, switchable per-request, rollback-friendly. This runbook is the operational reference.

## Architecture en deux tracks

```
                    ┌─────────────────────────────────────┐
                    │   Inputs partagés (Phase A + B)     │
                    │  pl_contract_data_daily,            │
                    │  pl_derived_indicators,             │
                    │  pl_fundamental_article (press),    │
                    │  pl_weather_observation (meteo),    │
                    │  pl_article_segment, etc.           │
                    └─────────────────────────────────────┘
                                  │
                ┌─────────────────┴─────────────────┐
                ▼                                   ▼
    ┌──────────────────────┐         ┌──────────────────────────┐
    │   TRACK LEGACY       │         │   TRACK ENSEMBLE         │
    │                      │         │                          │
    │ 19:20 cc-daily-      │         │ 19:18 cc-ensemble-       │
    │       analysis       │         │       compute            │
    │  → row legacy de     │         │  → row ensemble de       │
    │    pl_indicator_     │         │    pl_indicator_daily    │
    │    daily             │         │  → pl_orchestrator_      │
    │    (eco, decision,   │         │    decision (25 cols)    │
    │     conf, dir, ...)  │         │  → 14 specialist rows    │
    │                      │         │                          │
    │                      │         │ 19:25 cc-ensemble-       │
    │                      │         │       explainer (LLM)    │
    │                      │         │  → UPDATE ensemble row : │
    │                      │         │    eco, confidence,      │
    │                      │         │    direction, conclusion │
    │                      │         │                          │
    │ 19:30 cc-compass-    │         │ 19:35 cc-compass-brief-  │
    │       brief          │         │       ensemble           │
    │  → Drive:            │         │  → Drive:                │
    │    YYYYMMDD-         │         │    YYYYMMDD-CompassBrief-│
    │    CompassBrief.txt  │         │    Ensemble.txt          │
    └──────────────────────┘         └──────────────────────────┘
                │                                   │
                ▼                                   ▼
    YYYYMMDD-CompassAudio.{wav,m4a,mp4}    YYYYMMDD-CompassAudio-Ensemble.{wav,m4a,mp4}
    (NotebookLM le matin)                  (NotebookLM le matin)
                │                                   │
                └─────────────┬─────────────────────┘
                              ▼
                  Frontend /v1/dashboard/audio
                  (sert legacy ou ensemble selon
                   BRIEF_DEFAULT_VERSION env var
                   ou query param ?version=)
```

## Qui écrit quoi

| Asset | Legacy | Ensemble | Isolation |
|---|---|---|---|
| `pl_indicator_daily` row | `algorithm_version_id=legacy` | `algorithm_version_id=ensemble_v1_softgate_wrapper` | UNIQUE constraint sur (date, contract_id, algorithm_version_id) garantit qu'un track ne peut PAS toucher l'autre |
| `pl_orchestrator_decision` | — | écrit | Table exclusive à l'ensemble |
| `pl_specialist_prediction` | — | 14 rows/jour | Table exclusive à l'ensemble |
| Drive file | `YYYYMMDD-CompassBrief.txt` | `YYYYMMDD-CompassBrief-Ensemble.txt` | Filename discriminant ; même folder OK |
| Drive audio | `YYYYMMDD-CompassAudio.{ext}` | `YYYYMMDD-CompassAudio-Ensemble.{ext}` | NotebookLM produit les 2 audios chaque jour |

## Switch frontend (quel audio est servi)

Trois leviers, du plus large au plus précis :

### 1. Env var globale `BRIEF_DEFAULT_VERSION`

```bash
# Bascule globale frontend → ensemble (tout user, toute requête sans override)
gcloud run services update backend \
  --region europe-west9 --project cacaooo \
  --update-env-vars BRIEF_DEFAULT_VERSION=ensemble

# Rollback global → legacy
gcloud run services update backend \
  --region europe-west9 --project cacaooo \
  --update-env-vars BRIEF_DEFAULT_VERSION=legacy
```

Effet sur le redéploiement Cloud Run : la nouvelle instance lit l'env var au boot, les anciennes instances peuvent encore servir l'ancienne version jusqu'à recyclage (~quelques minutes).

### 2. Query param `?version=ensemble|legacy`

Sans flip global, le frontend ou un utilisateur peut tester :

```bash
# Endpoints qui supportent ?version=
GET /v1/dashboard/audio?version=ensemble
GET /v1/audio/info?version=ensemble
GET /v1/audio/stream?version=ensemble
```

Override par requête. Idéal pour preview UX d'un user pilote, A/B testing.

### 3. Schedulers (pause/resume)

Pour arrêter la PRODUCTION d'un brief (sans toucher au switch frontend) :

```bash
# Pause ensemble (legacy continue à produire son brief)
gcloud scheduler jobs pause cc-ensemble-explainer --location europe-west1 --project cacaooo
gcloud scheduler jobs pause cc-compass-brief-ensemble --location europe-west1 --project cacaooo

# Reprise
gcloud scheduler jobs resume cc-ensemble-explainer --location europe-west1 --project cacaooo
gcloud scheduler jobs resume cc-compass-brief-ensemble --location europe-west1 --project cacaooo

# Pause legacy (ensemble continue)
gcloud scheduler jobs pause cc-daily-analysis --location europe-west1 --project cacaooo
gcloud scheduler jobs pause cc-compass-brief --location europe-west1 --project cacaooo
```

⚠️ **Important** : `gcloud scheduler jobs pause` suspend le déclenchement mais NE désactive PAS le Cloud Run Job lui-même. Il peut toujours être lancé manuellement via `gcloud run jobs execute`.

## Lancer un brief manuellement

### Brief ensemble pour une date passée (backfill ou debug)

```bash
gcloud run jobs execute cc-ensemble-explainer \
  --region europe-west9 --project cacaooo \
  --args="ensemble-explainer,--target-date,2026-05-26,--force"

gcloud run jobs execute cc-compass-brief-ensemble \
  --region europe-west9 --project cacaooo \
  --args="compass-brief-ensemble,--target-date,2026-05-26,--force"
```

L'explainer doit tourner AVANT le brief (l'explainer écrit les champs LLM, le brief les lit).

### Brief legacy pour une date passée

```bash
gcloud run jobs execute cc-daily-analysis \
  --region europe-west9 --project cacaooo \
  --args="daily-analysis,--date,2026-05-26,--algorithm-version,legacy,--force"

gcloud run jobs execute cc-compass-brief \
  --region europe-west9 --project cacaooo \
  --args="compass-brief,--force"
```

(Le brief legacy ne supporte pas encore `--target-date` directement — il lit les 2 dernières dates de `pl_contract_data_daily`.)

## Comparaison side-by-side d'un brief sur la même date

```bash
# Télécharger les 2 briefs du jour depuis Drive
gdrive download "20260526-CompassBrief.txt"
gdrive download "20260526-CompassBrief-Ensemble.txt"

# Diff
diff -u 20260526-CompassBrief.txt 20260526-CompassBrief-Ensemble.txt | less
```

Ou via la console Drive : ouvrir les 2 fichiers en parallèle.

## Métriques à surveiller (Sentry)

- `cc-ensemble-explainer` cron monitor : exit 0 = success même si gate skip
- `cc-compass-brief-ensemble` cron monitor : idem
- Sentry breadcrumbs : LLM tokens in/out (Call#1 + Call#2 gpt-4-turbo), latency, decision, confidence, direction, macroeco_bonus
- Si l'engine émet un warning `LLM returned decision=X but ensemble said Y — forcing alignment`, le LLM a dérivé de `decision_wrapped` mais le force-alignment a corrigé → narrative préservée, à monitorer si récurrent (signe de drift du prompt `CALL_2_PROMPT_ENSEMBLE` dans `scripts/daily_analysis/prompts.py`)
- Si `EnsembleRowMissingError` → cc-ensemble-compute n'a pas tourné, voir [ensemble-failure-recovery.md](./ensemble-failure-recovery.md)

## Fail-loud rules respectées

- Aucune retry automatique sur LLM failure → exit non-zero, Sentry capture, runbook humain
- Aucune fallback silencieuse (legacy ne sert PAS de fallback automatique pour ensemble — c'est un choix produit, pas une dégradation)
- Validator post-LLM rejette tout commentaire qui contredit la décision

## Coût

- 1 appel LLM `gpt-4o-mini` par jour de trading = ~$0.001 × 250 ≈ **$0.25/an**
- Cloud Run Job 1Gi × ~30s × 250 runs = négligeable (<$1/an)
- 2 fichiers Drive (.txt) + 2 audios NotebookLM par jour : impact NotebookLM quota à monitorer
