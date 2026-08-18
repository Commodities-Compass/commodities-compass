# Aligner la colonne ● « Livré dès l'abonnement » — Offre V1.1

**Statut :** Proposed (non implémenté)
**Date :** 2026-07-16
**Owner :** Hedi
**Slug :** `align-offre-v11-livre`
**Cible repo :** `docs/user-stories/P1-align-offre-v11-colonne-livree.md`
**Réfs :** `docs/strategy/compass-tech-data-gap-vs-offres-v1.pdf` · deck commercial *Offres par segment V1.1*

---

## 1. Contexte

La grille commerciale **V1.1** distingue explicitement ce qui est **● livré dès l'abonnement** de ce qui est **◐ co-construit (Programme Fondateur)**. C'est le bon cadrage — mais il crée un contrat : **la colonne ● doit être 100 % vraie avant la première signature Fondateur**, sinon on facture une promesse.

L'audit Tech a identifié **5 petits écarts** où le deck annonce « livré » alors que le code ne le fait pas encore (ou pas de façon opérationnelle). Ils sont tous petits — l'objectif de cette US est de **rendre le vert irréprochable en ≤ 1 semaine**, pour pouvoir pitcher les Fondateurs en toute confiance.

Ce n'est **pas** le chantier « signal origine » (différentiels, arrivées, prix terrain) — celui-là est en co-construction, séparé, et de tout autre ampleur.

---

## 2. Goals & non-goals

### Goals (cette itération)
- Rendre vrais les 5 items de la colonne ● : **prix bord champ officiel**, **conversion FCFA**, **podcast quotidien fiabilisé**, **export de séries**, **accès multi-comptes opérationnel**.
- Chaque item : livré **honnêtement** (une valeur de référence n'est pas un flux live ; un accès partagé n'est pas du multi-tenant) et **labellisé** comme tel côté produit.

### Non-goals
- ❌ Scraper automatique du prix bord champ (fréquence trimestrielle → saisie manuelle suffit).
- ❌ GHS spot live (« cedi en sourcing » reste co-construct).
- ❌ Automatisation NotebookLM (= US-008, backlog séparé).
- ❌ Multi-tenant complet, rôles/quotas applicatifs, isolation par client (= chantier socle SaaS, séparé).
- ❌ API self-service à clés/quotas/métering (= co-construct Entreprise).
- ❌ Prix bord champ **réel/terrain**, différentiels, arrivées (= Programme Fondateur).

---

## 3. État actuel (vérifié dans le code)

| Item | Statut | Preuve |
|---|---|---|
| Prix bord champ officiel CCC/COCOBOD | ❌ Absent | aucune structure ; seul un commentaire `pipeline.py:851` évoque de futures fundamentals COCOBOD |
| Conversion FCFA | ❌ Absent | FX = EUR/USD, GBP/EUR, DXY proxy uniquement (`pl_external_indicator`) ; FCFA non dérivé |
| Podcast quotidien FR | ◐ Partiel | brief `.txt` **automatisé**, mais étape NotebookLM **manuelle** (`compass_brief/README.md:115` — « Steps 1-3 remain manual until US-008 ») |
| Export des séries | ❌ Absent | aucun endpoint d'export ; seul `audio.py` fait du `StreamingResponse` (flux audio Drive) |
| Accès « N sièges » | ❌ Absent | aucun modèle tenant/account/seat ; tout user Auth0 voit la même vue globale |

---

## 4. Les 5 chantiers

### T1 — Prix bord champ officiel CCC/COCOBOD  *(~2-3 j)*
**Objectif :** afficher le prix garanti officiel — CIV (**FCFA/kg**, CCC) et Ghana (**GHS / sac 64 kg**, COCOBOD) — sur le dashboard et dans le brief/podcast.

**Approche :**
- Table append-only `pl_official_farmgate_price` : `region (civ|ghana)`, `season_label`, `effective_date`, `announced_date`, `price_native`, `currency`, `unit (per_kg|per_bag_64kg|per_tonne)`, `source (ccc|cocobod)`, `source_url`. **Chaque révision = nouvelle ligne** (immuable, aligné North Star). Domaine = pipeline (`pl_`).
- Modèle SQLAlchemy + migration Alembic *(rappel règle repo : migration mergée sur `main` → déployée, jamais appliquée en prod depuis une feature branch)*.
- CLI `poetry run set-farmgate-price --region … --price … --effective-date … --source-url …` (saisie ops, quelques lignes/an).
- Endpoint `/v1/dashboard/farmgate-price` → dernière valeur effective ≤ date demandée, par région.
- Affichage front + 1 ligne dans le brief.

**Critères d'acceptation :**
- La valeur courante CIV **et** Ghana s'affiche sur le dashboard à la bonne date.
- Une révision de prix crée une nouvelle ligne sans écraser l'historique.
- Le libellé indique clairement **« officiel / garanti »** (distinct du prix réel terrain).

### T2 — Conversion FCFA  *(~0,5 j)*
**Objectif :** afficher le FCFA à côté des taux EUR/USD/GBP.

**Approche :** dérivation à l'affichage à partir de l'EUR déjà ingéré — **parité fixe** `1 EUR = 655,957 XOF/XAF` (constante en config, documentée). Pas de nouvelle colonne obligatoire (calcul au transform/read).

**Critères d'acceptation :**
- Le FCFA s'affiche, cohérent avec l'EUR du jour.
- La source (parité fixe) est documentée ; aucune promesse de « taux flottant ».

### T3 — Podcast quotidien FR fiabilisé  *(~0,5 j)*
**Objectif :** garantir qu'un audio existe **chaque jour de séance** — l'étape NotebookLM étant encore manuelle.

**Approche (MVP cette semaine, sans faire US-008) :** process ops documenté (owner + fenêtre horaire + checklist) **+ garde-fou** : une vérification quotidienne qui alerte (Sentry/log) si l'audio du jour est absent du dossier Drive à H+X.

**Critères d'acceptation :**
- Un audio est publié chaque jour de séance, **ou** une alerte se déclenche si absent.
- Le process manuel est documenté ; US-008 (automatisation) reste tracé en backlog.
- ⚠️ *Coût ops récurrent assumé et communiqué au commercial (« quotidien » = un humain jusqu'à US-008).*

### T4 — Export des séries de données (Entreprise)  *(~1-2 j)*
**Objectif :** livrer les séries en fichiers structurés — bridge honnête avant l'API self-service.

**Approche MVP :** endpoint authentifié (Auth0) `/v1/data/export?series=…&from=…&to=…&format=csv|json` → `StreamingResponse` + `Content-Disposition: attachment`. Périmètre = séries déjà prêtes (OHLCV, indicateurs, COT, stocks, météo, FX). **Pas** de clés/quotas/métering (co-construct).

**Critères d'acceptation :**
- Un compte Entreprise récupère une série en CSV/JSON sur une plage de dates.
- Périmètre des séries documenté ; aucune donnée sensible/PII exposée.

### T5 — Accès multi-comptes « N sièges » — version opérationnelle  *(~0,5 j)*
**Objectif :** servir « N utilisateurs » par abonnement de façon opérationnelle et honnête, sans le socle multi-tenant.

**Approche MVP :** procédure ops documentée pour provisionner/révoquer **N logins Auth0 par client**, avec la limite explicitement écrite (**vue partagée, pas d'isolation ni de quota applicatif**). Aucune refonte data cette semaine.

**Critères d'acceptation :**
- Procédure documentée pour créer/retirer N accès par client.
- La limite (pas d'isolation par siège) est écrite noir sur blanc et transmise au commercial.
- La gestion d'équipe complète (rôles, quotas, isolation) reste tracée en co-construct/backlog.

---

## 5. Séquencement & estimation

| Ordre | Chantier | Effort | Dépendance |
|---|---|---|---|
| 1 | T2 — FCFA | ~0,5 j | aucune |
| 2 | T1 — bord champ officiel | ~2-3 j | migration via `main` |
| 3 | T4 — export séries | ~1-2 j | aucune |
| 4 | T3 — podcast fiabilisé | ~0,5 j | accès Drive |
| 5 | T5 — N sièges (ops) | ~0,5 j | aucune |

**Total ≈ 5-6 j dev → tient dans la semaine.** T1, T2, T4 = code ; T3, T5 = process + garde-fou léger.

---

## 6. Risques / points ouverts

- **T3** est le seul item avec un **coût ops récurrent** (génération manuelle quotidienne) — à assumer explicitement côté commercial jusqu'à US-008.
- **T1** exige une **discipline de mise à jour** lors des révisions ad-hoc CCC/COCOBOD (rappels calendrier oct/avril).
- **T1 (Ghana)** : le prix est en **GHS/sac** — la conversion vers une devise commune touche le trou **GHS FX** (hors scope ici, affichage en unité native OK).
- **T5** : bien communiquer la limite d'isolation ; c'est un placeholder honnête, pas le vrai multi-tenant.

---

## 7. Definition of Done

- [ ] Les 5 items de la colonne ● sont vrais et labellisés honnêtement.
- [ ] Migration T1 mergée sur `main` et déployée (règle prod).
- [ ] `docs/strategy/compass-tech-data-gap-vs-offres-v1.pdf` : statuts mis à jour (les 5 passent au vert).
- [ ] Message à la Direction Commerciale : « colonne ● signée Tech ».
