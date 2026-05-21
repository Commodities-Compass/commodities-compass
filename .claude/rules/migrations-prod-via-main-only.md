# Migrations DB Prod via Main UNIQUEMENT

> Origin: 2026-05-21 — Cloud Run prod en crashloop pendant ~1h. La DB GCP avait été avancée à la revision `m7h8i9j0k1l2` par un `alembic upgrade head` exécuté depuis la branche `feat/c5-ensemble-vendor-and-schema` via le bastion IAP, alors que `origin/main` ne contenait que jusqu'à `h2c3d4e5f6g7`. L'instance Cloud Run existante continuait de tourner sans problème (alembic n'est exécuté qu'au cold start). Quand l'autoscaling a spawn un nouvel instance (24h plus tard), `alembic upgrade head` au démarrage a échoué avec `Can't locate revision identified by 'm7h8i9j0k1l2'`, container exit(255), crashloop.

## Le principe

**Toute migration Alembic appliquée sur la DB prod (GCP Cloud SQL) DOIT provenir d'un commit déjà mergé sur `main`.** La règle de progression est inversable :

```
fichier sur main  ⇔  revision dans pl_alembic_version de la DB prod
```

Si la DB est en avance sur le code main, le prochain cold-start Cloud Run plante. Si le code est en avance sur la DB, `alembic upgrade head` posera les nouvelles migrations au boot — c'est OK, c'est précisément le rôle de `start.sh`.

## Règles

### 1. JAMAIS `alembic upgrade head` sur la DB prod depuis une feature branch

Si une feature branch a besoin d'une nouvelle table / colonne / VIEW sur la DB prod (pour un backfill, un test, un bootstrap de modèle, etc.), la séquence obligatoire est :

1. Écrire la migration sur la feature branch et la tester en local.
2. Ouvrir une PR vers main avec **uniquement le fichier de migration** (pas le code applicatif qui la consomme).
3. Merger la PR sur main → CI/CD redéploie automatiquement → `start.sh` du nouveau container applique la migration sur la DB prod via `alembic upgrade head`.
4. Continuer le développement sur la feature branch en sachant que la DB et main sont alignés.

**Interdit** : ouvrir le tunnel IAP, se connecter à la DB prod, et tourner `poetry run alembic upgrade head` depuis une branche non-mergée. Même pour "juste tester", même "juste pour débloquer le backfill".

### 2. Migrations sur DB **locale** : OK depuis n'importe quelle branche

Aucune restriction sur `alembic upgrade head` contre la DB locale (`localhost:5433`) — c'est le workflow normal de dev. Cette rule concerne uniquement la DB prod.

### 3. Bastion = lecture seule par défaut, écriture uniquement via Alembic-de-main

Le bastion IAP (`gcloud compute ssh cc-bastion --tunnel-through-iap`) est documenté comme outil d'investigation read-only (cf `CLAUDE.md` § Browser Rules). Toute écriture (INSERT/UPDATE/DELETE, CREATE/DROP/ALTER) sur la DB prod doit passer par :

- soit une migration Alembic mergée sur main + redéploiement (cas normal)
- soit un `op.execute(...)` dans une migration future (changements idempotents)
- soit un ordre direct du user, en pleine conscience qu'il sort du process

Pas de "petit fix vite fait via psql".

### 4. Si on doit absolument appliquer une migration en prod en urgence (pas via merge)

Cas hypothétique : main est gelé pour une release frontend, mais le pipeline data a besoin d'une migration urgente.

Procédure :
1. Cherry-pick le fichier de migration sur une branche `hotfix/<description>` directement depuis `origin/main`.
2. Push + PR vers main + merge — c'est toujours le seul chemin légitime.
3. Si vraiment impossible (CI bloqué, déploiement HS), demander l'autorisation explicite du user **avant** de toucher à la DB prod via bastion. Tracer dans `docs/runbooks/`.

## Garde-fous techniques (à mettre en place — P1 suite à l'incident)

- **Hook Alembic** : refuser `alembic upgrade head` si la cible n'est pas localhost et que la branche actuelle n'est pas `main`. Implémentation dans `backend/alembic/env.py` (lire `os.environ` + git branch via subprocess, fail-loud si désaligné).
- **Bastion access log** : ajouter à `docs/runbooks/db-prod-access.md` un rappel obligatoire de ne pas tourner alembic via le tunnel.
- **CI smoke** : étape "alembic verify chain" dans `.github/workflows/ci.yml` qui run `alembic history` et fail si la chain est brisée.

## Récap : quand checker cette rule

Avant **toute** action touchant à `alembic upgrade head` :

1. Quelle DB ? localhost OK, GCP STOP.
2. Sur quelle branche je suis ? main OK, autre STOP.
3. Le code main contient-il déjà la migration que je veux appliquer ? Si non, **merger d'abord**.

Si les trois réponses ne sont pas "OK", on s'arrête et on demande au user.
