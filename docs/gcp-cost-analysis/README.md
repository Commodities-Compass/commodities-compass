# GCP Cost Analysis

Rapports mensuels de coûts GCP pour le projet `cacaooo` (Commodities Compass).

## Convention de nommage

- `YYYY-MM.md` — le rapport technique du mois.
- `YYYY-MM-reponse-email.md` — *(optionnel)* la même analyse vulgarisée, quand un destinataire non-technique doit être adressé.

## Procédure mensuelle

1. **Récupérer le CSV** : GCP Console → Billing → Reports → Export to CSV. Filtrer sur le mois écoulé. Group by **Service**. Prendre aussi le **mois en cours (MTD)** pour la trajectoire.
2. **Réconcilier avant d'analyser** : la somme des colonnes *Subtotal* doit égaler le total affiché dans le bandeau. Si ça ne tombe pas, on lit le mauvais tableau.
3. **Dupliquer le rapport précédent** : `cp YYYY-MM.md $(date +%Y-%m).md` puis mettre à jour les chiffres.
4. **Mettre à jour les sections** :
   - § 1 Résumé exécutif
   - § 2 Données brutes (tableau CSV)
   - § 4 Analyse par service (vérifier ce qui a changé)
   - § 5 Optimisations (barrer celles appliquées, ajouter les nouvelles)
   - § 6 Évolution suggérée pour le mois suivant
5. **Flagger toute variation >50 %** vs mois précédent dans le résumé exécutif.
6. **Drill-down si nécessaire** : pour les services dont la variation est anormale, refaire l'export en groupant par **SKU** plutôt que par Service.

## Pièges connus

- **Usage brut ≠ net facturé.** Jusqu'à mai 2026, ~€49/mois de crédits promo masquaient la facture (on payait ~10 %). Toute comparaison de tendance qui traverse mai/juin 2026 doit se faire sur l'**usage brut**, sinon on lit une fausse explosion.
- **Un coût sans ressource visible.** Le connector VPC est facturé dans **Compute Engine**, pas dans Networking — le projet peut afficher 0 VM et coûter €14/mois de Compute. Croiser systématiquement le poste avec l'inventaire `gcloud`.
- **La prévision de fin de mois de la console est optimiste** sur les crédits (constaté août 2026 : −€12 prévus vs −€6 extrapolés du réel). Recalculer le run-rate à la main.
- **Un mois où une optimisation est livrée est un mois hybride** — le vrai régime établi se lit sur le run-rate du mois suivant, pas sur le mois de livraison.

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
