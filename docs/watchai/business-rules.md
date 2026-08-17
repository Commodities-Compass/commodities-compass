# WatchAI Business Rules — the semantics that must not drift

> Companion to [watchai-integration.md](watchai-integration.md) and [port-inventory.md](port-inventory.md).
>
> **Reference source (2026-08-17)**: `plakoplister/watch-ai` @ **`11336ef`**, branch **`refonte-da-v2`** — the v2 `api/app/` (FastAPI + DuckDB), which is typed, tested and current. Line references to `Webapp/webapp_tax.py` @ `36d8f89` are kept **only where v2 has no equivalent**, and are marked *(v1)*.
>
> ⚠️ `refonte-da-v2` is an **active branch**. This spec is pinned to `11336ef`. Never re-anchor on `HEAD` implicitly — re-sync deliberately and re-run the reconciliation.
>
> §4, §5 and §7 were rewritten on 2026-08-17: the v1 material balance they described was **fixed by Julien on 2026-07-17** (double-counting bug). Do not port the v1 formulas.

---

## 0. Canonical schema

`api/app/saison.py` exposes three DuckDB views over the parquet with normalized names — this is the target shape for our ingestion transform, adopt it verbatim:

| View | Columns |
|---|---|
| `tax` | `declaration · date · port · exportateur · destinataire · destination · declarant · postar · produit · annee · mois · saison · pds_net · poids_tonnes · valcaf · droits_taxes · caf_par_tonne · tax_par_tonne` |
| `achats` | `exportateur · saison · date · mois_nom · annee_mois · pds_net · volume_tonnes` |
| `broyage` | `date · annee · mois · saison · tons_broyes · tons_mat · tons_ytd · index_*` |

It ends the space/underscore double-nomenclature of the Streamlit app (`EXPORTATEUR SIMPLE` vs `EXPORTATEUR_SIMPLE`). Our reduced projection keeps `date, port, exportateur, destination, postar, produit, saison, pds_net, valcaf, droits_taxes` and drops the rest ([watchai-integration.md](watchai-integration.md) decision #7).

---

## 1. Units — the first trap

| Field | Source | Unit | Conversion |
|---|---|---|---|
| `PDS_NET` | `Db_Master_Tax` (int64) | **kg** | `poids_tonnes = PDS_NET / 1000` |
| `POIDS_NET_KG` | `Db_Master_Achats` | **kg** | `volume_tonnes = POIDS_NET_KG / 1000` |
| `TONS_BROYES` | `Db_Master_Broyage` | **tonnes already** | ⚠️ **no division** |
| `VALCAF` / `DROITS_TAXES` | `Db_Master_Tax` | FCFA, absolute | — |
| `caf_par_tonne` | derived | **FCFA / tonne** | `VALCAF / poids_tonnes` |
| barème CCC | `pl_official_farmgate_price` | **FCFA / kg** | ← the mismatch |

```sql
caf_moyen_kg = caf_par_tonne / 1000            -- FCFA/t → FCFA/kg
valeur_achats = tonnes * prix_fcfa_par_kg * 1000
```

Store **tonnes** and **FCFA**. Convert at the edge, once, never inside a formula.

`Db_Master_Tax` also ships precomputed `TAX %` and `CAF/kg`. v2 exposes them as `tax_pct` / `caf_kg` but computes its own. We drop both columns and recompute — assert they agree on load; a divergence means the upstream extract changed shape.

---

## 2. Product taxonomy — settled

### 2.1 The rule

`produit` resolves as (v2 `saison.py`, `_TAX_SQL`):

```sql
COALESCE(
  NULLIF(TRIM("PRODUIT SIMPLE"), ''),
  CASE substr(regexp_replace(CAST(POSTAR AS VARCHAR), '[^0-9]', '', 'g'), 1, 4)
    WHEN '1801' THEN 'FEVES'   WHEN '1802' THEN 'COQUES'
    WHEN '1803' THEN 'LIQUEUR' WHEN '1804' THEN 'BEURRE'
    WHEN '1805' THEN 'POUDRE'  WHEN '1806' THEN 'CHOCOLAT'
    ELSE 'FEVES'
  END)
```

Note the POSTAR is **stripped of non-digits before** taking the first 4 characters — v1 took `str[:4]` raw.

### 2.2 Bean-equivalence — HORS GRADE is a bean

```python
FEVES_PRODUITS   = ("FEVES", "HORS GRADE")     # api/app/data.py:282
TRANSFO_PRODUITS = ("MASSE", "BEURRE", "POUDRE", "CHOCOLAT")   # :283
```

This was contested because the WatchAI monthly report's mix table puts `HORS GRADE` inside `TOTAL TRANSFORMÉ`. **Three independent confirmations that it is a bean:**

1. **Price** (weighted CAF, 2024-2026, computed on the parquet):

   | Produit | FCFA/kg | % du prix fève |
   |---|---:|---:|
   | HORS GRADE | 3 019 | **96,8 %** |
   | FEVES | 3 118 | 100 % |
   | POUDRE | 3 855 | 124 % |
   | MASSE | 4 287 | 137 % |
   | CHOCOLAT | 4 468 | 143 % |
   | BEURRE | 5 560 | 178 % |

   Cocoa shells/waste trade at single-digit percentages of the bean price. At **96,8 %**, with a 3 % quality discount, this is off-grade *beans*. Everything genuinely transformed sits at 124–178 %.

2. **The customs heading is a fiscal choice, not physics.** `HORS GRADE` is declared 99,9 % under POSTAR **1802** ("coques, pellicules et déchets de cacao") — a lower-duty heading. The `PRODUIT SIMPLE` label carries the commercial truth.

3. **v2's own tested code** uses `produit IN ('FEVES','HORS GRADE')` for the material balance (`api/tests/test_bilan_matiere.py`).

**Commercial consequence — this is not cosmetic.** "Taux de transformation locale" is a politically loaded figure in Côte d'Ivoire. For 2025-2026 YTD:

- `part_non_fèves` = 473 907 t = **27,7 %** ← what the WatchAI mix table prints
- `transformation réelle` = 340 068 t = **19,9 %** ← beans correctly excluded

Compass publishes **19,9 %** under any label containing "transformation". The other figure may be exposed as `part_non_fèves`, never as transformation.

### 2.3 Canonical set for Compass

```
FEVES · HORS_GRADE · MASSE · BEURRE · POUDRE · CHOCOLAT · COQUES
is_bean_equivalent = product_code IN (FEVES, HORS_GRADE)
```

`MASSE` absorbs `LIQUEUR` / `PATE` at ingestion. **Fail loud** on an unknown POSTAR prefix or an unmappable `PRODUIT SIMPLE` — never default to `FEVES`.

### 2.4 The dormant hole

The POSTAR fallback emits `COQUES` (1802) and `LIQUEUR` (1803) — two labels absent from both `FEVES_PRODUITS` and `TRANSFO_PRODUITS`. A row carrying either would vanish from the material balance entirely.

**Verified on `11336ef`: 0 of 172 712 rows have a null or blank `PRODUIT SIMPLE`**, and the column holds exactly six values — `FEVES · HORS GRADE · MASSE · BEURRE · POUDRE · CHOCOLAT`. Neither `COQUES` nor `LIQUEUR` ever materializes. The fallback never fires on current data, and v2 says so in a comment. The hole is real but dormant; the fail-loud in §2.3 is sufficient. Do not build a chantier around it.

---

## 3. Season

October → September.

```sql
saison_start = CASE WHEN month >= 10 THEN year ELSE year - 1 END
saison       = saison_start || '-' || (saison_start + 1)
```

Month display order is always `10,11,12,1..9`, never calendar order.

**Asymmetry to normalize**: `tax` derives `saison` in SQL, but `achats` takes `SAISON` **verbatim from the source file**. We derive both, so a source-side labelling error cannot desynchronize the two series.

`INCOMPLETE_SEASONS` *(v1, L1018)* is an empty dict — dead feature.

---

## 4. Material balance — the v2 formulation (supersedes v1)

> **The v1 formulas are a known bug.** From `api/tests/test_bilan_matiere.py`:
> *« le code faisait (exports + broyage) / achats avec des exports TOUS PRODUITS : le transformé exporté étant la SORTIE du broyage, la même matière était comptée deux fois. Le taux de sortie affichait 124 % — on faisait sortir plus qu'on n'achetait — et le solde était négatif. »*
> Signalled 2026-07-17, fixed in v2. **Do not port the v1 formulas.**

### 4.1 The insight

Purchases and grinding are counted in **beans**. Exported transformed product is a **product weight** (customs `pds_net`). Adding the two double-counts: the beans were already consumed by grinding. The fix is to convert transformed exports **back to bean equivalent**:

```python
RENDEMENT_BROYAGE = 0.80          # api/app/data.py:292

broyage_deduit_t = transfo_exporte_t / RENDEMENT_BROYAGE
solde_t          = achats_t - feves_exportees_t - broyage_deduit_t
```

`broyage_deduit_t` is *larger* than the product weight — that is the point.

### 4.2 The window

`bilan_months = months(achats) ∩ months(exports)` — **not** the three-source intersection.

Because grinding is now *derived* from transformed exports, STATSER is no longer an input to the balance. It buys back the 2–3 months STATSER used to cost (STATSER stops at April 2026 while tax and achats run to July 2026), and removes the dependency on a third-party source.

### 4.3 Derived ratios

```python
solde_pct        = solde_t / achats_t * 100
taux_transfo_pct = broyage_deduit_t / achats_t * 100
taux_sortie_pct  = (feves_exportees_t + broyage_deduit_t) / achats_t * 100
```

> **Corrected 2026-08-17 — these are NOT invariants.** They were ported as
> assertions and immediately failed on real data. **2021-2022 reaches a
> `taux_sortie_pct` of 108,1 %.** The cause is not a double-count: the two sides
> have different populations. 102 exporters appear on the customs export side
> against 81 on the purchase side, and 34 exporters shipping 102 829 t are
> **absent from the purchase master entirely**. Stock also carries across
> seasons, so a season can legitimately ship matter bought in the previous one.
>
> Note also that the two are algebraically the same statement —
> `solde_t = achats_t × (1 − taux_sortie_pct/100)` — so a fixture built to trip
> one trips the other. They were never two independent checks.
>
> They are published as a **flag**, not enforced: `outflow_exceeds_purchases`
> on the transformation block, surfaced in the UI as a "Sorties > achats" pill.
> That is why the figure is called a solde **apparent**. Implementation:
> `app/services/origin_balance.py`; a 500 here would take the section down on a
> season that is simply honest about its own data.

What a double-count *would* look like is different and much larger: the v1 bug
that added transformed exports raw produced 124 % **with a bean-equivalent
denominator that had not been divided by 0,80** — a systematic offset on every
season, not one season standing out. The regression guard is the reconciliation
against the golden values (§6), not a range assertion on the ratio.

### 4.4 The display mode is display only

The `brut` / `feves` toggle changes **which export figure is shown**, never the balance:

```python
assert abs(brut["taux_sortie_pct"] - feves["taux_sortie_pct"]) < 0.01
assert abs(brut["solde_t"]         - feves["solde_t"])         < 1
```

This is a semantic break from v1, where the mode changed the meaning of the solde. Keep the v1 caveat text about `Solde apparent` **only** if the brut figure is displayed — the balance itself no longer mixes units.

### 4.5 The GEPEX perimeter bias — reduced, not gone

v2 keeps a `biased: not gepex_only` flag. The bias now only affects the **STATSER confrontation** (§5), not the balance, since the balance no longer reads STATSER. Any endpoint returning a composite ratio still states its perimeter in the payload.

---

## 5. STATSER confrontation — a consistency signal, not an input

Computed separately, on **STATSER's own window** (the 3-source intersection) and **its own perimeter** (GEPEX):

```python
deduit_t = transfo_exporte(common_months) / RENDEMENT_BROYAGE
ecart_t  = deduit_t - declare_t            # declare_t = sum(tons_broyes)
```

A gap is a **signal**, and it is worth surfacing: either STATSER under-reports, or transformed product is leaving without declared grinding. This is a genuinely new analytic with no v1 equivalent — arguably the most interesting thing in block ②.

---

## 6. YTD — one window per source

v2 replaces the single common window with **per-source YTD blocks**:

> *« Les 3 sources s'arrêtent à des mois différents : comparer chacune à son propre équivalent N-1 est le seul "vs an dernier" honnête. »*

```python
months      = sorted(months_present_in_this_source_this_season)
prev_months = [f"{int(m[:4]) - 1}-{m[5:]}" for m in months]   # same campaign months, −1 year
ytd_t, prev_t, delta_pct = ...
```

Each block carries `from`, `to`, `months` (count) so the UI can state the window it is comparing. **Never** compare a source's YTD against a window it doesn't cover.

This supersedes both v1 implementations (date-cutoff in Rapport Mensuel, month-set intersection in Analyse Achat/Saison) — the month-set logic survives, applied per source rather than globally.

**Verified against the published July 2026 report**: exports Oct25→Jul26 = 1 710 347 t and Oct24→Jul25 = 1 428 071 t, both exact. See [watchai-integration.md](watchai-integration.md) §9.

---

## 7. Per-exporter transformation

STATSER is a GEPEX aggregate — transformation is **not attributable per operator**. v2 uses the only observable proxy: each exporter's own transformed exports, as seen at customs.

```python
part_transfo_pct = transfo_t / (feves_t + transfo_t) * 100
```

Do not attempt to allocate the STATSER aggregate across exporters. Gates on `read:watchai:nominative`.

---

## 8. Croissance vs N-1 — the 250 t noise floor

*(v1, `calc_growth` L5486 — no v2 equivalent yet)*

```python
if vol_n1 < 250: continue                  # tonnes
growth_pct = (vol_n / vol_n1 - 1) * 100
top_hausse = nlargest(3)
top_baisse = nsmallest(3, among rows where vol_n > 0)
```

The 250 t floor kills the meaningless +4000 % from a 2 t base; excluding `vol_n == 0` from the drops stops exporters who simply stopped from monopolising the −100 % podium. Make the floor a named constant.

---

## 9. Mécanisme de stabilisation — CAF réel vs barème

*(v1 L5552+; v2 has `api/app/bareme.py` + `report.py::_bareme()` — richer, see [watchai-integration.md](watchai-integration.md) §11)*

```python
# barème selection
if 3 <= month <= 9 and season.caf_intermediaire: → campagne intermédiaire
else:                                              → campagne principale

caf_moyen_kg = mean(caf_par_tonne where notna and > 0) / 1000
ecart        = caf_moyen_kg - prix_caf_officiel
ecart_pct    = ecart / prix_caf_officiel * 100
```

Barème values come from `pl_official_farmgate_price`, never a ported constant.

Two flaws to fix on port:

1. **The mean is unweighted** — a 25 t declaration weighs as much as a 5 000 t one. Likely why 2024-2025 shows a realised CAF of 5 767 FCFA/kg against a 2 768 barème (+108 %). Publish the **volume-weighted** figure; keep the unweighted one internally for reconciliation.
2. **The N-1 comparison always uses `caf_principal`**, never the intermediate barème *(v1 L5570)*, so March–September comparisons use the wrong reference.

---

## 10. Entity canonicalization

`Entity_Mappings.xlsx`, 4 sheets — `Exportateurs`, `Destinataires`, `Declarants`, `Destinations` — **588 mappings**, raw customs name → canonical (`SACO → BARRY`, `CARGILL WEST AFRICA → CARGILL`).

The most valuable non-data asset in the repo, and it **grows every month**. Re-import on every ingestion, fail loud on an unmapped name — a silently unmapped exporter fragments a client's flows across two spellings. Because it grows, it also **rebinds old rows retroactively** (§12).

Only the `*_SIMPLE` columns are usable: the raw `EXPORTATEUR` / `DESTINATAIRE` columns contain literal `0` values.

**GEPEX membership** — 11 canonical names *(v1 `auth_config.py:25`, v2 `api/app/auth.py`)*:
`ATLANTIC · BARRY · CARGILL · CCB · CEMOI · ECOM · GCB · ICP · NESTLE · OLAM · SUCDEN`
→ `ref_origin_entity.is_gepex_member`, editable without a deploy. v2 matches on `upper(exportateur)`.

---

## 11. Watermarking — dropped

*(v1 `data_watermarking.py`; **v2 has no equivalent** — Julien dropped it too)*

Deterministic per-user noise: `seed = sha256(username) % (2³²−1)`, `clip(normal(0, 0.003), ±0.005)` multiplicative on tonnages, admin exempt.

Incompatible with the Benchmark row: an exporter reconciling their own tonnage against a noised figure sees a discrepancy and files a bug. Replaced by per-request access logging in `aud_*` plus a visible watermark on generated documents.

---

## 12. Refresh semantics — the masters are snapshots, not ledgers

| Source | Producer | Behaviour |
|---|---|---|
| `Db_Master_Tax` | `integrate_monthly_data.py` | **Appends** the new month |
| `Db_Master_Achats` | `consolidate_achats.py` | **Rebuilds from scratch** — *« Lit TOUS les fichiers ACHATS \*.xlsx »* |
| `Db_Master_Broyage` | `consolidate_broyage.py` | **Rebuilds** from one workbook covering 2012→present |

Three consequences:

1. **History moves between batches.** A corrected source file republishes prior months. Any per-month append design is wrong.
2. **`Entity_Mappings` growth rebinds the past** for every source we re-canonicalize.
3. **WatchAI's own history is internally inconsistent on names** — `Db_Master_Tax` appends and mappings apply at integration time, so a 2023 row keeps its 2023 mapping forever. We re-apply the current mapping over the whole history on every load, so our canonical names are consistent across time. A genuine quality gain — and a reason our nominative totals may legitimately differ from a WatchAI screen on older seasons.

**Design rule**: full snapshot replace per batch, previous batch retained for diffing, **every month whose totals moved is reported**. A silently restated figure a client has already seen is worse than a visibly late one. See [watchai-integration.md](watchai-integration.md) decision #8.

---

## 13. Quirks not to replicate

| Quirk | Where | Handling |
|---|---|---|
| `DECLARATION` partially populated — 101 113 / 172 712 (58,5 %) on `11336ef`, 0 % on `main` | parquet | Unusable as a natural key; a non-issue under full-snapshot semantics (§12). Do **not** be tempted to key on it now that it is partly filled. |
| Unknown POSTAR → `FEVES` | v1 L1966 / v2 `_TAX_SQL` `ELSE` | Fail loud (§2.3) |
| `COQUES` / `LIQUEUR` absent from both product sets | both | Dormant (§2.4) |
| Bare `except:` swallowing errors | v1 L1936, L1966 | Fail loud |
| `determine_season_export` defined then bypassed | v1 L4678 | Dead code |
| `db_sync.auto_sync_check()` returns `True` unconditionally | v1 `db_sync.py:85` | Dead code |
| `INCOMPLETE_SEASONS = {}` | v1 L1018 | Dead feature |
| Two YTD implementations | v1 L5370 / L4790 | Superseded by §6 |
| Material balance double-count | v1 L5068-5137 | **Superseded by §4** |
| Unweighted CAF mean | v1 L5578 | Expose weighted (§9) |
| N-1 stabilisation uses the wrong barème | v1 L5570 | Fix on port (§9) |
| `achats.saison` taken from the source file | v2 `_ACHATS_SQL` | Derive it ourselves (§3) |
