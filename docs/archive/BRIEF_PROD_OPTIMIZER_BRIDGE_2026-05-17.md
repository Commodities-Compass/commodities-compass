# Brief — Pont Optimizer ↔ Com Compass Prod

```yaml
from:         Hedi (CTO, Com Compass + R&D Compass)
to:           Agent prod Com Compass
date:         2026-05-17
re:           Pont read-only entre Com Compass prod et l'Optimizer cockpit (sandbox Julien)
source_note:  ../../NOTE_HEDI_2026-05-16.md
status:       proposal — challenge welcome
```

## TL;DR

- **Demande Julien** : afficher dans son cockpit Optimizer (Flask sandbox, séparé de la prod) la prédiction OPEN/HEDGE/MONITOR du jour suivant, avec features fraîches (OHLC daily + COT LCE weekly + ERA5/ENSO monthly avec carry-forward). Voir `NOTE_HEDI_2026-05-16.md` pour la spec brute.
- **Solution proposée** : une **route API read-only protégée côté Com Compass prod** qui retourne 1 ligne de features pour la dernière session ouvrée (ou un `as_of` passé). L'Optimizer la consomme à la demande. Pas de duplication de feature engineering, pas d'accès BDD direct depuis l'Optimizer.
- **⚠️ Caveat critique** : R&D Phase 5 a invalidé le signal directionnel sur cocoa post-2024-01-30 ([FH-003, FH-004, FH-005](../../knowledge/failed-hypotheses.md)). Cet endpoint sert un **outil d'observation pour 1 user**, pas un edge tradeable. À calibrer en investissement infra en conséquence (voir section 8).

**Ce que ce doc N'EST PAS** :
- Pas une spec de retraining de modèle.
- Pas un endpoint pour scoring sur de vrais utilisateurs Com Compass.
- Pas un produit. Une primitive read-only pour permettre à Julien d'arrêter de me demander des extracts manuels.

---

## 1. Topologie 3 projets

L'agent prod connaît bien Com Compass. Cette section décrit les **deux autres** projets qui gravitent autour et qui ne sont PAS dans son périmètre.

| Aspect            | **Com Compass prod**               | **R&D Compass**                          | **Optimizer sandbox (Julien)**          |
|-------------------|------------------------------------|------------------------------------------|------------------------------------------|
| Owner             | Hedi (CTO)                         | Hedi + Julien (commun)                   | Julien (perso)                           |
| Location          | `~/Developer/work/commodities-compass/` (à confirmer côté agent prod) | `~/Developer/work/RnD_Compass/`          | `~/Developer/.../compass_backtest/` (côté Julien) |
| Runtime           | GCP full stack (Cloud Run / GKE)   | Local + scripts Python                   | Flask local sur sa machine               |
| Data store        | Cloud SQL Postgres                 | Parquet snapshots + CSV canoniques       | CSV local + JSON algo                    |
| Qui peut y écrire | Agent prod + Hedi                  | Hedi (DB ops) + Julien (research outputs)| Julien seul                              |
| Prod traffic      | Oui — vrais utilisateurs           | Aucun — usage interne recherche          | Aucun — usage perso Julien               |
| Scope             | Produit Com Compass                | Knowledge base + experiments R&D         | Cockpit recherche perso                  |

**Flux data actuel** :

```
                                          ┌─────────────────────────────────────────┐
                                          │  Com Compass prod (BDD Cloud SQL)       │
   Scrapers daily ───────────────────────►│  • pl_contract_data_daily               │
   (cours, COT EU, ERA5, ENSO, news, ...) │  • pl_derived_indicators                │
                                          │  • pl_article_segment                   │
                                          │  • pl_cot_eu_weekly                     │
                                          │  • ...20 tables au total                │
                                          └────┬────────────────────────────────────┘
                                               │
                ┌──────────────────────────────┼──────────────────────────────────┐
                │                              │                                  │
                ▼                              ▼                                  ▼
    ┌────────────────────┐      ┌───────────────────────────────┐      ╔═══════════════════════╗
    │ App prod (users)   │      │ scripts/export_db_snapshot.py │      ║  NOUVEAU              ║
    │ — Cloud Run service│      │ → data/db_snapshots/latest/   │      ║  Route API protégée   ║
    │ — existant         │      │ → distribué via Git LFS       │      ║  /api/rnd/features/   ║
    └────────────────────┘      │ → R&D experiments             │      ║  latest               ║
                                └───────────────────────────────┘      ╚═══════════╤═══════════╝
                                                                                   │
                                                                                   ▼
                                                                       ┌──────────────────────┐
                                                                       │ Optimizer cockpit    │
                                                                       │ (Flask perso Julien) │
                                                                       │ → consomme l'API     │
                                                                       │ → applique sa formule│
                                                                       └──────────────────────┘
```

**Hard rule** : Julien a un bearer token read-only sur la nouvelle route. Il ne touche **ni le code prod, ni la BDD prod, ni le Cloud SQL Auth Proxy, ni le service account des scrapers**. Si tu vois un commit de Julien sur le repo prod, c'est une erreur.

---

## 2. Boundary contract

Section load-bearing. Trois sous-blocs.

### 2.1 Ce que prod DOIT exposer

**Endpoint unique** :

```http
GET /api/rnd/features/latest?commodity=cocoa&as_of=YYYY-MM-DD
Authorization: Bearer <julien_token>
```

- `commodity` : pour l'instant `cocoa` only. Future-proof — autres commodities possibles si R&D pivote (Phase 5a).
- `as_of` (optionnel) : date ISO. Défaut = dernière session ouvrée connue.

**Réponse JSON** (schema indicatif, ajuste selon ton stack) :

```json
{
  "as_of": "2026-05-16",
  "commodity": "cocoa",
  "schema_version": "1.0.0",
  "prod_commit_sha": "abc1234",
  "feature_row": {
    "date": "2026-05-16",
    "open": 7842.0,
    "high": 7901.5,
    "...": "...",
    "rsi_14d": 58.3,
    "macd": 12.1,
    "cot_lce_mm_z": -0.42,
    "oni": 0.8,
    "...": "...92 colonnes au total"
  },
  "freshness": {
    "ohlc_last_close":        { "date": "2026-05-16", "lag_days": 0 },
    "cot_lce_last_release":   { "date": "2026-05-13", "lag_days": 3 },
    "era5_enso_last_month":   { "date": "2026-04-01", "lag_days": 46 },
    "sentiment_last_ingested":{ "date": "2026-05-16", "lag_days": 0 }
  }
}
```

- **Read-only**, idempotent, zéro write DB.
- Auth obligatoire — sinon `401`.
- Si une feature ne peut pas être calculée (ex : COT en attente de release), valeur = `null` + flag dans `freshness`. Pas d'invention silencieuse.

### 2.2 Ce que l'Optimizer NE PEUT PAS faire

- Pas de query directe sur Cloud SQL.
- Pas d'invocation manuelle des scrapers.
- Pas de recompute de features côté Optimizer (sinon on duplique la logique et on diverge).
- Pas de schema drift silencieux : l'Optimizer **doit valider** la réponse contre `cocoa_rd_dataset_20260512.meta.json` (92 colonnes, types). Si divergence → **fail loud**, pas de coercion implicite.

### 2.3 Ce que R&D Compass apporte comme référence canonique

Le script feature-builder côté prod (Chantier 1) doit répliquer **exactement** la logique de :

| Aspect             | Référence R&D Compass                                                                     |
|--------------------|--------------------------------------------------------------------------------------------|
| Lag policy ENSO    | `methodology/external_data.py` — ENSO shift +14j (NOAA publication mid-mois)              |
| Carry-forward      | `methodology/external_data.py` — `merge_asof(..., direction="backward")` + ffill          |
| COT release-aware  | `methodology/external_data.py` + meta.json `cot_asof_tolerance_days=14`                   |
| Fundamentals lag   | meta.json `fundamentals_months=2` (publié 2 mois après date de référence)                 |
| Sentiment ffill    | meta.json `sentiment_ffill_days=7`                                                         |
| Forward-return     | `methodology/data_loader.py` — `forward_return_Hd = (close.shift(-H) - close) / close`    |
| No look-ahead      | `methodology/data_loader.py` — `temporal_split` strict, `walk_forward_windows`            |
| Schema pin (92 col)| `output/rd_extract/cocoa_rd_dataset_20260512.csv` + `.meta.json` (SHA-256, null% par col) |
| Dictionnaire col   | `output/rd_extract/cocoa_rd_dataset_20260512.dictionary.md`                               |

**Acceptance test** : pour `as_of=2026-05-12`, l'endpoint prod doit renvoyer une `feature_row` dont les 92 valeurs matchent la dernière ligne de `cocoa_rd_dataset_20260512.csv` (tolérance numérique sur les floats, ex : `rtol=1e-6`).

---

## 3. Chantier 1 — Endpoint feature prod

**Owner** : agent prod. **Reviewer** : Hedi.

**Goal** : 1 route + 1 script back qui produit 1 ligne de features lag-aware schema-pinned.

### Deliverables

1. **Route handler** (`app/rnd_bridge/routes.py` ou équivalent dans ton archi) :
   - Validation query params (`commodity`, `as_of`).
   - Middleware auth bearer token.
   - Logging structuré (Cloud Logging) avec `caller`, `as_of`, `latency_ms`, `schema_version`.

2. **Script feature-builder** (`app/rnd_bridge/build_features.py`) :
   - Charge OHLC depuis `pl_contract_data_daily` (front-month, max volume) — même logique que R&D extract.
   - Charge derived indicators depuis `pl_derived_indicators`.
   - Charge COT depuis `pl_cot_eu_weekly` avec release-date-aware merge.
   - Charge ENSO/ERA5 depuis sources externes ou tables internes — applique le lag policy `methodology/external_data.py`.
   - Calcule sentiment via pivot `pl_article_segment` (zone × theme).
   - Concatène en 92 colonnes ordonnées comme `cocoa_rd_dataset_20260512.csv`.
   - Hedi peut scaffolder le squelette en portant `methodology/external_data.py` + le SQL utilisé par R&D extract. Je le fais en revue plutôt qu'en pull, pour respecter ta gouvernance de modifs prod.

3. **Validateur de schema** :
   - Lit `cocoa_rd_dataset_20260512.meta.json` (transporté côté prod ou téléchargé depuis le repo R&D).
   - Vérifie les 92 colonnes + types avant retour.
   - Si divergence : log `ERROR`, retourne `503` + `schema_drift: true` dans la réponse.

4. **Middleware auth** :
   - Bearer token unique pour Julien.
   - Token stocké dans Secret Manager.
   - Rotation manuelle (pas d'automatique pour ce niveau d'usage).

5. **Test d'intégration** (à automatiser en CI prod) :
   - `as_of=2026-05-12` → diff la `feature_row` contre la dernière ligne de `cocoa_rd_dataset_20260512.csv`.
   - Si tolérance dépassée sur n'importe quelle colonne → fail.
   - Le fichier de référence peut être checkout depuis le repo R&D ou mirroré dans le CI prod.

### Implementation notes (non prescriptif)

- **Module isolé** : suggère `app/rnd_bridge/` (ou nom équivalent) comme module séparé, **facile à supprimer** si R&D pivote de commodity ou tue la track Optimizer (voir caveat Phase 5).
- **Cache strategy** : à discuter (voir questions ouvertes section 6). Mon penchant : in-memory 60min, OHLC ne bouge qu'à la clôture.
- **Réutilise** la couche feature-engineering prod si elle existe déjà (probable). Sinon implémente contre la lag spec R&D — on évite la double maintenance.
- **Pas d'écriture en BDD prod** depuis ce module. Lecture seule sur les tables, calculs en mémoire.

### Acceptance criterion explicite

Parité numérique avec `cocoa_rd_dataset_20260512.csv` sur la dernière session connue (2026-05-12), tolérance `rtol=1e-6 / atol=1e-8` sur les colonnes float. Sinon, on ne déploie pas.

---

## 4. Chantier 2 — Intégration scrapers daily

**Owner** : agent prod (plomberie scraper) + Hedi (contrat ingestion R&D).

**Goal** : Optimizer voit les outputs des scrapers Com Compass quotidiennement, sans que Julien touche quoi que ce soit.

### Deliverables

1. **Documenter le hook post-scraper** existant côté prod : cron, Pub/Sub, Cloud Scheduler ? Quels scrapers tournent, à quelle fréquence, quels SLA de fraîcheur ?
   - L'objectif : que Julien ait une réponse propre quand il demande "quelles sources, quelle fréquence, quel format" (cf. NOTE_HEDI section 2.1).
   - Pas besoin de réécrire — juste documenter ce qui existe dans un format consommable.

2. **Décision** : Julien a-t-il besoin des tables raw, ou la `feature_row` du Chantier 1 suffit ?
   - **Hypothèse Hedi** : la feature_row suffit pour 90% des cas. Les 92 colonnes du dataset canonique couvrent déjà toutes les features ingérées par R&D.
   - **Si raw nécessaire** (ex : Julien veut faire son propre pivot sentiment) → second endpoint `GET /api/rnd/raw/{table}?since=YYYY-MM-DD` avec la denylist de `scripts/export_db_snapshot.py` (pas d'`aud_/alembic/test_`). Read-only, mêmes auth + cache que Chantier 1.

3. **R&D référence** : `data/db_snapshots/latest/_manifest.json` définit déjà le whitelist 20-tables utilisé par R&D. Reprendre cette liste pour le second endpoint si décidé.

### Coût

Snapshots R&D complets = 3.5 MB total (20 tables, Parquet zstd). Un pull quotidien depuis l'Optimizer est trivial. Pas de streaming, pas de Pub/Sub côté Julien.

---

## 5. Chantier 3 — Wiring sandbox Julien

**Owner** : Julien. **Support** : Hedi.

**Goal** : son cockpit appelle l'endpoint prod, applique sa decision function V8.x, affiche J+1 + badges de fraîcheur.

### Deliverables (chez Julien, pas chez toi)

- Client wrapper Python dans son repo Optimizer.
- Cache local (TTL au choix, ex : 1h).
- Badge UI rouge/ambre/vert piloté par `freshness` :
  - 🟢 toutes sources < lag attendu.
  - 🟡 1 source dépasse le lag médian (ex : COT > 7j).
  - 🔴 1 source dépasse le lag max acceptable (ex : ERA5 > 60j ou OHLC > 1 jour ouvré).
- Bloc HTML « PROCHAINE PRÉDICTION » dans le cockpit, refresh auto toutes les 10 min (cf. NOTE_HEDI 1.4).

**Important** : tu (agent prod) ne reviews PAS ce code. Mentionné ici pour que tu visualises la boucle complète. Le sandbox Optimizer reste sous la responsabilité de Julien.

---

## 6. Questions ouvertes pour l'agent prod

À chaque question, ma position (lean) en italique — challenge bienvenu si ton contexte d'infra impose autre chose.

1. **Auth** : bearer static dans Secret Manager vs IAP vs signed URL ?
   *Lean : bearer + IP allowlist sur le réseau de Julien. Cheap, un seul user, rotation manuelle OK.*

2. **Cache TTL vs recompute** à chaque call ?
   *Lean : in-memory 60 min keyed sur `(commodity, as_of)`. L'OHLC ne change qu'à la clôture, recomputer pour chaque refresh UI de Julien serait du gaspillage. Si tu préfères pas de cache pour simplicité opérationnelle, OK aussi — le volume est faible.*

3. **Rate limit** ?
   *Lean : 60 req/h hard, 10 req/min burst. Largement assez pour un user qui rafraîchit un cockpit toutes les 10 min.*

4. **Deployment env** : même service Cloud Run que l'app prod ou sidecar isolé ?
   *Lean : sidecar Cloud Run dédié `compass-rnd-bridge`. Isole le blast radius des vrais users — si le module plante, l'app prod n'est pas affectée. Cohérent avec la suppressibilité du module (caveat Phase 5).*

5. **Observability** :
   *Lean : Cloud Logging structuré (caller, as_of, latency, schema_version) + alerte Monitoring sur `schema_drift=true` ou erreur 5xx. Pas de dashboard dédié — on regardera à la demande.*

6. **Schema drift handling** : hard fail (503) vs soft warn (200 + flag) quand prod diverge du `.meta.json` ?
   *Lean : **hard fail 503**. Si l'Optimizer reçoit une feature_row avec moins de 92 colonnes, sa decision function va casser silencieusement. Mieux vaut que Julien voie un 503 et me ping que de prendre une décision sur des features partielles.*

7. **Backfill** : `as_of` accepte-t-il des dates passées ?
   *Lean : accepte `as_of` sur les 90 derniers jours. Au-delà → erreur 400 avec message "use R&D snapshots". Justifie : la BDD prod garde au moins 90j de derived indicators frais ; au-delà, le carry-forward peut diverger légèrement.*

8. **Versioning** : comment l'Optimizer sait que prod a changé les définitions de features ?
   *Lean : `schema_version` dans le payload (sem-ver). Bumpé manuellement à chaque PR touchant `app/rnd_bridge/`. Tu maintiens un `CHANGELOG.md` dans le module. Julien check la version au démarrage de son cockpit ; si différente de celle pinned, il warn dans son UI.*

---

## 7. ⚠️ Caveat Phase 5 — À lire avant de coder

Citation directe du `CLAUDE.md` (état au 2026-05-13) :

> Phase 4 Track C ALSO failed: EXP-041 strict pre-break/post-break temporal split shows all 4 h=22d configs are statistically significant anti-signal on 2025-2026. Same regime-inversion pattern as Phase 3 (FH-003) and Track D (FH-004). Now FH-005 confirms the third independent rejection — **the project has no surviving exploitable signal on cocoa across any horizon (daily / 5d / 22d) or feature class (technical / fundamental / sentiment / IV / EU stocks / COT positioning)**.

### Implication pour l'agent prod

- **Ne pas sur-investir** sur ce module :
  - Pas de SLA contractuel.
  - Pas de high-availability target — un downtime de quelques heures sur ce endpoint est acceptable, on prévient Julien Slack et c'est OK.
  - Pas d'auto-retraining hook, pas de pipeline ML behind, pas de monitoring de modèle.
  - C'est un outil d'**observation pour 1 user**, pas un produit.

- **Suppressibilité prioritaire** :
  - Si R&D pivote vers une autre commodity (Phase 5a — option en discussion), il faut pouvoir renommer / déplier le module proprement.
  - Si R&D tue la track Optimizer entièrement (Phase 5b/5c), il faut pouvoir supprimer `app/rnd_bridge/` en 1 PR sans tirer de dépendances ailleurs.
  - D'où l'insistance sur un module isolé en Chantier 1 (pas de hooks dans le code app principal, pas de schéma partagé).

- **Échelle d'effort recommandée** : ~3-5 jours côté toi (route + script + test + déploiement). Si tu pars sur > 2 semaines, on a un mismatch de scope, ping-moi.

---

## 8. Index de fichiers référencés

Tous les paths sont relatifs à `/Users/hediblagui/Developer/work/RnD_Compass/` (le repo R&D Compass, accessible à Hedi en lecture pour toi via Hedi).

| Fichier                                                      | Rôle                                               |
|--------------------------------------------------------------|----------------------------------------------------|
| `methodology/external_data.py`                               | Lag policy ENSO/FX, carry-forward, merge_asof      |
| `methodology/data_loader.py`                                 | Forward-return, temporal split, walk-forward       |
| `methodology/features.py`                                    | FeatureSpec dataclass, 4 groupes de features       |
| `methodology/features_external.py`                           | ENSO_FEATURES, FX_FEATURES, transforms zscore      |
| `output/rd_extract/cocoa_rd_dataset_20260512.csv`            | Dataset canonique 92 colonnes (2016–2026)          |
| `output/rd_extract/cocoa_rd_dataset_20260512.meta.json`      | Schema pin (SHA-256, lags, ffill rules)            |
| `output/rd_extract/cocoa_rd_dataset_20260512.dictionary.md`  | Sémantique de chaque colonne                       |
| `scripts/export_db_snapshot.py`                              | Allowlist/denylist tables, baseline snapshot logic |
| `data/db_snapshots/latest/_manifest.json`                    | 20 tables exportées + sha256 + row counts          |
| `NOTE_HEDI_2026-05-16.md`                                    | Demandes originales de Julien                      |
| `CLAUDE.md` (section "Current State")                        | Verdict Phase 5 — caveat signal-is-dead            |

---

## 9. Next steps

1. **Agent prod** : lis ce brief + les 9 fichiers référencés (Hedi te les transfère ou tu y as accès via le repo R&D). Retour avec objections, clarifs ou contre-propositions sous **48h**.
2. **Hedi** : une fois le design endpoint locké (auth, cache, deploy env), je scaffold le script feature-builder en m'appuyant sur `methodology/external_data.py`. Tu le revois plutôt que je push directement.
3. **Julien** : reste sur son sandbox. Reçoit URL + token quand l'endpoint est en pre-prod. Pas avant.

Échange Slack ou ce repo R&D Compass pour les follow-ups. Si tu préfères un appel 20min plutôt qu'écrit, ping-moi.

— Hedi
