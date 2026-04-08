# Pattern Extractor — Documentation technique

**Branche** : `feat/pattern-extractor`
**Statut** : R&D exploratoire — non merge dans main
**Data** : 672 segments sur GCP prod (`pl_article_segment`)

---

## Qu'est-ce que c'est

Un pipeline d'extraction structuree qui segmente les articles de press review cacao
selon une grille **2 zones x 4 themes**. Chaque article passe dans un LLM (o4-mini)
qui en extrait des segments avec : faits cles, chaines causales, sentiment, entites.

L'objectif est exploratoire : comprendre ce que nos articles couvrent (et ne couvrent
pas), identifier des patterns recurrents, et evaluer la faisabilite d'une exploitation
automatisee (dashboard, alerting, input pour le daily analysis).

## Etat actuel

| Element | Statut | Localisation |
|---|---|---|
| Code (script, modele, migration) | Branche `feat/pattern-extractor` | `backend/scripts/pattern_extractor/` |
| Table `pl_article_segment` | Creee sur GCP prod | Migration `a7b8c9d0e1f2` |
| Data (672 segments) | Sur GCP prod | `pl_article_segment` |
| Strategy doc | Branche | `docs/guides/macro-pattern-extraction-strategy.md` |
| Rapport d'analyse | Branche | `docs/reports/pattern-extraction-analysis-2026-04.md` |
| Pipeline nightly | **Non integre** | Pas de Cloud Run Job |

## Architecture

```
pl_fundamental_article (243 articles, avr 2025 - avr 2026)
    |
    v  poetry run extract-patterns (1 appel o4-mini par article, ~25s)
    |
    v  Validation Pydantic + normalisation aliases + merge doublons
    |
    v  pl_article_segment (672 segments)
         - zone: afrique_ouest | monde
         - theme: production | transformation | chocolat | economie
         - facts, causal_chains (JSON), sentiment, sentiment_score
         - entities (JSON), confidence
         - extraction_version, llm_provider, llm_model
```

## Fichiers

```
backend/scripts/pattern_extractor/
    __init__.py
    config.py          # Taxonomie, prompts, parametres LLM
    output_parser.py   # Pydantic models, aliases, merge doublons
    llm_client.py      # Appel OpenAI o4-mini (fail loud, no retry)
    db_reader.py       # Lecture articles depuis pl_fundamental_article
    db_writer.py       # Ecriture segments + audit aud_llm_call
    main.py            # CLI entry point

backend/alembic/versions/
    a7b8c9d0e1f2_add_pl_article_segment_table.py

docs/guides/
    macro-pattern-extraction-strategy.md   # Approches evaluees (A/B/C)
    pattern-extractor-README.md            # Ce fichier

docs/reports/
    pattern-extraction-analysis-2026-04.md # Rapport avec findings
```

## Utilisation

### Pre-requis

- DB locale running (`pnpm db:up`)
- Sync depuis GCP si besoin (`poetry run python scripts/sync_from_gcp.py`)
- `OPENAI_API_KEY` dans `.env`

### Commandes

```bash
# Dry run sur 5 articles (pas d'ecriture DB)
DATABASE_SYNC_URL="postgresql+psycopg2://postgres:password@localhost:5433/commodities_compass" \
  poetry run extract-patterns --mode batch --dry-run --limit 5

# Traiter les articles non encore extraits
DATABASE_SYNC_URL="postgresql+psycopg2://postgres:password@localhost:5433/commodities_compass" \
  poetry run extract-patterns --mode batch

# Traiter uniquement le dernier article actif
DATABASE_SYNC_URL="postgresql+psycopg2://postgres:password@localhost:5433/commodities_compass" \
  poetry run extract-patterns --mode single

# Options
--limit N              # Max N articles (batch mode)
--rate-limit 1.5       # Secondes entre appels API (defaut: 1.0)
--extraction-version v2 # Tag de version (defaut: v1, permet re-extraction)
--verbose              # Debug logging
```

### Requetes SQL utiles

```sql
-- Distribution zone x theme
SELECT zone, theme, count(*), avg(sentiment_score)::numeric(4,2)
FROM pl_article_segment GROUP BY 1,2 ORDER BY 1, count(*) DESC;

-- Top chaines causales
SELECT elem->>'cause', elem->>'effect', elem->>'direction', count(*)
FROM pl_article_segment, jsonb_array_elements(causal_chains::jsonb) elem
GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 20;

-- Sentiment mensuel par zone
SELECT date_trunc('month', article_date)::date, zone,
       avg(sentiment_score)::numeric(4,2), count(*)
FROM pl_article_segment GROUP BY 1,2 ORDER BY 1;

-- Entites les plus mentionnees
SELECT elem->>'type', elem->>'value', count(*)
FROM pl_article_segment, jsonb_array_elements(entities::jsonb) elem
GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20;
```

## Decisions de design

### Fail loud, no retry

Le LLM client n'a **pas de retry**. Si o4-mini renvoie du contenu vide ou un
JSON invalide, l'article est marque en echec et le pipeline continue. Raison :
un retry masque les anomalies. On prefere voir le taux d'echec reel (75% de
succes sur le premier backfill) et iterer sur le prompt/les aliases.

### Merge des doublons zone x theme

Le LLM produit parfois 2 segments pour la meme combinaison zone/theme
(ex: deux faits "monde/economie" distincts). Plutot que d'ajouter un index
sequentiel au schema, on merge avant ecriture : concatenation des facts,
union des causal chains et entities, moyenne du sentiment score, min de
la confidence.

### Aliases permissifs

Le LLM ne respecte pas toujours les valeurs exactes du schema (ex: `economy`
au lieu de `economie`, `ameriques` au lieu de `monde`). Des dictionnaires
d'aliases normalisent les valeurs avant la validation Pydantic. Ajouter
des aliases est le fix prefere par rapport a complexifier le prompt.

### extraction_version

La contrainte unique inclut `extraction_version`. Cela permet de re-lancer
une extraction avec un prompt ameliore (v2) sans ecraser les resultats
precedents (v1). Les deux coexistent en base.

## Limitations connues

- **Taux de succes 75%** — 61/243 articles en echec. Causes principales :
  empty responses o4-mini (~50%), entity types non normalises (~50%).
  Ameliorable en ajoutant des aliases (`temps`, `phenomene`, `concept`) et
  en augmentant `max_completion_tokens`.
- **Chaines causales fragmentees** — chaque article formule les causalites
  differemment. L'agregation par categorie (DEMANDE, METEO, STOCKS...) est
  plus robuste que le matching exact. Phase 2 (BERTopic/embeddings)
  permettrait du clustering semantique.
- **Sources trader-centric** — les 6 sources du press review agent couvrent
  bien marches + production mais mal transformation locale et chocolat
  en Afrique.

## Next steps possibles

1. **Ameliorer le taux de succes** — ajouter les aliases manquants, retraiter
   les 61 echecs
2. **Phase 2 : BERTopic** — topic modeling non-supervise sur les 672 segments
   pour decouvrir des patterns latents (voir strategy doc)
3. **Integration nightly** — Cloud Run Job apres `cc-press-review-agent`
   pour extraire automatiquement chaque nouvel article
4. **Dashboard widget** — sentiment moyen 30j glissants par zone/theme
5. **Input Daily Analysis** — injecter le contexte structurel dans le prompt
   du bot de trading
