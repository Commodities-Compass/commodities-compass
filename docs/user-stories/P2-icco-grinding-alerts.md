# Cocoa Grinding Alerts

## Context

Les donnees de broyage (grindings) sont un indicateur fondamental cle du marche cacao. Elles mesurent le tonnage de feves broyees par trimestre, refletant la demande reelle de l'industrie. Ces chiffres impactent directement les prix et doivent etre integres dans l'analyse Compass.

Les grindings sont publies par 3 associations regionales (donnees gratuites, ~2 semaines avant l'ICCO) et agreges par l'ICCO (payant).

## Sources de donnees

### Sources gratuites (prioritaires)

#### 1. ECA — European Cocoa Association

- **Zone** : Europe (~40% des grindings mondiaux, signal le plus fort)
- **Site** : `eurococoa.com/all-about-grind-stats/`
- **Format** : PDF public, URL predictible (`/wp-content/uploads/WEBSITE-REPORT-WESTERN-STATS-Q{x}-{year}-1.pdf`)
- **Participants** : 19 entreprises, donnees compilees par Statser (Pays-Bas)
- **Scrapable** : oui (httpx, pas besoin de Playwright)

**Calendrier 2026 :**

| Trimestre | Date de publication         |
|-----------|-----------------------------|
| Q1 2026   | Jeudi 16 avril 2026         |
| Q2 2026   | Jeudi 16 juillet 2026       |
| Q3 2026   | Jeudi 15 octobre 2026       |
| Q4 2026   | Jeudi 21 janvier 2027       |

#### 2. NCA — National Confectioners Association

- **Zone** : Amerique du Nord
- **Site** : `candyusa.com/cocoa-grinds-report/`
- **Format** : Page web publique, pas de login requis
- **Participants** : ~10 processeurs, donnees publiees pour ICE Futures U.S.
- **Dernier chiffre** : Q4 2025 = 103,117 tonnes metriques (+0.35% YoY)
- **Scrapable** : oui (httpx + BeautifulSoup)

#### 3. CGA — Cocoa Association of Asia

- **Zone** : Asie
- **Site** : `cocoaasia.org`
- **Format** : Site Wix, structure mal definie — a investiguer
- **Statut** : Acces aux donnees non confirme, a creuser manuellement
- **Scrapable** : a determiner

### Source payante (ulterieure)

#### ICCO — International Cocoa Organization

- **Site** : `icco.org/statistics/`
- **Publication** : Quarterly Bulletin of Cocoa Statistics (abonnement annuel)
- **Contenu** : Agregation mondiale (production + grindings + stocks + trade par region/pays)
- **Calendrier** : Bulletins en fevrier, mai, aout, novembre + revisions intermediaires
- **Contact** : `statistics.section@icco.org`
- **Interet** : Donnees mondiales consolidees, historique depuis 1960

## Strategie

### Phase 1 — Calendar reminders + veille manuelle (maintenant)

4 rappels Google Calendar alignes sur les dates ECA (avril, juillet, octobre, janvier) :
- Verifier ECA : `eurococoa.com/all-about-grind-stats/`
- Verifier NCA : `candyusa.com/cocoa-grinds-report/`
- Verifier CGA : `cocoaasia.org` (exploration manuelle)

Zero infra, operationnel en 5 min. Objectif : valider que le signal est utile pour le trading avant d'automatiser.

### Phase 2 — Scrapers ECA + NCA (quand le signal est valide)

Deux Cloud Run Jobs qui detectent les nouvelles publications et envoient une notification.

**Architecture :**

```
Cloud Scheduler (daily, semaines de publication)
  -> Cloud Run Job (grinding-alert-checker)
       -> httpx GET eurococoa.com + candyusa.com
       -> compare avec derniere publication connue (pl_grinding_publication)
       -> si nouveau : notification + insert DB
```

**Details techniques :**

- **Stack** : httpx + BeautifulSoup (pages statiques, pas besoin de Playwright)
- **Detection ECA** : presence d'un nouveau PDF via URL predictible ou hash de la page
- **Detection NCA** : diff du contenu de la page cocoa-grinds-report
- **Storage** : table `pl_grinding_publication` (date, source, quarter, url, volume_tonnes, yoy_pct)
- **Notification** : Slack webhook ou email (SendGrid)
- **Cron** : quotidien du 10 au 25 des mois de publication (avril, juillet, octobre, janvier)
- **Infra** : meme pattern que les scrapers existants (Dockerfile, Cloud Run Job, Cloud Scheduler)

### Phase 3 — Extraction des donnees + dashboard (optionnel)

- Parser les PDFs ECA pour extraire les volumes par pays
- Scraper les chiffres NCA depuis la page
- Stocker dans `pl_grinding_data` (date, source, region, quarter, volume_tonnes, yoy_pct)
- Alimenter le dashboard avec un widget fondamentaux long-terme (grindings trend)
- Integrer dans le prompt du Daily Analysis comme variable macro

### Phase 4 — Abonnement ICCO (si necessaire)

Si les donnees regionales ne suffisent pas (besoin de donnees mondiales consolidees, historiques, ou production/stocks) :
- Souscrire a l'abonnement ICCO
- Ajouter un scraper/parser pour le Quarterly Bulletin PDF
- Enrichir `pl_grinding_data` avec les donnees mondiales

## Decision

Commencer par Phase 1. Europe (ECA) + Amerique du Nord (NCA) couvrent les deux plus gros marches de transformation. Passer en Phase 2 apres validation du signal sur 1-2 trimestres.
