Pourquoi HEDGE malgré 11 MONITOR sur 14 — disséqué
1. La clé cachée : « MONITOR » au niveau spécialiste = abstention, pas vote
Le code vendor R&D soft_gate.py:213-222 traite les votes comme ça :


# OPEN → +1 | HEDGE → -1 | MONITOR → 0
for name, pred in specialist_votes.items():
    vote = self._vote(pred)
    if vote == 0:
        # Abstention: contributes 0 to the score but the specialist's
        # weight is also 0 in the denominator — they sit out today.
        per_w[name] = 0.0
        continue
    n_committed += 1
    ...
Un spécialiste qui sort MONITOR n'est PAS en train de "voter MONITOR" — il dit "je m'abstiens, je n'ai pas assez de signal pour engager une position". Mécaniquement il sort du numérateur ET du dénominateur. Il ne pondère ni le score, ni les poids.

Donc le décompte effectif ce soir était :

3 spécialistes engagés (= votent HEDGE)
11 spécialistes abstenus (= votent MONITOR = sit out)
Et le soft-gate calcule UNIQUEMENT sur les 3 engagés.

2. La formule appliquée aux 3 engagés (2026-05-26)

weighted_sum = Σ (weight_i × vote_i)  pour i ∈ {3 spécialistes HEDGE}
             = poids × (-1) + poids × (-1) + poids × (-1)
             = -6.6387  (= -weights_sum total)

net_score = weighted_sum / weights_sum = -1.0000  (saturé bearish)

commit_threshold = 0.20  (soft-gate config)

| net_score | ≥ threshold → décision basée sur signe
-1.0 ≤ -0.20 → décision = HEDGE
Les 3 spécialistes engagés sont 100% unanimes HEDGE, donc net_score est saturé à -1.0. Aucune ambiguïté côté gate.

3. Cluster mapping confirmé via DB
Les 3 HEDGE engagés de ce soir :

Specialist	Cluster	Window	Famille
xpol_W_TB_macro	Winter	12m	TB + macro
exp_optim_017_bear_4	Spring	12m	optim_017 bearish variant
exp_optim_017_bull_4	Spring	12m	optim_017 bullish variant (mais vote HEDGE !)
→ winter_vote_signed = -1, spring_vote_signed = -2. Cohérent avec l'orchestrator.

Les 11 abstenus (MONITOR) couvrent les deux clusters également : 5 Winter + 6 Spring. Aucun cluster n'a une position OPEN engagée.

4. Pourquoi le wrapper Compass n'a pas vetoé vers MONITOR ?
Le Compass wrapper a 4 détecteurs. Aujourd'hui :

Détecteur	Fired ?	Pourquoi
fired_running_acc	non	running_acc_5d est NULL (cold-start) — pas de signal de sous-perf
fired_dispersion	non	Le critère R&D demande à la fois "faible n_committed" ET "variance des votes engagés élevée". Ici n_committed=3 est bas, mais les 3 engagés sont UNANIMES (variance=0) → pas de dispersion détectée
fired_trend	n/a	détecteur OFF en v1.0.0
fired_three_way	n/a	détecteur OFF en v1.0.0
→ Aucun fire → wrapper_active = false → decision_wrapped = soft_gate_decision = HEDGE.

5. Comparaison avec d'autres dates (10 dernières)
Date	soft-gate	wrapped	wrapper actif ?	n_committed	weights	net_score	anom_z	winter	spring	Lecture
2026-05-26	HEDGE	HEDGE	non	3 ⬇️	6.6	-1.00	1.68	-1	-2	Aujourd'hui : conviction qui s'effrite mais reste tranchée
2026-05-22	HEDGE	HEDGE	non	6	12.7	-1.00	0.39	0	-2	Hier vendredi : double du committed, anomaly basse
2026-05-21	HEDGE	HEDGE	non	5	11.6	-1.00	0.78	0	-1	
2026-05-20	HEDGE	HEDGE	non	7	14.1	-1.00	0.59	0	-1	
2026-05-19	HEDGE	HEDGE	non	7	18.9	-1.00	1.26	-2	-1	fired_dispersion=true MAIS Compass override relâche
2026-05-18	HEDGE	HEDGE	non	8	32.5	-1.00	2.25	-2	-1	Pic de conviction (8 engagés)
2026-05-15	HEDGE	HEDGE	non	7	27.9	-1.00	1.74	-2	-1	
2026-05-14	OPEN	MONITOR	OUI	6	24.3	+1.00	2.66	0	1	Wrapper veto sur OPEN → MONITOR (running_acc fired)
2026-05-13	OPEN	MONITOR	OUI	5	16.2	+1.00	2.55	-2	1	Wrapper veto idem
2026-05-12	MONITOR	MONITOR	non	6	0.0	0.00	2.48	-4	1	Cas rare : weights_sum=0 → vrai MONITOR naturel
Lecture des 3 façons d'arriver à MONITOR (compass wrapper)
Vrai MONITOR par le gate (2026-05-12) : n_committed=6, mais le mix Winter -4 / Spring +1 → forces opposées → weighted_sum=0 → net_score=0 → MONITOR. Le gate dit honnêtement « les engagés se contredisent ».

MONITOR forcé par wrapper (2026-05-13, 2026-05-14) : soft-gate disait OPEN (+1.00) mais fired_running_acc=true → wrapper veto → wrapped=MONITOR. Détecteur de sous-performance.

MONITOR par abstention générale (cas théorique) : si TOUS les 14 votent MONITOR, n_committed=0, weights_sum=0, net_score=0 → MONITOR. Pas observé sur les 10 derniers jours.

Note pour 2026-05-26 : on a n_committed=3. Si UN des 3 avait voté OPEN au lieu de HEDGE, net_score = (poids_open − 2×poids_hedge) / (poids_open + 2×poids_hedge). Avec poids ~2 chacun, ça donnerait (2−4)/(6) = -0.33. Toujours < -0.20 → toujours HEDGE. Il aurait fallu 2 OPEN sur 3 engagés pour basculer dans la zone MONITOR (-0.20 < net_score < +0.20).

6. Le signal mou que tu sentais — confirmation quantitative
Tu as l'intuition correcte : avec 3/14 = 21% d'engagement, c'est le ratio le plus bas des 10 derniers jours (typique 5-8 = 36-57%). Les chiffres confirment :

Métrique	2026-05-26 (today)	Moyenne 10 derniers j
n_committed	3	6.0
weights_sum	6.6	18.4
realized_return_5d	-0.126 (le HEDGE a déjà capté de la baisse)	-0.05
L'interprétation honnête :

La majorité silencieuse des modèles dit « le mouvement baissier des 7 derniers jours s'est déjà manifesté, je ne vois plus de catalyseur clair → je m'abstiens ».
Les 3 modèles qui parlent encore disent unanimement « le risque structurel est toujours là, je couvre ».
Le LLM Explainer a saisi cette nuance : confidence=3/5 + direction=NEUTRE = « la position HEDGE est techniquement valide mais le marché n'a plus d'élan baissier clair ».
7. Faiblesse du design vendor — point à noter
Cette logique « MONITOR = abstention silencieuse » a un effet de bord intéressant :

Quand peu de spécialistes parlent, l'orchestrator amplifie leur voix.

Si demain UN seul spécialiste votait HEDGE et 13 votaient MONITOR, l'orchestrator dirait toujours HEDGE avec un net_score = -1.0. Le wrapper Compass est censé être le garde-fou via fired_dispersion, mais ce détecteur regarde la VARIANCE des votes engagés (et donc rate ce cas où tous les engagés sont d'accord par hasard).

Sur les 7 derniers jours de HEDGE consécutifs, on est passé de 8 à 3 engagés — la conviction s'érode. Si demain on tombe à 1-2 engagés, ça vaudra peut-être le coup d'introduire un détecteur « low_commitment » (e.g. fire si n_committed < 4 AND weights_sum < 8) qui forcerait MONITOR. C'est un candidat de tuning Compass-side, à proposer à la R&D ou à ajouter en override.

TL;DR : Le gate ne fait PAS de vote majoritaire à la 14. Il filtre les abstentions (MONITOR-niveau-spécialiste = « pas de signal »), puis tranche sur les votes engagés uniquement. Aujourd'hui 3 spécialistes engagés, tous d'accord sur HEDGE, donc HEDGE. C'est un signal faible en magnitude (peu de conviction globale) mais tranché en direction. Le LLM Explainer l'a très bien capté : confidence=3/5 + direction=NEUTRE.

Tu veux que je creuse plus (par exemple pourquoi les 11 abstentions précisément, ou impact d'ajouter un détecteur low_commitment dans le wrapper Compass), ou on retourne au prompt NotebookLM ?