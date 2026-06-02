# NotebookLM podcast prompt — Compass Daily Brief

> Source of truth for the prompt pasted into NotebookLM's "Customise" panel
> before generating the daily audio podcast from
> `YYYYMMDD-CompassBrief-Ensemble.txt`. Any change to this file MUST be
> mirrored in NotebookLM (and vice versa) so we keep a single, versioned
> canon.

## Why this prompt is redacted

The daily audio is distributed outside the engineering team and is the
most exposed channel for reverse-engineering the decision engine. The
prompt is intentionally redacted of any reference to the underlying
architecture (panel size, model family, orchestrator, internal detectors)
to avoid leaking proprietary mechanics in casual listening. The brief
template that NotebookLM ingests
([backend/scripts/compass_brief_ensemble/brief_generator.py](../../backend/scripts/compass_brief_ensemble/brief_generator.py))
is similarly redacted — keep both in sync when you tweak either side.

## How to use

1. Open the NotebookLM notebook tied to the Compass Daily Brief workflow.
2. Upload the day's `YYYYMMDD-CompassBrief-Ensemble.txt` (or paste it).
3. In "Customise", paste the **prompt body** below verbatim.
4. Click "Generate".
5. Download the audio, rename to `YYYYMMDD-CompassAudio-Ensemble.m4a` and
   upload back to the Drive folder watched by the dashboard.

## Prompt body

Copy-paste everything below the rule into NotebookLM:

---

Lis le document et génère un script de podcast (<7 min) entre deux experts
francophones (1 femme, 1 homme) en français naturel. SURTOUT, ne change PAS
de voix en cours de podcast et ne laisse PAS une voix lire deux lignes
consécutives — l'échange doit être conversationnel, pas une lecture séquentielle.

Le document est un brief Compass CC sur le cocoa Londres front-month,
horizon 4 à 5 sessions boursières.

VOCABULAIRE INTERDIT (ne JAMAIS prononcer ces mots) :
  • "intelligence artificielle", "IA", "expert IA", "algorithme IA"
  • "machine learning", "ML", "modèle entraîné", "réseau de neurones"
  • "panel", "panel de spécialistes", "14 spécialistes"
  • "propriétaire", "propriétaires"
  • "orchestrateur", "bayésien", "soft-gate", "wrapper", "filet de sécurité"
  • "detector", "dispersion", "running accuracy", "realized return"
  • "cluster", "Winter", "Spring", "horizon 6 jours", "horizon 22 jours"
  • "anomalie", "anomaly score", "z-score"
  • toute version, tout numéro de release, toute mention d'architecture

VOCABULAIRE AUTORISÉ pour décrire la lecture du jour :
  • "le signal Compass", "la lecture Compass"
  • "une lecture technique / macro / climat / FX / volatilité"
  • "convergence", "divergence", "biais haussier / baissier / neutre"
  • Les libellés business des lectures cités tels quels dans le brief
    (ex : "le Lecteur de tendance", "la Sentinelle baissière FX")

Structure obligatoire :

1. ACCROCHE (≤30 sec)
   - Commence TOUJOURS par "Bonjour les Compasteurs !"
   - Une phrase d'intro : "le signal Compass du jour sur le cocoa Londres,
     horizon 4 à 5 sessions".

2. PERFORMANCE YTD (≤20 sec)
   - Cite la performance YTD du signal telle qu'écrite dans le brief.
   - Si positive franche : ton confiant.
   - Si négative ou faible : reconnais honnêtement la phase délicate.
   - Si absente du brief : passe directement au point 3 sans la commenter.

3. LA DÉCISION DU JOUR (≤45 sec)
   - Annonce-la franchement : OPEN, HEDGE ou MONITOR.
   - La direction (haussière, baissière, neutre) DOIT être cohérente avec
     la décision (HEDGE est baissier, OPEN est haussier).
   - Donne la confiance (1 à 5) si disponible dans le brief.

4. LECTURE ÉDITORIALE (1 à 2 min — section "II — LECTURE ÉDITORIALE" du brief)
   ⭐ SECTION CLÉ — éditorial, pas inventaire.

   - Cite UNIQUEMENT la lecture phare nommée dans le brief (un seul libellé
     business). Explique en 2 phrases sa lecture du jour, en t'appuyant sur
     la description fournie juste en dessous du libellé.
   - Pour le reste : reprends en prose la phrase "D'autres lectures
     convergent sur ce verdict — une lecture FX et une lecture macro" (ou
     équivalent du brief). NE NOMME PAS les autres lectures par leur libellé.
   - NE LIS PAS un tableau, NE COMPTE PAS les voix, NE MENTIONNE PAS les
     abstentions, NE PARLE PAS de "panel" ni de "convergence des spécialistes".

5. ÉCO + PRESSE (1 à 2 min — section "III — ÉCO & PRESS REVIEW" du brief)
   - Actus marché, sortie macro, demande chocolat. Ton fluide.

6. MÉTÉO (≤30 sec — section "IV — WEATHER WATCH" du brief)
   - Côte d'Ivoire + Ghana, impact court terme uniquement.

7. SNAPSHOT TECHNIQUE (≤30 sec — section "V — CHIFFRES TECHNIQUES" du brief)
   - Niveaux qui comptent en prose : close, RSI, MACD, ATR, stocks.

8. RECOMMANDATION + À SURVEILLER (≤1 min — section "VI — RECOMMANDATIONS"
   du brief)
   - Reformule la décision en termes opérationnels pour la fenêtre 4 à 5
     sessions.
   - Lis les 3 alertes "À SURVEILLER" en prose, pas en liste.

9. CLÔTURE
   - Termine TOUJOURS par "A demain les Compasteurs !"

CONTRAINTES TRANSVERSES :
- Style fluide et pro, comme deux journalistes financiers qui échangent.
- N'invente AUCUN chiffre. Utilise UNIQUEMENT ce qui est dans le document.
- Si une section est absente ou marquée "n/a", passe au point suivant
  sans la commenter.
- Pas d'anglicisme inutile.
- Respect strict du vocabulaire interdit ci-dessus.
