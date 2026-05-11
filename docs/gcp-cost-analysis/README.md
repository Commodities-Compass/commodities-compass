# GCP Cost Analysis

Rapports mensuels de coûts GCP pour le projet `cacaooo` (Commodities Compass).

## Convention de nommage

Un fichier par mois : `YYYY-MM.md`.

## Procédure mensuelle

1. **Récupérer le CSV** : GCP Console → Billing → Reports → Export to CSV. Filtrer sur le mois écoulé. Group by **Service**.
2. **Dupliquer le rapport précédent** : `cp YYYY-MM.md $(date +%Y-%m).md` puis mettre à jour les chiffres.
3. **Mettre à jour les sections** :
   - § 1 Résumé exécutif
   - § 2 Données brutes (tableau CSV)
   - § 4 Analyse par service (vérifier ce qui a changé)
   - § 5 Optimisations (barrer celles appliquées, ajouter les nouvelles)
   - § 6 Évolution suggérée pour le mois suivant
4. **Flagger toute variation >50 %** vs mois précédent dans le résumé exécutif.
5. **Drill-down si nécessaire** : pour les services dont la variation est anormale, refaire l'export en groupant par **SKU** plutôt que par Service.

## Structure d'un rapport

1. Résumé exécutif (3-5 lignes)
2. Données brutes (tableau CSV)
3. Mapping coût → composant produit (backend / frontend / pipeline / ops)
4. Analyse détaillée par service GCP
5. Optimisations recommandées (triées par ROI)
6. Évolution suggérée pour le mois suivant
7. Annexe (commandes gcloud, procédure)

## Industrialisation future

Pour passer à un suivi automatisé :
- Activer l'**export BigQuery** du billing GCP (`gcloud billing accounts list` → activer dans la console).
- Créer un dashboard Looker Studio par-dessus.
- Ajouter des **budgets et alertes** sur les seuils dépassés.
