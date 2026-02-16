# CFTC Scraper - Railway Deployment Guide

## Déploiement Service Indépendant

Le scraper CFTC utilise le **même Dockerfile** que le backend, mais tourne comme un **service cron séparé** sur Railway.

### 1. Créer le Service Railway

Dans le projet Railway "commodities-compass":

1. **Cliquer** "New Service" → "Empty Service"
2. **Nommer**: `cftc-scraper`
3. **Connecter** au repo GitHub (même repo que backend)

### 2. Configuration Build

Dans les settings du service `cftc-scraper`:

**Build Settings**:
- **Builder**: Dockerfile
- **Dockerfile Path**: `backend/Dockerfile`
- **Build Command**: (laisser vide, géré par Dockerfile)

**Working Directory**:
- **Root Directory**: `backend/`

### 3. Configuration Deploy

**Deploy Settings**:
- **Start Command**:
  ```bash
  poetry run python -m scripts.cftc_scraper.main --sheet=production
  ```

- **Cron Schedule**:
  ```
  0 4 * * 6
  ```
  _(Tous les samedis à 4:00 AM UTC = 5:00 AM CET)_

- **Health Check**: Désactiver (pas applicable pour cron job)

- **Restart Policy**:
  - Type: `On Failure`
  - Max Retries: `2`

### 4. Variables d'Environnement

Ajouter dans Railway dashboard → Service `cftc-scraper` → Variables:

```bash
# Required
GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON=<copier depuis backend service>

# Optional - Slack Alerts
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# Optional - Email Alerts (future)
SENDGRID_API_KEY=
ALERT_EMAIL_FROM=alerts@cocoaians.com
ALERT_EMAIL_TO=julien.marboeuf@cocoaians.com,hedi@cocoaians.com
```

### 5. Déploiement

1. **Push to main** branch → Railway auto-deploy
2. **Vérifier logs** dans Railway dashboard
3. **Tester manuellement** via "Redeploy" button

### 6. Testing

#### Test Dry-Run (depuis local)

```bash
# Via Railway CLI
railway run -s cftc-scraper poetry run python -m scripts.cftc_scraper.main --dry-run --sheet=production
```

#### Test Live (depuis Railway dashboard)

1. Aller dans Service `cftc-scraper`
2. Click "Deploy" → "Redeploy"
3. Vérifier logs en temps réel

### 7. Monitoring

**Logs**:
- Railway Dashboard → `cftc-scraper` → Logs
- Chercher: `"SUCCESS"`, `"CRITICAL"`, `"No new report"`

**Alerts**:
- Slack channel (si configuré)
- Email (si configuré)

**Success Indicators**:
- Logs montrent `"✅ SUCCESS: CFTC scraper completed"`
- Google Sheets column I mise à jour
- Cell K1 contient nouvelle date rapport
- Slack alert "CFTC Scraper - Success" reçu

### 8. Calendrier

**Schedule Automatique** (Railway Cron):
- **Tous les samedis 4:00 AM UTC**
- Équivalent: **Samedi 5:00 AM CET** (hiver) / **6:00 AM CEST** (été)

**Publication CFTC**:
- Vendredi 3:30 PM ET = **21:30 CET**
- Donc samedi matin = ~7h de marge (largement suffisant)

**Gestion des retards** (jours fériés):
- Si pas de nouvelle publication → Info alert, exit 0
- Sheet garde dernière valeur (forward-fill)
- Prochaine exécution (samedi suivant) détectera et mettra à jour

### 9. Workflow

```
Samedi 4:00 AM UTC
    ↓
Railway Cron déclenche service
    ↓
Scraper télécharge rapport CFTC
    ↓
Extrait date rapport (ex: "February 10, 2026")
    ↓
Lit cell K1 (dernière date connue)
    ↓
Compare dates
    ↓
┌─────────────────┬──────────────────────┐
│ Nouvelle date   │ Même date            │
├─────────────────┼──────────────────────┤
│ Parse Long/Short│ Info: pas de nouveau │
│ Calcule NET     │ Exit 0               │
│ Forward-fill I  │ Alert Slack (info)   │
│ Update K1       │                      │
│ Success alert   │                      │
│ Exit 0          │                      │
└─────────────────┴──────────────────────┘
```

### 10. Troubleshooting

**Problème**: Service crash au démarrage
- **Solution**: Vérifier `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` configuré
- **Solution**: Vérifier Working Directory = `backend/`

**Problème**: "No new report" chaque semaine
- **Solution**: Vérifier date dans cell K1
- **Solution**: Tester scraper manuellement pour voir date extraite
- **Solution**: Vérifier site CFTC accessible

**Problème**: Pas de mise à jour dans sheet
- **Solution**: Vérifier permissions service account (write access)
- **Solution**: Vérifier spreadsheet ID correct
- **Solution**: Vérifier sheet name "TECHNICALS" existe

**Problème**: Pas d'alertes Slack
- **Solution**: Vérifier `SLACK_WEBHOOK_URL` configuré
- **Solution**: Tester webhook manuellement
- **Solution**: Vérifier channel Slack existe

### 11. Commandes Utiles

```bash
# Déployer manuellement
railway up -s cftc-scraper

# Voir logs en temps réel
railway logs -s cftc-scraper --follow

# Run one-off command
railway run -s cftc-scraper poetry run python -m scripts.cftc_scraper.main --sheet=production

# Dry run test
railway run -s cftc-scraper poetry run python -m scripts.cftc_scraper.main --dry-run --sheet=staging

# Force update (ignore date check)
railway run -s cftc_scraper poetry run python -m scripts.cftc_scraper.main --sheet=production --force
```

### 12. Rollback

Si problème après déploiement:

1. Railway Dashboard → `cftc-scraper` → Deployments
2. Trouver dernier déploiement stable
3. Click "..." → "Redeploy"

Ou:

```bash
railway rollback -s cftc-scraper
```

## Architecture Finale

```
Railway Project: commodities-compass
│
├── Service: backend (FastAPI app)
│   ├── Dockerfile: backend/Dockerfile
│   ├── Start: uvicorn app.main:app
│   └── Cron: -
│
├── Service: barchart-scraper (Daily scraper)
│   ├── Dockerfile: backend/Dockerfile
│   ├── Start: python -m scripts.barchart_scraper.main --sheet=production
│   └── Cron: 0 19 * * * (19:00 UTC daily)
│
└── Service: cftc-scraper (Weekly scraper) ⭐ NOUVEAU
    ├── Dockerfile: backend/Dockerfile
    ├── Start: python -m scripts.cftc_scraper.main --sheet=production
    └── Cron: 0 4 * * 6 (04:00 UTC Saturday)
```

## Next Steps

1. ✅ Code développé et testé localement
2. ⏳ Créer service Railway `cftc-scraper`
3. ⏳ Configurer variables d'environnement
4. ⏳ Configurer cron schedule
5. ⏳ Déployer et tester dry-run
6. ⏳ Tester live run
7. ⏳ Configurer Slack webhook pour alerts
8. ⏳ Vérifier première exécution automatique (samedi prochain)
