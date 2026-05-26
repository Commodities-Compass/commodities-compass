# Ensemble Explainer — Prompt Tuning Runbook

> How to safely modify the LLM prompts that produce the ensemble brief narrative (`eco`, `confidence`, `direction`, `conclusion`). The Explainer is constrained — it explains the ensemble decision, never overrides it. Tuning the prompt is the main lever to adjust style, depth, and tone.

## Where the prompts live

- **System prompt** : [backend/scripts/ensemble_explainer/prompts.py](../../backend/scripts/ensemble_explainer/prompts.py) → `SYSTEM_PROMPT`
- **User prompt template** : same file → `USER_PROMPT_TEMPLATE`
- **Validation rules** : [backend/scripts/ensemble_explainer/output_parser.py](../../backend/scripts/ensemble_explainer/output_parser.py) → `parse_explainer_output()` + `_OPPOSITE_WORDS`

## Editing tone / length / structure

The 4 fields the LLM produces and how to influence them :

### `eco` (≤300 chars, magazine éditorial)
- For shorter prose : reduce the explicit ≤300 chars in the system prompt to ≤200
- For more macro emphasis : add to the system prompt « Mentionne explicitement la macro_direction et macro_surprise si actives »
- For less hedging language : add « Évite "à confirmer", "à valider" — donne ton diagnostic clair »

### `confidence` (1-5 LLM-judged)
- Calibrate by adding examples in the system prompt :
  - « confidence=5 → conviction maximale (running_acc_5d > 0.85 + cluster Winter unanime + macro alignée) »
  - « confidence=2 → doute fort (anomaly_z > 1.5 OU dispersion fire OU specialists splits) »
- Current behavior is unconstrained — the LLM picks freely

### `direction` (HAUSSIERE / BAISSIERE / NEUTRE)
- This is enum-validated. If the LLM keeps picking NEUTRE on bullish ensemble cases, add « Si decision=OPEN avec macro_direction=+1, direction doit être HAUSSIERE sauf désaccord majeur »

### `conclusion` (≤2000 chars, doit contenir 3 « À SURVEILLER »)
- For more triggers diversity : add patterns to the system prompt
- For tighter NotebookLM audio (shorter audio briefs) : reduce CONCLUSION_MAX_CHARS to 1200 in `config.py`

## Procedure : tuner le prompt en 5 étapes

### 1. Mesurer le baseline
```bash
# Capturer 3 dates récentes avec décisions différentes
cd backend

# OPEN day
poetry run ensemble-explainer --target-date 2026-05-22 --dry-run --verbose

# HEDGE day
poetry run ensemble-explainer --target-date 2026-05-21 --dry-run --verbose

# MONITOR day
poetry run ensemble-explainer --target-date 2026-05-20 --dry-run --verbose
```

Logger les outputs (eco, conclusion) pour chacun → ce sera ton « avant ».

### 2. Éditer `prompts.py`
- Modifier `SYSTEM_PROMPT` ou `USER_PROMPT_TEMPLATE` selon le besoin
- Garder les contraintes ABSOLUES (decision-pinned, JSON strict, no markdown fences)
- Ne JAMAIS retirer la phrase « Tu DOIS la respecter, ne PEUX PAS la modifier »

### 3. Tester sur le même panel
```bash
poetry run ensemble-explainer --target-date 2026-05-22 --dry-run --verbose
poetry run ensemble-explainer --target-date 2026-05-21 --dry-run --verbose
poetry run ensemble-explainer --target-date 2026-05-20 --dry-run --verbose
```

Comparer avant/après. Critères :
- ✅ Tous les outputs JSON valides (pas de `ExplainerOutputError`)
- ✅ Confidence dans [1,5]
- ✅ Direction dans {HAUSSIERE, BAISSIERE, NEUTRE}
- ✅ Conclusion contient 3 « À SURVEILLER »
- ✅ Conclusion ne contredit pas decision (validator passe)
- ✅ Ton/longueur conformes à ce que tu visais

### 4. Tester l'edge case (wrapper actif + anomalie)
Si possible, trouver une date où `wrapper_active=True` ET `anomaly_score_z > 2.0` → cas où le LLM doit nuancer fortement. Vérifier que la conclusion reflète bien le contexte difficile.

### 5. Validation tests unitaires
```bash
poetry run pytest scripts/ensemble_explainer/tests/test_output_parser.py -v
```

Les tests d'output parser doivent passer (le validator est stable).

### 6. Ship
Commit + PR + merge. Le prompt est appliqué au prochain run cron (19:25 UTC du jour suivant).

## Cost estimate par run

- Model : `gpt-4o-mini`
- Tokens input typiques : ~1500-2500 (système + diagnostics + 14 specialists + press + meteo)
- Tokens output : ~300-600
- Cost : ~$0.0005 / call
- Par an (250 trading days) : ~$0.12

Si on veut migrer vers `gpt-4-turbo` (plus narratif, plus cher) :
- Cost par call : ~$0.05
- Par an : ~$12

Trade-off à arbitrer.

## Validator stricte : les mots interdits

Le `output_parser._OPPOSITE_WORDS` mapping bloque les contradictions :

```python
_OPPOSITE_WORDS = {
    "OPEN":    ("vendre", "vente", "short", "couvrir", "hedge", "fermer la position"),
    "HEDGE":   ("acheter", "long", "open", "rouvrir"),
    "MONITOR": (),  # neutral
}
```

Si on veut autoriser un nouveau verbe dans une conclusion sans qu'il déclenche un blocage, **NE MODIFIE PAS** la liste sans réflexion — c'est un garde-fou fail-loud volontaire. Préfère reformuler le prompt pour que le LLM utilise un autre vocabulaire.

Si tu DOIS ajouter / retirer un mot :
- Ajouter test dans `tests/test_output_parser.py` pour blinder le comportement
- Documenter la raison dans le commit

## Quand le LLM commence à dériver (drift)

Symptômes :
- Conclusions de plus en plus longues / verbeuses sans nouvelle info
- Confidence systématiquement à 4-5 sans diversité
- Direction NEUTRE trop fréquente même sur cas tranchés
- LLM mentionne des chiffres absents du contexte (hallucination)

Réponse :
1. Revenir au prompt précédent (`git revert`) + observer 5 jours
2. Si drift persiste → tester avec `gpt-4-turbo` (peut-être que `gpt-4o-mini` n'a plus assez de capacité pour le prompt actuel)
3. Si tokens d'entrée augmentent (> 4000) → tronquer press_summary et meteo_summary plus agressivement dans `main.py::_build_user_prompt()`

## Mesure de divergence ensemble vs legacy

Pour quantifier si la nouvelle narrative est cohérente avec l'historique legacy, un script utile (à créer si besoin) :

```sql
-- Compare confidence and direction across both tracks for the last N days
SELECT
  i_legacy.date,
  i_legacy.decision   AS legacy_decision,
  i_legacy.confidence AS legacy_conf,
  i_legacy.direction  AS legacy_dir,
  i_ens.decision      AS ens_decision,
  i_ens.confidence    AS ens_conf,
  i_ens.direction     AS ens_dir
FROM pl_indicator_daily i_legacy
JOIN pl_indicator_daily i_ens
  ON i_legacy.date = i_ens.date AND i_legacy.contract_id = i_ens.contract_id
WHERE i_legacy.algorithm_version_id = (SELECT id FROM pl_algorithm_version WHERE name='legacy')
  AND i_ens.algorithm_version_id    = (SELECT id FROM pl_algorithm_version WHERE name='ensemble_v1_softgate_wrapper')
  AND i_legacy.date > CURRENT_DATE - INTERVAL '30 days'
ORDER BY i_legacy.date DESC;
```

→ Si ensemble systématiquement +/- 1 vs legacy en confidence → suggérer de calibrer le prompt.
