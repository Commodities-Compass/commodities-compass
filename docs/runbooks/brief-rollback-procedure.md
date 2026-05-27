# Brief Rollback Procedure — Runbook

> Step-by-step recovery when something goes wrong in the dual-track (legacy + ensemble) brief pipeline. Each scenario lists symptoms, immediate action, and verification.

> **Principle** : legacy is the safety net. If anything's wrong with ensemble, pause the ensemble side and the legacy brief continues serving normally. Never rollback by editing DB or writing custom SQL — use the scheduler pause + env var flip mechanisms.

---

## Scenario A — Bug dans l'explainer (refactor 2026-05-27 : wrapper DBAnalysisEngine)

### Contexte
Depuis le refactor PR #17, `cc-ensemble-explainer` est un thin wrapper autour de `scripts.daily_analysis.db_analysis_engine.DBAnalysisEngine` (cf. [PIPELINE_ENSEMBLE.md §7](../architecture/PIPELINE_ENSEMBLE.md)). Plus de prompt / parser / writer custom — tout le code LLM est partagé avec `cc-daily-analysis`. Donc les modes de panne sont les mêmes que côté legacy.

### Symptômes
- Sentry alerte sur `cc-ensemble-explainer` avec :
  - `EnsembleRowMissingError` (pre-flight a trouvé 0 row ensemble dans `pl_indicator_daily` à `data_date`)
  - `AnalysisWriteError` (engine n'a pas matché de row à l'UPDATE — typiquement compute-indicators n'a pas tourné)
  - OpenAI 5xx / timeout / quota
  - `AlgorithmVersionNotFoundError` (improbable, schema drift)
- Le brief ensemble du jour ne se génère pas (cc-compass-brief-ensemble exit 1 avec `EnsembleBriefDataMissingError` ou conclusion vide)
- L'utilisateur a peut-être vu un brief incomplet si `cc-compass-brief-ensemble` a tourné avant le diagnostic

### Action immédiate (≤2 min)
```bash
gcloud scheduler jobs pause cc-ensemble-explainer --location europe-west1 --project cacaooo
gcloud scheduler jobs pause cc-compass-brief-ensemble --location europe-west1 --project cacaooo
```

Le brief LEGACY continue à se générer normalement (cc-daily-analysis pinné sur legacy via `--algorithm-version legacy`). Le frontend par défaut (`BRIEF_DEFAULT_VERSION=legacy`) sert toujours l'audio legacy → aucun impact UX.

### Diagnostic
1. Sentry → exception + stack trace (le code legacy DBAnalysisEngine se log sous `scripts.daily_analysis.*` même quand appelé depuis ensemble-explainer).
2. `gcloud logging read 'resource.labels.job_name="cc-ensemble-explainer"' --limit 50` — chercher les lignes `Date semantics:`, `Pre-flight OK`, `Call #1 result`, `Call #2 result`, `Engine result`.
3. Vérifier l'upstream — `cc-ensemble-compute` a-t-il tourné ce soir ? Si non c'est lui le vrai responsable (cf. [ensemble-failure-recovery.md](./ensemble-failure-recovery.md)).

### Fix
- Si bug d'engine / prompt → éditer `backend/scripts/daily_analysis/prompts.py` (`CALL_1_PROMPT` ou `CALL_2_PROMPT_ENSEMBLE`) OU `backend/scripts/daily_analysis/db_analysis_engine.py`. ⚠ Toute modif affecte AUSSI le brief legacy puisque le code est partagé.
- Si `EnsembleRowMissingError` → relancer d'abord cc-ensemble-compute pour générer la row manquante.
- Tester en dry-run local sur dates historiques : `poetry run ensemble-explainer --target-date YYYY-MM-DD --dry-run`.
- PR + merge + redéploiement.
- Reprendre les schedulers : `gcloud scheduler jobs resume ...`.

### Verification
- Lancer manuellement pour rattraper les dates manquées :
  ```bash
  gcloud run jobs execute cc-ensemble-explainer \
    --region europe-west9 --project cacaooo \
    --args="ensemble-explainer,--target-date,2026-05-27,--force"
  ```
  Le wrapper calcule `data_date = previous_session(2026-05-27)` = 2026-05-26 et UPDATE la row à cette date.
- Vérifier la row ensemble : `SELECT date, decision, confidence, direction, LENGTH(conclusion) FROM pl_indicator_daily i JOIN pl_algorithm_version v ON i.algorithm_version_id=v.id WHERE i.date='2026-05-26' AND v.name='ensemble_v1_softgate_wrapper'`. Conclusion attendue : ~1000-1500 chars avec marker `> A SURVEILLER AUJOURD'HUI:` + 3 bullets.

---

## Scenario B — Bug dans le brief generator ensemble (template / formatting)

### Symptômes
- `cc-compass-brief-ensemble` exit 1
- Sentry alerte avec stack trace dans `brief_generator.py`
- Aucun fichier `-Ensemble.txt` sur Drive pour la date

### Action immédiate (≤2 min)
```bash
gcloud scheduler jobs pause cc-compass-brief-ensemble --location europe-west1 --project cacaooo
```

L'explainer continue à enrichir la DB (donc la décision + narrative restent disponibles pour le dashboard). Seule la production du brief Drive est gelée.

### Diagnostic
- Sentry → exception + stack trace
- Tester localement : `poetry run compass-brief-ensemble --target-date 2026-05-26 --dry-run` (affiche le brief sur stdout)
- Comparer avec les tests `scripts/compass_brief_ensemble/tests/test_brief_generator.py`

### Fix
- Patch dans `brief_generator.py`, tests passent, merge, deploy
- Reprendre le scheduler

### Verification
```bash
gcloud run jobs execute cc-compass-brief-ensemble \
  --region europe-west9 --project cacaooo \
  --args="compass-brief-ensemble,--target-date,2026-05-26,--force"
```
Vérifier le fichier sur Drive : `YYYYMMDD-CompassBrief-Ensemble.txt`.

---

## Scenario C — Décision ensemble divergente le matin (frontend pivot d'urgence)

### Symptômes
- Le frontend affiche une décision ensemble qui semble incohérente avec le brief legacy
- L'équipe veut temporairement servir le brief legacy aux utilisateurs le temps d'investiguer

### Action immédiate (≤5 min)
**Option 1 — Pivot global** (tous les users) :
```bash
# Vérifier la valeur actuelle
gcloud run services describe backend --region europe-west9 --project cacaooo \
  --format="value(spec.template.spec.containers[0].env[?name=='BRIEF_DEFAULT_VERSION'].value)"

# Pivoter vers legacy
gcloud run services update backend --region europe-west9 --project cacaooo \
  --update-env-vars BRIEF_DEFAULT_VERSION=legacy
```

Effet : les requêtes `/v1/dashboard/audio` sans `?version=` query param vont chercher le brief legacy. ~2-3 min de propagation Cloud Run.

**Option 2 — Pivot ciblé** (sans changer le défaut) : la frontend peut explicitement requêter `?version=legacy` sur ses calls audio jusqu'à résolution.

### Diagnostic
- Comparer brief legacy vs ensemble côté Drive (cf. [brief-dual-track.md](./brief-dual-track.md#comparaison-side-by-side-dun-brief-sur-la-même-date))
- Investiguer pourquoi l'ensemble diverge — c'est probablement attendu (l'ensemble peut prendre une décision différente du LLM legacy quand les données structurées contredisent le narratif)
- Si la divergence est légitime → garder ensemble en service mais l'expliquer
- Si erreur (corruption data) → identifier root cause + fix DB

### Verification
- `BRIEF_DEFAULT_VERSION` lu correctement par le service backend (curl /v1/dashboard/audio sans `?version=` → vérifier que `version` dans la response est `legacy`)
- Audio legacy joue bien dans le browser

### Cleanup (retour à la normale)
```bash
gcloud run services update backend --region europe-west9 --project cacaooo \
  --update-env-vars BRIEF_DEFAULT_VERSION=ensemble  # ou rester sur legacy selon décision
```

---

## Scenario D — Rollback complet ensemble (décommissioning temporaire)

### Cas d'usage
On veut désactiver toute la production ensemble (explainer + brief) pendant N jours, pour investigation profonde ou pour libérer du quota NotebookLM.

### Action complète
```bash
# Pause les 2 schedulers (préserve la config Terraform)
gcloud scheduler jobs pause cc-ensemble-explainer       --location europe-west1 --project cacaooo
gcloud scheduler jobs pause cc-compass-brief-ensemble   --location europe-west1 --project cacaooo

# Optionnel : pause aussi cc-ensemble-compute si on veut TOUT arrêter
# (Attention : ça stoppe aussi le frontend dashboard qui sert la décision ensemble)
# gcloud scheduler jobs pause cc-ensemble-compute --location europe-west1 --project cacaooo

# Frontend : retourner sur legacy par défaut
gcloud run services update backend --region europe-west9 --project cacaooo \
  --update-env-vars BRIEF_DEFAULT_VERSION=legacy
```

### État résultant
- Legacy continue à produire ses 2 briefs (daily-analysis + compass-brief)
- Dashboard frontend continue à afficher l'ensemble (via `_resolve_algo_for_date()`) parce que `cc-ensemble-compute` reste actif — la position OPEN/HEDGE/MONITOR vient toujours de l'ensemble
- L'audio servi par défaut est legacy
- Aucun audio ensemble nouveau ne sera produit (pas de fichier `-Ensemble.txt` sur Drive)

### Reprise
```bash
gcloud scheduler jobs resume cc-ensemble-explainer       --location europe-west1 --project cacaooo
gcloud scheduler jobs resume cc-compass-brief-ensemble   --location europe-west1 --project cacaooo

# Si on veut re-basculer le frontend en ensemble
gcloud run services update backend --region europe-west9 --project cacaooo \
  --update-env-vars BRIEF_DEFAULT_VERSION=ensemble
```

Rattrapage si on veut combler les jours manquants : voir scénario A.

---

## Scenario E — Drive credentials expirées (les 2 tracks affectés)

### Symptômes
- `cc-compass-brief` ET `cc-compass-brief-ensemble` exit 1 simultanément
- Sentry stack trace mentionne 401/403 Google Drive API

### Action
- Renouveler les credentials du service account (cf. infra Terraform)
- Update `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` secret dans GCP Secret Manager
- Forcer un redéploiement des 2 jobs : `gcloud run jobs update cc-compass-brief ...` et `gcloud run jobs update cc-compass-brief-ensemble ...`
- Lancer manuellement pour rattraper

C'est un fail commun aux 2 tracks (shared credentials) — pas un bug du dual-track.

---

## Tableau récapitulatif

| Quoi a failli | Action immédiate | Legacy impacté ? | Frontend impacté ? |
|---|---|---|---|
| Explainer LLM | Pause `cc-ensemble-explainer` + `cc-compass-brief-ensemble` | Non | Non (BRIEF_DEFAULT_VERSION=legacy par défaut) |
| Brief generator ensemble | Pause `cc-compass-brief-ensemble` | Non | Non |
| Décision ensemble bizarre | Flip `BRIEF_DEFAULT_VERSION=legacy` | Non | Oui (mais legacy disponible) |
| Rollback complet | Pause les 2 schedulers ensemble + flip env var | Non | Légèrement (pas d'audio ensemble dispo) |
| Drive credentials | Renew secret + redeploy | OUI | Oui (les 2 audios manquent) |

Toutes ces actions sont **réversibles**. Aucune édition DB. Aucune migration. Aucun rollback de PR. Le système est conçu pour qu'on puisse pivoter en 2-5 minutes.
