# Commodities Compass — Migration vers le domaine personnalisé

**Date :** Avril 2026
**Durée estimée :** 10 minutes
**Interruption de service :** Aucune — l'ancienne URL reste active pendant toute la migration

---

## Contexte

Commodities Compass est actuellement accessible via une URL technique générée par Google Cloud :

```
https://frontend-j6lr5v6fdq-od.a.run.app
```

Nous allons le rendre accessible via notre propre domaine :

```
https://app.com-compass.com     → Dashboard (interface utilisateur)
https://api.com-compass.com     → API (serveur de données)
```

**Pourquoi deux sous-domaines ?**
C'est la pratique standard en SaaS (Stripe, Notion, Linear font la même chose). Le dashboard et l'API sont deux services distincts hébergés sur Google Cloud Run, reliés par un Global HTTPS Load Balancer. Chacun reçoit son propre certificat SSL géré automatiquement par Google, et peut évoluer indépendamment.

**Qu'est-ce qui change pour l'utilisateur final ?**
Rien, à part l'URL dans la barre du navigateur. L'expérience, les identifiants, et les données restent identiques. L'ancienne URL continue de fonctionner en parallèle.

---

## Infrastructure mise en place (côté engineering — déjà fait)

Un **Global HTTPS Load Balancer** a été provisionné via Terraform :

- **IP statique globale (anycast)** : `34.36.87.103`
- **Certificats SSL** : gérés automatiquement par Google (provisionnement après DNS)
- **Routage** : `app.com-compass.com` → service Frontend, `api.com-compass.com` → service Backend
- **Redirection HTTP → HTTPS** : automatique (port 80 → 301 → port 443)

```
                  ┌─────────────────────────┐
                  │   34.36.87.103 (IP LB)  │
                  │   SSL auto (Google)      │
                  └──────────┬──────────────┘
                             │
               ┌─────────────┼─────────────┐
               │                           │
    app.com-compass.com         api.com-compass.com
               │                           │
    ┌──────────▼──────────┐     ┌──────────▼──────────┐
    │   Cloud Run          │     │   Cloud Run          │
    │   Frontend (React)   │     │   Backend (FastAPI)   │
    └──────────────────────┘     └──────────┬──────────┘
                                            │ VPC privé
                                 ┌──────────▼──────────┐
                                 │  Cloud SQL (PG 15)   │
                                 │  IP privée, SSL only │
                                 └──────────────────────┘
```

---

## Action requise : modifier les enregistrements DNS

Les enregistrements DNS actuels (CNAME vers `ghs.googlehosted.com`) doivent être **remplacés** par des enregistrements A pointant vers l'IP du Load Balancer.

### Procédure

1. Se connecter sur **https://domains.squarespace.com**
2. Cliquer sur **com-compass.com**
3. Aller dans **DNS** → **DNS Settings** → **Custom Records**

### Enregistrements à SUPPRIMER

| Type | Host | Value actuel |
|------|------|-------------|
| CNAME | `app` | `ghs.googlehosted.com` |
| CNAME | `api` | `ghs.googlehosted.com` |

> Cliquer sur l'icône poubelle à droite de chaque enregistrement pour le supprimer.

### Enregistrements à AJOUTER

| Type | Host | Value |
|------|------|-------|
| **A** | `app` | `34.36.87.103` |
| **A** | `api` | `34.36.87.103` |

> **Note technique :** Un enregistrement A (Address) lie un nom de domaine directement à une adresse IP. Contrairement au CNAME qui est un alias, le A pointe vers notre Load Balancer Google Cloud, qui se charge ensuite de router le trafic vers le bon service et de gérer le certificat SSL automatiquement.

### Enregistrement TXT — à conserver

L'enregistrement TXT de vérification Google peut rester en place — il ne pose aucun problème :

| Type | Host | Value |
|------|------|-------|
| TXT | `@` | `google-site-verification=bcdAD4R1ddLJum-d1AC560EB9aE3vvZKYll_` |

### Résumé des actions DNS

| # | Action | Type | Host | Value |
|---|--------|------|------|-------|
| 1 | Supprimer | CNAME | `app` | `ghs.googlehosted.com` |
| 2 | Supprimer | CNAME | `api` | `ghs.googlehosted.com` |
| 3 | Ajouter | A | `app` | `34.36.87.103` |
| 4 | Ajouter | A | `api` | `34.36.87.103` |

---

## Après les modifications DNS (côté engineering)

Une fois les enregistrements A en place, l'équipe technique prend le relais :

1. **Propagation DNS** — vérification que les A records pointent vers le LB (2-5 min)
2. **Provisionnement SSL** — Google génère automatiquement les certificats HTTPS (15-60 min)
3. **Mise à jour Auth0** — redirection des callbacks d'authentification vers les nouvelles URLs
4. **Mise à jour CORS** — autorisation du nouveau domaine dans la politique de sécurité du backend
5. **Redéploiement** — build et déploiement avec la nouvelle configuration

### Ce qui ne change pas

- Les données en base (PostgreSQL sur Cloud SQL) restent intactes
- Les 8 jobs automatisés (scrapers, agents, compute) ne sont pas impactés
- Les identifiants Auth0 restent les mêmes
- L'ancienne URL `*.run.app` continue de fonctionner en parallèle

---

## Validation (ensemble)

Une fois le déploiement terminé, nous vérifions :

- [ ] `https://app.com-compass.com` charge le dashboard
- [ ] Le cadenas SSL est vert (certificat valide)
- [ ] La connexion Auth0 fonctionne (login → redirect → dashboard)
- [ ] Les 7 widgets du dashboard affichent des données
- [ ] Le lecteur audio fonctionne
- [ ] `https://api.com-compass.com/health` retourne `{"status": "healthy"}`
- [ ] HTTP redirige vers HTTPS (`http://app.com-compass.com` → `https://...`)

---

## FAQ

**Le site actuel sur com-compass.com sera-t-il impacté ?**
Non. Nous modifions uniquement les sous-domaines (`app.` et `api.`). Le domaine racine `com-compass.com` et son site Squarespace ne sont pas touchés.

**Combien de temps prend la migration ?**
La modification DNS prend 5 minutes. La propagation et le provisionnement SSL prennent 15-60 minutes. Le reste est géré par l'équipe technique.

**Y aura-t-il une coupure de service ?**
Non. L'ancienne URL reste fonctionnelle pendant toute la migration et après.

**Pourquoi un Load Balancer et pas un simple DNS ?**
Notre hébergement (Google Cloud Run, région Paris) ne supporte pas le mapping de domaine direct. Le Load Balancer est la solution standard de production — il gère le SSL, le routage, et ouvre la porte à des fonctionnalités futures (protection DDoS, cache CDN, WAF).
