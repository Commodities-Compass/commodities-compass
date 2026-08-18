# NotebookLM podcast prompt — Compass Daily Brief (regime track, FR)

> Source of truth for the prompt pasted into NotebookLM's "Customise" panel
> before generating the daily **French** audio podcast from
> `YYYYMMDD-CompassBrief-Regime.txt`. Any change here MUST be mirrored in
> NotebookLM (and vice versa) so we keep a single, versioned canon.
>
> Regime+judge track. The ensemble counterpart
> ([notebooklm-podcast-prompt.md](notebooklm-podcast-prompt.md)) stays in place
> until that track is retired, then this file replaces it.

## What changed vs the ensemble prompt

Only three things, because only one section of the brief changed:

1. **Horizon** — the regime call decides for the **next session**, not a 4-to-5
   session window. Every mention of the horizon moves accordingly. This is the
   change most likely to be missed: an audio that promises a week-long view on a
   next-day signal misrepresents the product.
2. **Point 4 (éditorial)** — the ensemble brief named a headline read among
   several converging reads. The regime brief names the **market regime** and how
   the **macro arbitration** landed. No panel, no convergence, no counting.
3. **Point 3 (rationale)** — the confidence sentence is no longer a list of
   pillars with SUPPORT/NUANCE roles. It is a single sentence naming what would
   invalidate the read.

Everything else — hook, YTD, eco & press, weather, technical snapshot,
recommendations, close — is unchanged, because the brief's other sections are
unchanged: they describe the market, not the algorithm.

## Why this prompt is redacted

The daily audio is distributed outside the engineering team and is the most
exposed channel for reverse-engineering the decision engine. The prompt is
intentionally redacted of any reference to the underlying architecture (regime
detection, specialists, the macro overlay's mechanics) to avoid leaking
proprietary mechanics in casual listening. The brief template that NotebookLM
ingests ([regime_brief/brief_generator.py](../../backend/scripts/regime_brief/brief_generator.py))
is similarly redacted, and refuses to render if a field leaks — keep both in
sync when you tweak either side.

## How to use

1. Open the NotebookLM notebook tied to the Compass Daily Brief workflow.
2. Upload the day's `YYYYMMDD-CompassBrief-Regime.txt` (or paste it).
3. In "Customise", paste the **prompt body** below verbatim.
4. Click "Generate".
5. Download the audio, rename to `YYYYMMDD-CompassAudio-Regime.m4a` and upload
   back to the Drive folder watched by the dashboard.

## Prompt body

Copy-paste everything below the rule into NotebookLM:

---

Lis le document et génère un script de podcast (<5 min) entre deux experts
francophones (1 femme, 1 homme) en français naturel. SURTOUT, ne change PAS
de voix en cours de podcast : l'échange doit être conversationnel, pas une
lecture séquentielle.

Le document est un brief Compass sur le CACAO Londres, horizon la prochaine
séance.

VOCABULAIRE INTERDIT (ne JAMAIS prononcer ces mots) :
  • "intelligence artificielle", "IA", "expert IA", "algorithme IA"
  • tout ce qui touche à la mécanique interne : "régime détecté par le
    système", "spécialiste", "modèle", "probabilité", "score", "détecteur"
  • ne compte JAMAIS des voix, des lectures ou des indicateurs

Structure obligatoire :

1. ACCROCHE (≤30 sec)
   - Commence TOUJOURS par "Bonjour les COMPASTEURS !"
   - Une phrase d'intro : "le signal Compass du jour sur le CACAO Londres,
     horizon la prochaine séance".

2. PERFORMANCE YTD (≤20 sec)
   - Cite la performance YTD du signal telle qu'écrite dans le brief.
   - Si positive franche : ton confiant.
   - Si négative ou faible : reconnais honnêtement la phase délicate.
   - Si absente du brief : passe directement au point 3 sans la commenter.

3. LA DÉCISION DU JOUR (≤60 sec)
   - Annonce-la franchement : OPEN, HEDGE ou MONITOR.
   - La direction (haussière, baissière, neutre) DOIT être cohérente avec
     la décision (HEDGE est baissier, OPEN est haussier).
   - Donne la confiance (1 à 5) telle qu'elle apparaît dans la Section I.
   - **Lis et reformule la phrase qui suit le score** dans la ligne
     "Confiance : X/5 — [phrase]". Cette phrase dit ce qui pourrait faire
     mentir la lecture du jour. Reformule-la en une phrase fluide, du type
     "la conviction reste mesurée : un retour à la normale côté logistique
     remettrait cette lecture en cause" (à adapter aux mots exacts du brief).
   - Si aucune confiance n'est présente : passe au point 4 sans inventer.

4. LECTURE ÉDITORIALE (1 à 2 min — section "II — LECTURE ÉDITORIALE" du brief)
   ⭐ SECTION CLÉ — éditorial, pas inventaire.

   - Le brief nomme d'abord le RÉGIME DE MARCHÉ en langage courant (par
     exemple "tendance haussière établie", "marché sans direction claire",
     "volatilité élevée"). Explique en 2 phrases ce que ce régime implique
     concrètement pour un acheteur physique.
   - Le brief dit ensuite comment la LECTURE MACRO s'est positionnée face à
     la position technique : elle la confirme, elle s'y oppose, ou elle ne
     tranche pas. Reprends cette phrase en prose et explique l'arbitrage —
     c'est le cœur éditorial du jour.
   - Parle de "la lecture technique" et de "la lecture macro" comme de deux
     angles d'analyse. NE MENTIONNE PAS de spécialiste, de modèle, de
     probabilité, ni aucun mécanisme de décision.

5. ÉCO + PRESSE (1 à 2 min — section "III — ÉCO & REVUE DE PRESSE" du brief)
   - Actus marché, sortie macro, demande chocolat. Ton fluide.

6. MÉTÉO (≤1 min — section "IV — WEATHER WATCH" du brief)
   - Côte d'Ivoire + Ghana, impact court terme et trajectoire de campagne.

7. SNAPSHOT TECHNIQUE (≤30 sec — section "V — PHOTO TECHNIQUE" du brief)
   - Niveaux qui comptent en prose : clôture, volume, positions ouvertes,
     stocks (en tonnes).

8. RECOMMANDATION + À SURVEILLER (≤1 min — section "VI — RECOMMANDATIONS
   OPÉRATIONNELLES" du brief)
   - Reformule la décision en termes opérationnels pour la prochaine séance.
   - Lis les alertes "À SURVEILLER" en prose, pas en liste.

9. CLÔTURE
   - Termine TOUJOURS par "A demain les COMPASTEURS !"

CONTRAINTES TRANSVERSES :
- Style fluide et pro, comme deux journalistes financiers qui échangent.
- N'invente AUCUN chiffre. Utilise UNIQUEMENT ce qui est dans le document.
- Si une section est absente ou marquée "n/a", passe au point suivant
  sans la commenter.
- SURTOUT : ne change PAS de voix en cours de podcast ; l'échange reste
  conversationnel entre une femme et un homme, en français naturel.
