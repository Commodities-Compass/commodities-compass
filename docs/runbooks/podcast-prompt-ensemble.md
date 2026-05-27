# Podcast NotebookLM — prompt ensemble v2 (2026-05-27)

> Prompt à coller dans NotebookLM pour générer le podcast quotidien Compass à partir du brief ensemble. Mis à jour le **2026-05-27** pour : (1) éliminer le vocabulaire « experts IA » au profit de « spécialistes propriétaires entraînés en machine learning », (2) tirer parti des profils détaillés rendus par le nouveau brief (Section II), (3) imposer un ton cohérent entre la décision et la direction.
>
> Source du document à donner à NotebookLM : le fichier `YYYYMMDD-CompassBrief-Ensemble.txt` uploadé sur le Drive partagé par `cc-compass-brief-ensemble`.

---

## Le prompt complet

```
Lis le document et génère un script de podcast (<7 min) entre deux experts
francophones (1 femme, 1 homme) en français naturel. SURTOUT, ne change PAS
de voix en cours de podcast et ne laisse PAS une voix lire deux lignes
consécutives — l'échange doit être conversationnel, pas une lecture séquentielle.

Le document est un brief ensemble (horizon 4-5 trading days), pas un brief
« pour demain ». Il s'agit du signal Compass CC sur le contrat front-month
cocoa Londres.

ÉLÉMENT CRITIQUE — Le vocabulaire à utiliser pour parler de notre système :

  • Notre signal vient de 14 spécialistes propriétaires entraînés en
    machine learning sur dix ans de données cocoa Londres. NE LES APPELLE
    JAMAIS « experts IA », « intelligences artificielles » ou
    « algorithmes IA ». Ce sont des spécialistes propriétaires, point.

  • Chaque spécialiste a une méthode propre — lecture technique pure,
    structure FX, conditions climatiques ENSO, dynamique de volatilité,
    sentiment macro extrait de la presse. Le brief (Section II) donne
    le profil business de chacun (« Lecteur de tendance — référence »,
    « Sentinelle baissière FX », « Stratège macro global », etc.).

  • Le panel se répartit en deux clusters thématiques : le cluster Winter
    (six spécialistes, tendance technique + couverture FX) et le cluster
    Spring (huit spécialistes, conditions macro + climat).

  • L'orchestrateur bayésien Compass agrège uniquement les voix engagées
    (OPEN ou HEDGE), pas les abstentions (MONITOR au niveau spécialiste).

Structure obligatoire du podcast :

1. ACCROCHE ET RAPPEL DU PANEL (≤45 sec)
   - Commence toujours par « Bonjour les Compasteurs! »
   - Présente brièvement Compass : un panel de 14 spécialistes propriétaires
     qui votent chaque jour OPEN, HEDGE ou MONITOR sur un horizon de 4-5
     jours boursiers.
   - Annonce le nombre de voix engagées du jour ("X spécialistes sur 14
     se sont exprimés aujourd'hui, les Y autres ont préféré s'abstenir").

2. PERFORMANCE RÉCENTE (≤45 sec — section III du brief)
   - Lis le running accuracy 5j et le realized return 5d.
   - Si running_acc_5d ≥ 0.70 et realized_return_5d > 0 : félicite-toi
     honnêtement, le signal a eu raison sur la semaine.
   - Si running_acc_5d < 0.50 OU realized_return_5d < 0 : reconnais la
     baisse de performance et explique les raisons probables (anomaly_z
     élevé, désaccord entre clusters, régime transition).
   - Si running_acc_5d est marqué « n/a » : précise que les modèles
     viennent d'être ré-entraînés, donc la métrique est en stabilisation.
   - Mentionne la persistence : « ce biais est en place depuis N jour(s) ».

3. LA DÉCISION DU JOUR (≤45 sec — section I)
   - Annonce-la franchement : OPEN, HEDGE ou MONITOR.
   - IMPORTANT : la direction (haussière, baissière, neutre) DOIT être
     cohérente avec la décision. HEDGE est baissier, OPEN est haussier.
     Si le brief affichait une incohérence (par exemple HEDGE / NEUTRE),
     fais confiance à la décision, pas à la direction.
   - Donne la confiance LLM (1 à 5) si disponible.

4. LES SPÉCIALISTES QUI ONT PARLÉ (1-2 min — section II)
   ⭐ C'EST LA SECTION CLÉ — le différenciateur de notre format.

   Pour chaque spécialiste engagé listé dans la section II du brief :
   - Donne son libellé business (jamais l'ID technique de type
     « exp_optim_002 »). Le brief liste les profils sous la forme
     « [HEDGE] Sentinelle baissière FX · cluster Spring (S1, horizon 6j) ».
     Utilise le libellé « Sentinelle baissière FX » — pas le code S1.
   - Lis sa description courte (1-2 phrases que le brief donne juste
     en-dessous).
   - Explique comment sa voix pèse aujourd'hui (par exemple : « la
     Sentinelle baissière FX appelle à couvrir, ce qui est cohérent
     avec sa calibration prudente »).

   Pour les abstentions :
   - Mentionne brièvement les spécialistes silencieux (cite 2-3 noms
     business max, pas tous) pour donner un sentiment de complétude :
     « Onze autres spécialistes — comme le Lecteur de tendance de
     référence ou le Stratège macro global — ont préféré s'abstenir,
     jugeant le signal trop faible pour s'engager. »

5. CONTEXTE MACRO (≤45 sec — section III)
   - Macro direction et surprise macro (garde l'unité σ).
   - Anomaly score : ne le cite QUE si z > 1.5 (« régime à surveiller »).
   - Wrapper actif : ne mentionne QUE si oui (« le filet de sécurité
     Compass a corrigé la décision soft-gate »).

6. ÉCO + PRESSE (1-2 min — section IV)
   - Contextualise les actus marché, la sortie macro, les conditions
     climatiques en Côte d'Ivoire et Ghana, la demande chocolat.
   - Ton fluide, pas une énumération de bullets.

7. MÉTÉO (30 sec — section V)
   - Côte d'Ivoire + Ghana, impact court terme uniquement.

8. SNAPSHOT TECHNIQUE (30 sec — section VI)
   - Les valeurs clés en prose : close, volume, RSI, MACD, ATR.
   - Pas de lecture brute du tableau, juste les niveaux qui comptent.

9. RECOMMANDATION DU JOUR + À SURVEILLER (≤1 min — section VII)
   - Reformule la décision en termes opérationnels pour la fenêtre
     4-5 jours.
   - Lis les 3 alertes « À SURVEILLER » du brief en prose, pas en liste.

10. CLÔTURE
   - Termine TOUJOURS par « A demain les Compasteurs! »

CONTRAINTES TRANSVERSES :

- Style fluide et pro, comme deux journalistes financiers qui échangent
  sur le marché — pas une lecture de bullets points.
- N'invente AUCUN chiffre. Utilise UNIQUEMENT ce qui est dans le document.
- Ne lis JAMAIS le tableau des 14 spécialistes ni la liste des 25
  diagnostics. Sélectionne ce qui est pertinent.
- Si une section est absente ou marquée « n/a », passe au point suivant
  sans la commenter.
- Pas d'anglicisme inutile (« commit » → « engagement », « score » → « score »
  est OK).
- Évite les expressions « expert IA », « intelligence artificielle »,
  « algorithme IA » — toujours « spécialiste propriétaire » ou
  « modèle entraîné en machine learning ».

Commence toujours par 'Bonjour les Compasteurs!' et finis toujours par
'A demain les Compasteurs!'
```

---

## Différences avec le prompt v1

| Élément | v1 (legacy) | v2 (ce prompt) |
|---|---|---|
| Vocabulaire spécialistes | « experts IA », « specialists ML » | « spécialistes propriétaires entraînés en machine learning » |
| Section dédiée aux spécialistes | implicite, lecture du tableau | Section 4 explicite, profils business individualisés |
| Cohérence décision/direction | non contrôlée | rappel explicite : HEDGE = baissier, OPEN = haussier |
| Abstentions | passées sous silence | mentionnées en 1 phrase pour donner du sens à la sélection |
| Codes R&D (W1, S1, X2...) | absent | toléré mais pas obligatoire, le libellé business est primordial |

## Vocabulaire des spécialistes — référence rapide pour QA

Le brief expose les profils par libellé business. Voici la carte tech ID → libellé pour vérifier qu'un podcast n'utilise pas un ID technique :

| Tech ID | Libellé business | Cluster |
|---|---|---|
| exp_optim_002 | Lecteur de tendance — référence | Winter |
| exp_optim_005 | Lecteur de tendance volatilité-conditionnel | Winter |
| exp_optim_006 | Spécialiste cycle long — 3 semaines | Winter |
| exp_optim_011 | Stratège macro global | Winter |
| xpol_W_TB_garch | Lecteur de tendance + ajustement volatilité | Winter |
| xpol_W_TB_macro | Lecteur de tendance contextualisé macro | Winter |
| exp_optim_017_bear_4 | Sentinelle baissière FX | Spring |
| exp_optim_017_bear_8 | Sentinelle baissière macro + FX | Spring |
| exp_optim_017_bull_4 | Stratège haussier FX | Spring |
| exp_optim_017_bull_5 | Stratège haussier baseline (approche logistique) | Spring |
| exp_optim_017_bull_7 | Stratège haussier FX renforcé | Spring |
| exp_optim_017_bull_8 | Stratège haussier multi-facteur | Spring |
| xpol_S_bull_garch_fx | Stratège haussier volatilité-conditionnel FX | Spring |
| xpol_S_bear_garch_macro | Sentinelle baissière complète | Spring |

Source canonique : [backend/scripts/compass_brief_ensemble/specialist_catalog.py](../../backend/scripts/compass_brief_ensemble/specialist_catalog.py).

## Si un spécialiste est renommé / ajouté côté R&D

1. Mettre à jour `specialist_catalog.py` (ajouter / renommer une `SpecialistProfile`).
2. Mettre à jour la table ci-dessus dans ce runbook.
3. Re-uploader le prompt mis à jour dans NotebookLM.
