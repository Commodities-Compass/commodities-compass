# Brief Ensemble — Evolution Runbook

> How to add new sections, enrich existing ones, and roadmap for future improvements without breaking the dual-track contract. The ensemble brief is intentionally designed to be modular — you can add structured sections without touching the LLM Explainer.

## Architecture du brief ensemble (rappel)

Le brief est une concaténation de **7 sections** rendues par [brief_generator.py](../../backend/scripts/compass_brief_ensemble/brief_generator.py:render_brief). Chaque section est :

- **Pure formatter** : aucune logique métier, aucun appel DB, aucun LLM. Lit la dataclass `EnsembleBriefData`.
- **Indépendante** : modifier ou ajouter une section ne nécessite pas de toucher aux autres.
- **Testable** : `tests/test_brief_generator.py` lui passe une fixture `EnsembleBriefData` et compare le texte généré.

## Pattern pour ajouter une nouvelle section

### Cas 1 — La donnée existe déjà dans `EnsembleBriefData`

Exemple : tu veux ajouter une section « EXPOSURE FX » qui utilise `data.fx_gbpusd` (champ qui existerait déjà en DB et serait lu par `db_reader.py`).

Étapes :
1. Ouvrir [brief_generator.py](../../backend/scripts/compass_brief_ensemble/brief_generator.py)
2. Ajouter une section dans `render_brief()` :
   ```python
   # ── VIII — Exposure FX ────────────────────────────────────────────────
   lines.append("VIII — EXPOSURE FX")
   lines.append(SEP_THIN)
   lines.append(f"  GBP/USD : {_fmt(data.fx_gbpusd, 4)}")
   lines.append("")
   ```
3. Tester : `poetry run pytest scripts/compass_brief_ensemble/tests/`
4. Dry-run : `poetry run compass-brief-ensemble --target-date 2026-05-22 --dry-run`
5. PR + merge + reprend le cron normal

### Cas 2 — La donnée n'existe pas encore dans `EnsembleBriefData`

Exemple : tu veux ajouter une section « MACRO EVENT IMPACT » qui interroge une nouvelle table `pl_macro_event` que la R&D ajoute.

Étapes :
1. Ajouter le champ à `EnsembleBriefData` dans `db_reader.py`
2. Ajouter la lecture DB correspondante (`_read_macro_events()`)
3. L'appeler dans `read_brief_data()` et le passer dans la dataclass
4. Ajouter la section dans `brief_generator.py`
5. Ajouter un test dans `test_brief_generator.py` avec une fixture contenant ce nouveau champ
6. PR + merge + redéploiement

⚠️ Si tu ajoutes du DB read → checker que ça ne casse pas si la donnée est `None`/absente (l'ensemble brief doit fonctionner même sur dates où une table est vide).

## Roadmap d'enrichissements possibles

### Niveau 1 — Sections déjà disponibles, juste à coder
Toutes les données sont déjà en DB :

- **Section VIII — Cotation détail** : 5 derniers closes + volume + OI moving avg
  Source : `pl_contract_data_daily` (déjà lu pour le snapshot, étendre à 5 jours)
- **Section IX — Stocks regulators** : niveau STOCK_US + STOCK_EU + delta semaine
  Source : `pl_contract_data_daily.{stock_us, stock_eu_bags60kg}`
- **Section X — COT EU positioning** : Managed Money net, Producer/Merchant net
  Source : `pl_cot_eu_weekly` (déjà existante)
- **Section XI — FX context** : DXY proxy, GBP/USD
  Source : `pl_external_indicator` (déjà existante via FX scraper)
- **Section XII — Climate context** : ENSO ONI + Niño 3.4
  Source : `pl_external_indicator` (déjà existante via ENSO scraper)
- **Section XIII — Supply/Demand fundamentals** : ECA grindings YoY %, NCA grindings YoY %
  Source : `pl_supply_demand_observation` (créée P3)

Chacune = ~20-30 lignes de code dans `brief_generator.py` + 5-10 lignes dans `db_reader.py`. Aucun LLM nécessaire.

### Niveau 2 — Sections nécessitant calcul / signal processing

- **Section « PERSISTENCE BREAKDOWN »** : tableau qui montre pour chaque jour des 14 derniers, quelle était la décision (avec changement d'état marqué). Permet de voir les flips
- **Section « PRIORS CALIBRATION »** : comparer le prior structurel (e.g. `prior_open=0.51`) à la freq empirique récente des décisions. Indicateur de drift régime.
- **Section « SPECIALIST PERFORMANCE »** : pour chaque spécialiste, tableau de son accuracy 5d/20d/full (depuis `forward_return_6d`). Aide à voir quels spécialistes mènent le consensus.

Ces sections nécessitent du SQL plus complexe (rolling computations) mais restent déterministes.

### Niveau 3 — Sections enrichies par un LLM additionnel

Idée : un 2e appel LLM (« commenter section II ») qui transforme le tableau brut des 14 spécialistes en une narration éditoriale plus longue.

- Coût : 1 appel LLM supplémentaire par jour (~$0.001 si gpt-4o-mini)
- Bénéfice : audio NotebookLM plus engageant
- Risque : drift narrative-vs-data → ajouter un validator

Architecture si on le fait :
- Nouveau script `cc-ensemble-explainer-clusters` qui produit un commentaire sur cluster Winter vs Spring
- Stocke dans une nouvelle colonne `pl_indicator_daily.cluster_narrative` (TEXT)
- Le `brief_generator` lit cette colonne et la place dans la section II

### Niveau 4 — Brief hebdomadaire 5-day rolling

L'ensemble prédit J+4-J+5. Un brief hebdomadaire qui résume « cette semaine on a tenu OPEN les 4 derniers jours avec running_acc=0.91, on continue / on change » serait plus aligné avec l'horizon ML.

Implémentation :
- Nouveau script `cc-compass-brief-ensemble-weekly` (cron vendredi 19:35)
- Réutilise `brief_generator.py` partiellement + ajoute des sections agrégées
- Upload `WEEK_NN_YYYY-CompassBrief-Ensemble-Weekly.txt`
- Frontend optionnel : toggle entre brief daily et brief weekly

Hors scope actuelle PR mais nice-to-have pour Q3 2026.

## Changer le ton sans toucher au code

Tout passe par les prompts du LLM Explainer ([prompts.py](../../backend/scripts/ensemble_explainer/prompts.py)). Voir [ensemble-explainer-prompt-tuning.md](./ensemble-explainer-prompt-tuning.md) pour la procédure détaillée.

Exemples de ton possibles :
- **Magazine éditorial actuel** : sobre, neutre, en français, citations chiffrées
- **Tableau de bord** : très condensé, bullet points, sans prose
- **Narratif long** : explicatif, analogies, comparaisons historiques (~500 mots)
- **Provocateur** : « le marché ignore X » (pas conseillé pour audience trading sérieuse)

Le ton est entièrement dans le `SYSTEM_PROMPT` — pas besoin de redeploy si on remplace juste les instructions de style.

## Validation continue après évolution

Après tout changement structurel du brief :

1. **Tests** : `pytest scripts/compass_brief_ensemble/tests/` doivent rester verts
2. **Dry-run** sur 5 dates récentes représentatives (OPEN, HEDGE, MONITOR, anomaly, sentiment fort)
3. **Diff visuel** : prendre 1 brief avant et 1 après ton changement, mettre les 2 côte-à-côte
4. **Validation audio NotebookLM** : générer un audio depuis le nouveau brief, écouter — le format doit être audio-friendly (pas trop de symboles spéciaux qui se lisent mal)
5. **Cost check** : si on a ajouté un nouvel appel LLM, monitorer la première semaine sur le total LLM cost

## Garde-fous

- **Ne JAMAIS** ajouter une section qui modifie la décision (decision_wrapped reste immutable)
- **Ne JAMAIS** retirer une section qui contient des chiffres réglementaires (close, volume, decision) sans alternative claire — les utilisateurs s'y attendent
- **Toujours** garder les sections IV (presse) et V (météo) — c'est la « sensibilité humaine » du brief
- **Toujours** garder VII (recommandations + À SURVEILLER) — c'est ce que les utilisateurs lisent en premier
