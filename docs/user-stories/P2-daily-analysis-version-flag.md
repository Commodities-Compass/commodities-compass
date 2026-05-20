# Daily-Analysis Version Flag — Prévenir l'overwrite de la décision ensemble

**Statut :** Proposed (non implémenté)
**Date :** 2026-05-19
**Owner :** TBD (Hedi)
**Slug :** `daily-analysis-version-flag`
**Cible repo :** `docs/user-stories/P2-daily-analysis-version-flag.md`
**Deadline :** P2 mais **bloquante pour le launch C5 day-1** — doit ship AVANT le flip `is_active=TRUE` de l'ensemble
**Effort :** ~0.5 jour (code + tests)

---

## 1. Contexte

Le job `cc-daily-analysis` (LLM, cron `20 19 * * 1-5` UTC) écrit dans `pl_indicator_daily` la décision finale + le commentaire eco/direction/confiance pour **la version actuellement active** (`is_active=TRUE`). Le code :

[backend/scripts/daily_analysis/db_analysis_engine.py:238-241](../../backend/scripts/daily_analysis/db_analysis_engine.py#L238-L241) :
```python
algo_row = self._session.execute(
    text("SELECT id FROM pl_algorithm_version WHERE is_active = true LIMIT 1"),
).fetchone()
algo_version_id = algo_row[0] if algo_row else None
```

Le UPDATE qui suit ([lignes 246-276](../../backend/scripts/daily_analysis/db_analysis_engine.py#L246-L276)) scope à `WHERE algorithm_version_id = :algo_version_id`.

**Problème** : pour le launch C5 ([CAMPAIGN_5_PROD_DEPLOYMENT.md §8.1](../onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md#L444-L477)), Hedi a tranché un **day-1 promotion** : `ensemble_v1_softgate_wrapper` aura `is_active=TRUE` dès J1, `legacy` passera à `is_active=FALSE`. Conséquence :
- `cc-daily-analysis` resolve `is_active=TRUE` → trouve la version ensemble → essaie d'UPDATE la row ensemble avec son LLM judgement (macroeco_bonus, decision, confidence, direction, eco, conclusion)
- Mais la décision ensemble est calculée par `cc-ensemble-compute` (cron 19:18 UTC, ~2 min avant daily-analysis à 19:20) avec une logique 14-spécialistes + soft-gate + wrapper — **pas avec un LLM**
- Le LLM va donc **écraser la décision ensemble** chaque soir → la row dashboard montre la décision LLM, pas l'ensemble.

**Pourquoi maintenant** : sans cette US, day-1 launch C5 est inopérant côté dashboard (l'utilisateur verra le LLM, pas l'ensemble). Il faut pinner daily-analysis sur la version `legacy` peu importe qui est `is_active=TRUE` globalement.

**Alternative architecturale rejetée** : laisser daily-analysis tourner sur la version active = retirer purement la dépendance LLM du pipeline. Trop disruptif pour une US bloquante. La solution proposée est minimale et backward-compatible.

---

## 2. Goals & non-goals

### Goals (cette itération)

- Ajouter un flag CLI `--algorithm-version <name>` à `cc-daily-analysis`
- Quand flag absent → comportement actuel inchangé (resolve `is_active=TRUE`)
- Quand flag présent → resolve `WHERE name = :name LIMIT 1` (peu importe `is_active`)
- Pinner le déploiement Cloud Run Job sur `--algorithm-version legacy` via `deploy.yml`
- Tests unit + intégration
- Backward compatible

### Non-goals

- **Pas** de refactor du LLM call ni de la logique métier daily-analysis (seule la resolution de l'algorithm_version_id change)
- **Pas** de support multi-versions parallèles (une seule version par run)
- **Pas** de bascule automatique : c'est l'opérateur (Hedi) qui décide via le flag dans deploy.yml
- **Pas** de modification de `cc-compute-indicators` (qui supporte déjà `--all-versions` + `--algorithm-version`)
- **Pas** d'auto-detection "skip this version if a different writer already wrote it" (complexité inutile)

---

## 3. Solution

### 3.1 Changement code

**Fichier 1 : `backend/scripts/daily_analysis/main.py`** (ligne ~55, après `--llm-model`) :

```python
parser.add_argument(
    "--algorithm-version",
    default=None,
    help=(
        "Pin daily-analysis to a specific algorithm name (e.g. 'legacy'). "
        "If omitted: resolves to is_active=TRUE (current behavior, backward compatible)."
    ),
)
```

Puis passe `args.algorithm_version` au `DBAnalysisEngine` constructeur ou méthode de run.

**Fichier 2 : `backend/scripts/daily_analysis/db_analysis_engine.py`** (ligne 238-241) :

```python
# AVANT (lignes 238-241 actuelles)
algo_row = self._session.execute(
    text("SELECT id FROM pl_algorithm_version WHERE is_active = true LIMIT 1"),
).fetchone()

# APRÈS — backward compatible
if self._algorithm_version_name:
    algo_row = self._session.execute(
        text("SELECT id FROM pl_algorithm_version WHERE name = :name LIMIT 1"),
        {"name": self._algorithm_version_name},
    ).fetchone()
else:
    algo_row = self._session.execute(
        text("SELECT id FROM pl_algorithm_version WHERE is_active = true LIMIT 1"),
    ).fetchone()
algo_version_id = algo_row[0] if algo_row else None
```

Note : si plusieurs versions partagent le même `name` (e.g., `legacy` v1.0.0 et v1.0.1) → ajouter aussi un argument `--algorithm-version-number` ou utiliser le pattern de `compute-indicators` qui prend `--algorithm` + `--algorithm-version`. Pour MVP : `LIMIT 1` ORDER BY `is_active=TRUE` est suffisant (la version active du nom donné).

**Fichier 3 : `.github/workflows/deploy.yml`** ligne 207 :

```bash
# AVANT
deploy_job cc-daily-analysis       1Gi  "daily-analysis"

# APRÈS
deploy_job cc-daily-analysis       1Gi  "daily-analysis,--algorithm-version,legacy"
```

Cloud Run prend l'arg via virgule séparation (pattern existant pour `cc-compute-indicators`).

### 3.2 Fallback safety

Si `--algorithm-version legacy` et aucune row trouvée dans `pl_algorithm_version` avec `name='legacy'` → log ERROR, exit non-zero (fail-loud). **Pas** de fallback silencieux vers `is_active=TRUE` (ça vaincrait le but).

### 3.3 Race condition vs `cc-ensemble-compute`

`cc-ensemble-compute` (19:18 UTC) écrit `pl_indicator_daily` pour version `ensemble_v1_softgate_wrapper`. `cc-daily-analysis` (19:20 UTC) avec `--algorithm-version legacy` écrit pour version `legacy`. **Aucune intersection** : ce sont des rows distinctes par PK `(date, contract_id, algorithm_version_id)`. Safe.

Si quelqu'un omet le flag dans deploy.yml par accident → daily-analysis pointe sur `is_active=TRUE` = `ensemble_v1_softgate_wrapper` → écrase la row ensemble. **Mitigation** : test d'intégration explicite + critère acceptance §7 vérifie que le flag est bien dans deploy.yml.

---

## 4. Tests

### 4.1 Tests unitaires

```bash
poetry run pytest backend/tests/daily_analysis/test_db_analysis_engine.py -v
```

Cas testés :

1. **Sans flag** : engine init sans `algorithm_version_name` → SELECT WHERE is_active=TRUE → resolve la version active.
2. **Avec flag = "legacy"** : engine init avec `algorithm_version_name="legacy"` → SELECT WHERE name='legacy' → resolve la version legacy même si `is_active=FALSE`.
3. **Flag avec version inexistante** : `algorithm_version_name="nonexistent"` → algo_row = None → fail-loud (raise ou exit non-zero, à matcher le pattern actuel).
4. **2 versions actives** (cas pathologique) : `--algorithm-version legacy` avec 2 rows `name='legacy'` → LIMIT 1 prend la première (acceptable, à documenter).
5. **UPDATE scope** : avec flag, le WHERE `algorithm_version_id = :algo_version_id` ne match que la row legacy, jamais la row ensemble.

### 4.2 Test d'intégration

```bash
poetry run pytest backend/tests/daily_analysis/test_integration.py -v -m integration
```

**Setup** : DB locale avec 2 rows dans `pl_algorithm_version` :
- `legacy v1.0.1` : `is_active=FALSE` (volontairement)
- `ensemble_v1_softgate_wrapper v1.0.0` : `is_active=TRUE`

**Pre-state** : insérer 1 row `pl_indicator_daily` pour chaque version (date=today, contract_id=CAK26), avec valeurs distinctives (e.g., `decision='HEDGE'` pour legacy, `decision='OPEN'` pour ensemble).

**Run** : `poetry run daily-analysis --algorithm-version legacy --dry-run` puis sans `--dry-run`.

**Assert** :
- La row legacy reçoit les UPDATE LLM (decision/confidence/direction/eco/conclusion changent)
- La row ensemble RESTE INCHANGÉE (decision='OPEN', pas écrasée)
- Si on relance sans le flag → la row ensemble est mise à jour par le LLM (comportement actuel, démonstration du risque)

### 4.3 Test deploy.yml

```bash
grep -A1 "cc-daily-analysis" .github/workflows/deploy.yml | grep "algorithm-version,legacy"
```

Critère acceptance : doit retourner exactement la ligne `deploy_job cc-daily-analysis 1Gi "daily-analysis,--algorithm-version,legacy"`.

---

## 5. Critères d'acceptance

### MVP shipped quand :

1. **Code modifié** :
   - `backend/scripts/daily_analysis/main.py` : flag `--algorithm-version` ajouté à argparse, default `None`
   - `backend/scripts/daily_analysis/db_analysis_engine.py:238-241` : resolution conditionnelle name vs is_active
   - `.github/workflows/deploy.yml:207` : `deploy_job cc-daily-analysis 1Gi "daily-analysis,--algorithm-version,legacy"`
2. **Tests unit ≥ 80% coverage** sur les changements (5 cas listés §4.1).
3. **Test d'intégration** : démontre que la row ensemble n'est PAS touchée quand le flag est fourni.
4. **Backward compatible** : `poetry run daily-analysis --dry-run` (sans le flag) produit exactement le même comportement qu'avant.
5. **Smoke test prod J-1** : sur staging ou via dry-run prod, vérifier qu'avec le flag dans deploy.yml :
   ```sql
   SELECT date, name, decision, eco IS NOT NULL AS has_llm_eco
   FROM pl_indicator_daily i
   JOIN pl_algorithm_version v ON i.algorithm_version_id = v.id
   WHERE date = CURRENT_DATE - 1
   ORDER BY name;
   ```
   → Doit montrer `legacy` avec `has_llm_eco=TRUE`, `ensemble_v1_softgate_wrapper` avec `has_llm_eco=FALSE` (jamais touché par daily-analysis).
6. **Window de validation 5 jours** : sur 5 cycles daily, 0 update sur la row `ensemble_v1_softgate_wrapper` par daily-analysis (vérifiable via colonne `updated_at` si ajoutée, sinon via diff snapshot avant/après).
7. **Sentry vert** : aucune erreur sur `cc-daily-analysis` post-flag deployment.

### Rejet si :

- Fallback silencieux quand `--algorithm-version` cible une version inexistante (doit fail-loud).
- Modification de la logique LLM (out of scope — seule la resolution change).
- Auto-retry sur DB error (règle interdite).
- Tests qui ne distinguent pas explicitement les 2 rows (legacy vs ensemble).
- deploy.yml sans le flag → laisser cette mitigation à un PR review checklist serré.

---

## 6. Risques & mitigation

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| Oubli du flag dans deploy.yml au moment du deploy | Moyenne | Élevé (la row ensemble est écrasée) | PR review checklist explicite, test grep dans CI, alerte Sentry custom si la row ensemble change après 19:20 (post-MVP, optionnel). |
| 2 rows avec `name='legacy'` (e.g., v1.0.0 et v1.0.1) | Faible | Faible | `LIMIT 1` ORDER BY `created_at DESC` (documenter dans le code). Si besoin précis : ajouter `--algorithm-version-number`. |
| Flag mis sur `ensemble_v1_softgate_wrapper` par accident | Très faible | Élevé (LLM écrit dans la row ensemble) | Le flag est explicite côté deploy.yml ; PR review attendu. Pas de mitigation code (config-as-code). |
| daily-analysis se trompe de row si `is_active=TRUE` change pendant le run | Très faible | Faible | Le run dure ~30s. La transaction est courte. Cas pathologique non couvert (acceptable). |
| Backward compat cassée pour un autre consommateur de daily-analysis | Faible | Moyen | Tests d'intégration sans flag montrent le comportement actuel inchangé. Pas d'autre consommateur identifié. |

---

## 7. Open questions

1. **Faut-il aussi un `--algorithm-version-number`** (e.g., `1.0.1`) ? → NON pour MVP. Le `name` est suffisant ; si plusieurs versions du même name existent, ORDER BY `created_at DESC LIMIT 1` est le défaut raisonnable. À envisager en P3 si besoin.
2. **Alternative : flag inverse `--skip-version <name>`** (skip la version ensemble plutôt que pinner legacy) ? → NON. Pinner explicitement est plus sûr et plus simple.
3. **Long-terme** : faut-il que daily-analysis disparaisse complètement quand l'ensemble est mature et que sa décision LLM n'a plus de valeur ajoutée ? → DISCUSSION future. Hors scope de cette US.
4. **Faut-il faire la même chose pour `compute-indicators`** ? → NON. `compute-indicators --all-versions` est déjà le pattern correct (compute pour toutes les versions enabled). Pas de risque d'overwrite croisé (différents version_ids = différentes rows).

---

## 8. Séquence d'exécution

Phasing pour livrer en 0.5 jour :

| Étape | Tâche | Temps |
|---|---|---|
| 1 | Modifier `main.py` + argparse | 10 min |
| 2 | Modifier `db_analysis_engine.py` resolution | 10 min |
| 3 | Écrire 5 tests unit | 1h |
| 4 | Écrire test d'intégration | 1h |
| 5 | Modifier `deploy.yml` | 5 min |
| 6 | PR + review | 30 min |
| 7 | Deploy + smoke test prod | 30 min |
| 8 | Window validation 5 jours (passif) | n/a |

Total : ~3.5h actif + 5 jours de monitoring.

---

## Annexe A — Fichiers modifiés

### Modifier (ciblage chirurgical)

- `backend/scripts/daily_analysis/main.py` — +5 lignes argparse, +1 ligne passage du flag
- `backend/scripts/daily_analysis/db_analysis_engine.py` — refactor lignes 238-241 (~10 lignes après expansion)
- `.github/workflows/deploy.yml` — modifier ligne 207 (+27 chars dans les args)
- `backend/tests/daily_analysis/test_db_analysis_engine.py` — +5 tests unit
- `backend/tests/daily_analysis/test_integration.py` — +1 test intégration (créer le fichier si n'existe pas)

### Ne pas toucher

- Logique LLM (prompts, parsing, validation) — hors scope
- `pl_indicator_daily` schema — pas de migration
- `pl_algorithm_version` schema — pas de migration
- Autres scripts (`compute-indicators`, scrapers, etc.) — isolation
- Frontend — pas d'impact UI

---

## Annexe B — Liens

- Code actuel daily-analysis : [backend/scripts/daily_analysis/main.py](../../backend/scripts/daily_analysis/main.py), [db_analysis_engine.py:238-276](../../backend/scripts/daily_analysis/db_analysis_engine.py#L238-L276)
- Pattern compute-indicators (référence) : [backend/app/engine/runner.py:472-477](../../backend/app/engine/runner.py#L472-L477) — `--algorithm` + `--algorithm-version`
- Plan déploiement C5 : [CAMPAIGN_5_PROD_DEPLOYMENT.md §3 Q3](../onboarding/CAMPAIGN_5_PROD_DEPLOYMENT.md#L138-L142)
- Pipeline error handling : [.claude/rules/pipeline-error-handling.md](../../.claude/rules/pipeline-error-handling.md)
