# Scrapers de Données Fondamentales — Chantier 2

**Statut :** Partiellement shippé (ECA + NCA livrés, ICCO différé)
**Date :** 2026-04-20 (spec) / 2026-05-26 (statut)
**Owner :** Hedi
**Cible repo :** `docs/user-stories/P3-fundamental-data-scrapers-grindings.md`

> **2026-05-26 — Statut actuel** :
> - **Shippé** : scrapers ECA et NCA grindings, calendar-gated via `ref_publication_calendar`, table unifiée `pl_supply_demand_observation` (EAV-style — évite la confusion avec `pl_fundamental_article`). Daily watchdog `cc-publication-calendar-watchdog` qui alerte si une publication attendue n'arrive pas dans les 21 jours. Backfills disponibles (7y ECA, 5y NCA). Voir [CLAUDE.md](../../CLAUDE.md) sections « ECA Grindings Scraper » + « NCA Grindings Scraper » + « Publication Calendar Watchdog ».
> - **Différé** : ICCO Monthly Review — data structurée (production_kt, grindings_kt, surplus_deficit_kt) est **paywallée** (member-area ICCO). Seul un résumé narratif HTML est public, sans les chiffres. À ré-évaluer si Compass devient membre ICCO ou si la politique change.
> - **Hors scope cette itération** : CCC arrivages (site instable), COCOBOD (à investiguer), CGA Asia.

## Context

EXP-014 (validé 14 avril 2026) a montré que les thèmes **production** (p=0.017) et **chocolat** (p=0.025) portent un signal Granger significatif à lag 3-4 dans les deltas de sentiment. Ce signal vient du récit narratif quotidien, pas des data points eux-mêmes.

Cependant, les data points fondamentales structurées (grindings, arrivages, production) sont complémentaires :
1. Elles alimentent directement le moteur d'indicateurs comme features fondamentales
2. Elles créent les **événements** qui font bouger le sentiment quotidien (une publication de grindings ECA déclenche un shift narratif capté par le Flux 1)
3. Elles permettent de cross-valider le sentiment extrait de la press review

Ce chantier est **séparé de la press review** (Chantier 1). La press review capte le sentiment quotidien ; ces scrapers ingèrent les data structurées à basse fréquence.

## Pourquoi pas dans la press review ?

| Critère | Press Review (Chantier 1) | Scrapers Fondamentaux (Chantier 2) |
|---------|---------------------------|-------------------------------------|
| Fréquence | Quotidienne | Hebdo/Mensuel/Trimestriel |
| Nature | Narrative, sentiment, opinion | Data points structurés (tonnes, %) |
| Signal | z-delta sentiment (EXP-014) | Direct feed dans indicators engine |
| Consumer | Dashboard humain + extraction sentiment | Engine machine (composite score) |
| Sources | News sites quotidiens | PDFs officiels à dates fixes |

Injecter des PDFs trimestriels dans le press review crée un mismatch : 90% des jours la source retourne rien de neuf, et le jour de publication le chiffre est noyé dans du prose au lieu d'être stocké structuré.

## Sources et données

### Grindings (demande chocolat — trimestriel)

Détails complets dans [icco-grinding-alerts.md](icco-grinding-alerts.md).

| Source | Zone | Fréquence | Format | Scrapable |
|--------|------|-----------|--------|-----------|
| ECA (European Cocoa Association) | Europe (~40% grindings mondiaux) | Trimestriel | PDF public, URL prédictible | Oui (httpx) |
| NCA (National Confectioners Association) | Amérique du Nord | Trimestriel | Page web publique | Oui (httpx + BS4) |
| CGA (Cocoa Association of Asia) | Asie | Trimestriel | Site Wix, à investiguer | À déterminer |

### Production / Arrivages (offre — hebdo/mensuel)

| Source | Zone | Data | Fréquence | Format | Scrapable |
|--------|------|------|-----------|--------|-----------|
| CCC (Conseil Café-Cacao) | Côte d'Ivoire | Arrivages ports (Abidjan, San Pedro) | Hebdo/mensuel | Communiqués web | À investiguer — site parfois instable |
| COCOBOD | Ghana | Production, achats LBC | Mensuel | Rapports | À investiguer |
| ICCO Monthly Review | Mondial | Crop forecasts, surplus/deficit | Mensuel | PDF | Oui (httpx) |

### Tables cibles

```
pl_grindings_data (trimestriel)
  date | source (eca/nca/cga) | quarter | region | volume_tonnes | yoy_pct

pl_arrivals_data (hebdo/mensuel)
  date | source (ccc/cocobod) | country | port | volume_tonnes | cumul_season | yoy_pct

pl_crop_forecast (mensuel/trimestriel)
  date | source (icco) | season | production_kt | grindings_kt | surplus_deficit_kt
```

## Stratégie

### Phase actuelle — Calendar reminders (déjà en place)

Voir [icco-grinding-alerts.md](icco-grinding-alerts.md) Phase 1.

### Phase suivante — Scrapers automatisés

Pattern identique aux scrapers existants (ice_stocks, cftc) :
- Cloud Run Job + Cloud Scheduler
- httpx + BS4 (ou PDF extraction pour ECA)
- Upsert dans tables dédiées
- Cron adapté à la fréquence de chaque source

### Intégration engine

Une fois les données stockées, elles peuvent :
1. Alimenter le moteur d'indicateurs comme nouvelles features fondamentales
2. Être injectées comme contexte dans le prompt du Daily Analysis
3. Être affichées dans un widget dashboard "Fondamentaux long-terme"

## Priorité

Ce chantier est P2 par rapport au Chantier 1 (press review orientée signaux). Raisons :
- Le signal Granger est capté par le sentiment quotidien (Chantier 1), pas par les data points
- Les data fondamentales alimenteront le moteur V2 qui n'est pas encore en production
- Le volume de données (trimestriel) ne justifie pas d'urgence technique

Démarrage recommandé : après stabilisation du Chantier 1, ou quand ECA Q1 2026 est publié (16 avril 2026) pour valider le scraper sur un cas réel.
