# Multi-Account « N sièges » — Runbook (version opérationnelle honnête)

> Comment servir « N utilisateurs par abonnement » **aujourd'hui**, sans socle multi-tenant. C'est un placeholder assumé : N logins Auth0 → **une seule vue globale partagée**. Aucune isolation par client, aucun quota applicatif. La gestion d'équipe complète (rôles, quotas, isolation par tenant) reste **co-construction / backlog** — voir §5.
>
> Origine : US [P1-align-offre-v11-colonne-livree.md](../user-stories/P1-align-offre-v11-colonne-livree.md) §T5.

## 1. Ce que « N sièges » veut dire ici (et ne veut PAS dire)

| ✅ Livré | ❌ Pas livré (co-construct) |
|---|---|
| Provisionner N logins Auth0 par client | Isolation des données par client / par siège |
| Révoquer un login à tout moment | Quotas ou rate-limit **par utilisateur** |
| Chaque login accède au dashboard | Rôles / permissions différenciés (admin vs viewer) |
| | Vue « équipe » (qui est dans mon org, activité) |

**En clair : tous les logins voient exactement le même dashboard global.** Il n'y a pas de notion de « données du client X ». Un siège = un identifiant Auth0 valide, rien de plus.

## 2. Le modèle d'auth actuel (vérifié dans le code)

- Auth0 SPA + JWT RS256, JWKS validé côté backend (`app/core/auth.py`, cache JWKS 6 h).
- Claims extraits par `get_current_user` : `sub`, `email`, `name`, `permissions` (`auth.py:131-136`).
- **`permissions` est extrait mais JAMAIS enforcé.** Aucun `require_permission` / check de scope nulle part dans le backend. `sub` ne sert qu'au tag Sentry (`auth.py:138`).
- **Aucun endpoint ne filtre les données par `sub`/`email`.** Les 19 endpoints protégés vérifient seulement que le token est valide, puis renvoient les mêmes `pl_*` globaux à tout le monde.

> Conséquence directe : **tout compte Auth0 valide = accès complet et identique**. Le contrôle d'accès réel se joue donc uniquement à la porte Auth0 (qui a le droit de se connecter), pas dans l'application.

## 3. Provisionner N accès pour un client

> ⚠️ Les détails exacts (nom de la connection, domaine tenant, éventuel flow d'invitation) dépendent de la config Auth0 de prod — **à confirmer avant première exécution** (marqués `‹CONFIRM›`).

1. **Auth0 Dashboard** → tenant ‹CONFIRM: domaine, ex. `com-compass.eu.auth0.com`› → **User Management → Users → Create User**.
2. Connection : ‹CONFIRM: la Database Connection utilisée par l'app SPA (ex. `Username-Password-Authentication`)›.
3. Renseigner `email` (login du siège) + mot de passe initial (ou déclencher l'email de « change password » Auth0).
4. Répéter pour chaque siège du contrat (N users).
5. **Convention de traçabilité** (recommandée, purement organisationnelle — pas d'effet applicatif) : préfixer/étiqueter les users du même client via le champ `app_metadata`, ex. `{ "client": "<nom-client>", "seats_contract": "<ref-contrat>" }`. Ça permet de retrouver/révoquer tous les sièges d'un client plus tard, **sans** que le backend ne le lise (il ne le lit pas).
6. Vérifier que l'URL de logout du front (`https://app.com-compass.com/login`) est bien dans **Allowed Logout URLs** du client Auth0 (déjà le cas en prod ; sinon Auth0 affiche sa page d'erreur au lieu de rediriger — cf. `CLAUDE.md` § Authentication Flow).

Aucune action côté base de données, backend ou déploiement. Le user peut se connecter immédiatement.

## 4. Révoquer un accès

1. **Auth0 Dashboard → Users** → rechercher l'email (ou filtrer par `app_metadata.client`).
2. Soit **Block** (réversible — l'utilisateur ne peut plus se connecter, compte conservé), soit **Delete** (définitif).
3. Effet : les nouveaux logins échouent. **Un token déjà émis reste valide jusqu'à expiration** (le backend valide la signature/expiry, il ne consulte pas Auth0 à chaque requête). Pour une coupure immédiate d'un token en cours, il faut attendre son `exp` (ou faire tourner les clés — disproportionné ici). À garder en tête pour une révocation « urgente ».

## 5. Limites — à écrire noir sur blanc (et à transmettre au commercial)

- **Vue partagée, pas d'isolation.** Chaque siège voit la même donnée globale. Il n'existe pas de « périmètre client ». Ne pas vendre « vos données », « votre espace », ou toute forme de cloisonnement.
- **Pas de quota par siège.** Le rate-limit existant est global/endpoint (slowapi), pas par utilisateur. N sièges ne consomment pas de quota individuel.
- **Pas de rôles.** Aucun admin/viewer/editor. Tous les sièges sont équivalents.
- **Révocation = latence jusqu'à expiration du token** pour les sessions déjà ouvertes (§4).
- **Le compte de sièges n'est pas enforcé techniquement.** Rien n'empêche de créer plus de logins que le contrat n'en prévoit — c'est un engagement commercial/manuel, pas une limite système.

## 6. Ce qui reste co-construction / backlog (le vrai multi-tenant)

Le socle SaaS complet — modèle `tenant`/`account`/`seat`, mapping `user ↔ account`, scoping des requêtes par tenant, rôles & quotas applicatifs, isolation des données — est un chantier séparé, **hors de cette itération**. Direction cible : North Star `tenant.account.locale` (déjà citée comme aspiration dans `app/core/i18n.py`). Tant qu'il n'est pas construit, la procédure ci-dessus est le seul moyen honnête de servir « N sièges ».

## 7. Message type pour la Direction Commerciale

> « N sièges » = N identifiants Auth0 par client, provisionnables/révocables à la demande. **Tous accèdent à la même intelligence de marché** (vue globale Compass). Ce n'est pas un espace client cloisonné : pas d'isolation de données, pas de rôles, pas de quota par utilisateur. Le cloisonnement par client, les rôles et les quotas sont au programme de co-construction (Programme Fondateur), pas dans l'offre livrée dès l'abonnement.
