# Prefix Search Reliability & Spellchecker Audit – Comprehensive Report

**Date:** October 27, 2025  
**Prepared by:** Prefix Search Taskforce  
**Scope:** Samokat · Dixy (Web/B2B/App) · Azbuka Vkusa · Auchan  
**Artifacts:** All deliverables live under `cache-investigation/` unless noted otherwise.

---

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [Data Sources & Key Artifacts](#data-sources--key-artifacts)
3. [Traffic Analytics Highlights](#traffic-analytics-highlights)
4. [Whitelist Quality Audit](#whitelist-quality-audit)
5. [Spellchecker Architecture & Risks](#spellchecker-architecture--risks)
6. [Automation & Scripts](#automation--scripts)
7. [Remediation Plan & Ownership](#remediation-plan--ownership)
8. [Operational Next Steps](#operational-next-steps)
9. [Appendix A – File Index](#appendix-a--file-index)
10. [Appendix B – Command Reference](#appendix-b--command-reference)

---

## Executive Summary
Prefix traffic represents up to **29%** of requests for high-volume sites (Samokat, Dixy App) and currently drives disproportionate zero-result rates. Two systemic issues were confirmed:

1. **Aggressive whitelist rules** (via AnyQuery/Kostyl) that replace partial inputs with unrelated terms.  
2. **Outdated spellchecker models** (AutoFiller) trained on noisy prefixes, producing unwarranted completions.

In addition, the current ranking stack struggles to leverage vector signals for short, evolving queries, leaving prefix traffic heavily dependent on simple lexical boosts.

We produced a full audit, dashboards, code notes, and a phased remediation plan that reduces risky rewrites, improves prefix recall, and clarifies ownership across Search Ops, Platform, Ranking, and NLP teams.

---

## Data Sources & Key Artifacts
| Artifact | Description | Location |
|---|---|---|
| Prefix metrics JSON | 7-day ClickHouse snapshot (short vs long query ratios, zero rates) | `cache-investigation/PREFIX_SHORT_STATS_20251027.json` |
| Flagged whitelist entries | Top suspicious rewrite rules per site | `cache-investigation/PREFIX_WL_FLAGGED_TOP_20251027.csv` |
| Quality report (raw) | Detailed whitelist statistics & samples | `cache-investigation/PREFIX_WL_QUALITY_REPORT_20251027.json` |
| Spellchecker analysis | Module-by-module breakdown (Kostyl, AutoFiller, Amender) | `cache-investigation/SPELLCHECKER_AUTOFILL_ANALYSIS.md` |
| HTML dashboard | Visual report including charts & summaries | `cache-investigation/PREFIX_REPORT_20251027.html` |
| Remediation roadmap | Owners, milestones, outstanding work | `cache-investigation/PREFIX_SEARCH_REMEDIATION_PLAN.md` |
| Debug diff script | Automation to compare corrections on/off | `cache-investigation/run_prefix_debug_diff.py` + output CSV |

For interactive charts, open `PREFIX_REPORT_20251027.html` in any modern browser (Chart.js is loaded via CDN).

---

## Traffic Analytics Highlights
Data source: `PREFIX_SHORT_STATS_20251027.json`

| Site | Short-Query Share | Short Zero% | Overall Zero% | Comment |
|---|---|---|---|---|
| **Samokat** | 20.0% | 5.3% | 9.5% | High prefix load; non-trivial failure rate. |
| **Dixy App** | 28.8% | 5.8% | 10.5% | Largest risk cluster – mobile behavior produces keystroke-level queries. |
| **Dixy Web/B2B** | 12–19% | up to 3.3% | up to 10.6% | Web sees fewer prefixes; B2B suffers from low inventory coverage. |
| **Azbuka Vkusa** | 16.9% | 0% | 0% | Prefixes exist but clean whitelists keep failures near zero. |
| **Auchan** | 6.5% | 0.6% | 4.4% | Small share yet many Cyrillic↔Latin corrections. |

Samokat and Dixy App are prioritized for remediation; both combine high volume with non-trivial zero rates.

---

## Whitelist Quality Audit
Input: `PREFIX_WL_FLAGGED_TOP_20251027.csv`

| Site | latin_in_corr | cyril_added | added_digits | long_phrase | Notes |
|---|---|---|---|---|---|
| Samokat | 6 | 13 | – | – | Numerous brand transliterations; some exact duplicates (“equal”). |
| Dixy Web | 9 | 11 | – | – | Classic Cyrillic↔Latin swaps (`valio`, `lay's`). |
| Dixy B2B | 11 | 9 | – | – | Similar to Dixy Web, plus mis-mapped product lines. |
| Dixy App | 13 | 5 | 4 | – | Mobile-specific digits added to brand names (`j7`). |
| Azbuka Vkusa | 17 | 3 | – | – | High reliance on Latin brand names. |
| Auchan | 4 | 15 | – | 1 | Snake-case transliterations from keyboard layout errors. |

- **latin_in_corr** – correction injects Latin characters where query was Cyrillic (and vice versa).  
- **cyril_added** – correction pulls in full Cyrillic words regardless of prefix validity.  
- **added_digits** – numeric brand suffixes inserted (`j7`).  
- **long_phrase** – entire multi-word slogans inserted for short inputs.

Action items: Remove or blacklist high-risk entries for priority sites; reinstate only business-approved mappings after peer review.

---

## Spellchecker Architecture & Risks
Reference: `SPELLCHECKER_AUTOFILL_ANALYSIS.md`

- **Kostyl** applies whitelist/blacklist substitutions before ML logic. It replaces any 1–5 token span found in `aq_config.correction_site_white_list`. This is the main source of aggressive rewrites (`bar → баранки`).
- **AutoFiller** builds per-site tries and typo models from feed + search logs to complete the last token. Noisy logs produce wrong suggestions (e.g., `картофель ф → картофельное`).
- **Amender** corrects typos via edit distance. When invoked after AutoFiller it cements incorrect completions.

Operational guidance:
1. Enable `usePrefixes=true` in `RankingRequestConverter` for short tokens so AnyQuery can rely on `prefixMap` and avoid calling the external spellchecker.
2. Rebuild AutoFiller datasets with stricter thresholds (min search frequency ≥ 5, candidate must exist in feed) before re-enabling for Samokat.
3. For unchanged behavior, cite `cache-investigation/PREFIX_DEBUG_DIFF_REPORT.csv` to confirm whether new corrections appear post-deployment.

### Detailed Problem Statement

| Pain Point | Why it happens | Impact |
| --- | --- | --- |
| **Whitelist dominance** | Kostyl runs before any machine learning module; every 1–5 token match is forcefully replaced. AnyQuery always invokes spellchecker with `usePrefixes=false`, so prefixMap is ignored. | User-typed prefixes get replaced by static phrases (`bon pari → bon paris`, `teos → густой йогурт`), causing relevance loss and noisy metrics. |
| **Spellchecker AutoFiller noise** | AutoFiller relies on tries built from raw search logs + feed. For sites like Dixy App, logs contain keystroke-level junk; model still “completes” them. | `картофель ф` becomes `картофельное`, `масло  ` loses trailing blanks, leading to incorrect ES queries and misaligned suggestions. |
| **Vectors unavailable for partial tokens** | Current vector strategies expect at least one clean token & classification output. Prefix queries typically have length ≤2 and classifier returns empty categories/attributes. | Autocomplete service falls back to lexical match + view boost; vector similarity payload is never used for >80% of prefix traffic. |
| **Prefix-specific ranking gaps** | Boosting rules (categories, brands) require exact tokens; with prefixes the boosts don’t fire. Rescoring relies on `numberOfViews`, so generic top sellers outrank true prefix matches. | Short prefixes return irrelevant “best sellers” instead of matching product families. |
| **No whitelisting governance** | No nightly QA, so new entries creep in unchecked. Spellchecker rebuilds also never clean the trie models. | Technical debt keeps growing; each new prefix bug requires manual grep in `aq_config`. |

### Spellchecker Modules (Detailed Analysis)

| Module | Purpose | Strengths | Limitations / Issues |
| --- | --- | --- | --- |
| **Simple Typo Handler (“short spellchecker”)** | Correct single-token typos up to 1–2 edits (keyboard layout, missing letters). | Fast, deterministic; good for classic misspellings (`молооко → молоко`). | Only operates on individual tokens; cannot understand context; stops working when two-letter prefixes are fed constantly (common on mobile). |
| **Amender** | Full typo correction (edit distance) with language-model weights. | Handles longer tokens, multi-edit corrections, spacing. | Invoked after AutoFiller and Kostyl, so it often “fixes” already incorrect replacements; lacks awareness of user intent for partial words. |
| **AutoFiller** | Completes the final word using tries and typo probability (`CTyposModel`). | Good when logs/feed are clean; fixes truncated words quickly. | Highly sensitive to noisy prefixes: if logs contain random keystrokes, the trie “learns” them and overrides user input (e.g., `картофель ф → картофельное`). |
| **Layout Switcher / Brand Replacer** | Map Latin to Cyrillic, brand aliases. | Helpful for transliterations. | Without guardrails, they cause `latin_in_corr` churn (e.g., forcing `tess` → `тесс`). |

### Product Requirements for Prefix Ranking

To hand off the work effectively, we summarized real raw queries (without spellchecker rewrites) and how ranking is expected to behave for each site. Data source: ClickHouse `sessions.searches` (7-day window). The classifier **does not emit categories or attributes** for tokens shorter than ~3 symbols; vector models also require a stable bag-of-words. Therefore, short prefixes currently bypass classification, attribute detection, and vectors — leaving money “on the table” for merchandisers and forcing users to type the entire term manually.

| Site | Sample raw queries (as typed) | Ranking expectations | Must NOT happen |
| --- | --- | --- | --- |
| **Samokat** | `si`, `te`, `bon pa`, `йогурт гре`, `филе инд`, `йогурт греческий`, `bon pari оранж`, `te fal`, `samsung s23`, `филе индейка 1 кг` | 1) Show exact prefix categories (e.g., `si` → сигареты + сигары) 2) Keep longer multi-token requests intact even with typos (`йогурт греческий` vs `йогурт гре`) 3) `samsung s23` should use vectors + attributes even if one token is partial. | Replacing `bon pa` with “bon paris” (French phrase). Splitting `samsung s23` and ranking by “Samsung best sellers” only. |
| **Dixy Web** | `мол`, `val`, `lay`, `холс`, `магг`, `шоколад темный`, `крем для рук`, `val amico`, `lay chips`, `nestle gold` | 1) Recognize brand prefixes even when classifier is empty; use brand = `lays` 2) Multi-token phrases with partial endings (`крем для рук`) should respect attribute boosts (skin care) 3) For transliterations (`val amico`) keep Italian brand mapping. | Promoting random top sellers (“макароны”) just because views are high. Dropping brand-specific promotions due to missing classification. |
| **Dixy B2B** | `гар`, `опл`, `fris`, `hame`, `сыр моцарелла 2кг`, `масло растительное 10л`, `fris cat adult`, `оплата карта`, `cheddar 5kg` | 1) Business customers expect SKU-level matches (box packaging). 2) Numeric weights (`2кг`, `5kg`) should be preserved for availability sorting. 3) Queries mixing Russian/English words must stay intact to hit B2B catalog names. | Returning household goods instead of pet food. Ranking by consumer popularity rather than B2B stock levels. |
| **Dixy App** | `ма`, `масло `, `кар`, `кар тофель`, `молоко без лакт`, `детское питание фрут`, `масло сливочное крестьян`, `хлеб без дрож`, `сок детский яб`, `памперсы 3` | 1) Accept keystroke-level prefixes and keep the same intent across keystrokes. 2) Multi-token partials (`масло сливочное крестьян`) should rank the full product line, not reset after each token 3) Preserve numeric sizes (`памперсы 3`) to avoid mixing size ranges. | AutoFiller changing `масло  ` to `масло сл` or `масло оливковое`. Classifier output = null and ranking falling back to “Top Views” (irrelevant). |
| **Azbuka Vkusa** | `pr`, `ries`, `санп`, `prosecco rose`, `riesling mosel`, `санпеллегрино лимон`, `сыр brie`, `вино вилла мария`, `premium gift box` | 1) Recognize premium brand prefixes (`pr` → prosecco). 2) Longer multi-word phrases (wine type + region) should hit curated listings with attribute filters. 3) Accept mixture of Cyrillic + Latin without reordering tokens. | Transliteration forcing everything to Cyrillic and losing imported labels. Stripping descriptors like “mosel”. |
| **Auchan** | `xfq`, `adapter`, `yjcrb`, `чайник электрический 1.5`, `adapter usb c hdmi`, `yjcrb gfhj`, `крышка на елку 50 см`, `шиньон детский`, `xfqyfz сервиз`, `сейв софт наволочка` | 1) Layout switcher should map `xfq` → `чай`. 2) Long multi-token queries with measurements must keep unit order for matching `1.5 л`. 3) Prefix errors (keyboard layout) should be corrected but context (e.g., “adapter usb c hdmi”) preserved. | Kostyl rewriting multi-word queries into unrelated phrases. Dropping measurement tokens or reordering words, causing mismatch. |

**Key requirements derived from these examples:**
- Maintain prefix intent across keystrokes without rewriting the query (especially on mobile apps).  
- Provide fallback category/brand hints based on prefix statistics when classifier is silent.  
- Allow transliteration/layout corrections but keep original prefix order for ranking.  
- Avoid global best-seller overrides: prefix-specific signals should outweigh generic popularity.  
- Vector embeddings must be retrained or layered so that short tokens still receive semantic guidance; otherwise, the entire vector stack is bypassed.  
- Logging should capture the original raw prefix, the applied correction (if any), and normalized query so we can audit mismatches.

---

## Automation & Scripts

### Debug Diff Runner
- **Path:** `cache-investigation/run_prefix_debug_diff.py`
- **Purpose:** Calls `https://sort.diginetica.net/debug` with `withCorrection=true/false` for sample prefixes.  
- **Usage:**
  ```bash
  cd cache-investigation
  ./run_prefix_debug_diff.py
  ```
  Output is stored in `PREFIX_DEBUG_DIFF_REPORT.csv` (50 rows by default – adjust the script to expand coverage).

### HTML Dashboard
- **Path:** `cache-investigation/PREFIX_REPORT_20251027.html`
- **Contents:** Executive snapshot, metrics table, dual bar chart (short-query mix vs zero rates), stacked chart for whitelist risk.  
- **Viewing:** open in Chrome/Firefox. Charts load via Chart.js CDN.

### Metrics Export
- **Path:** `cache-investigation/PREFIX_SHORT_STATS_20251027.json`
- **Schema:** `site_id`, `site_name`, `total_queries`, `short_queries`, `short_ratio`, `short_zero_ratio`, `overall_zero_ratio`.  
- **Upsert:** use `scripts/collect_prefix_stats.sql` (prepared separately) or the ClickHouse query referenced in the plan.

---

## Remediation Plan & Ownership
Documented in `PREFIX_SEARCH_REMEDIATION_PLAN.md`. Summary below:

| Workstream | Owner | Key Deliverables | Due |
|---|---|---|---|
| Whitelist cleanup | Search Ops | Approve/remove risky rules; implement nightly QA report | Nov 5 |
| AnyQuery & spellchecker guardrails | Platform | Enable `usePrefixes`, add length/alphabet guard, rebuild AutoFiller | Nov 12 |
| Ranking improvements | Ranking | Edge n-gram fields, prefix-aware boosting, adjustable rescore windows | Nov 12 |
| Query understanding | NLP | Prefix → category lookup, classifier fallback for short tokens | Nov 19 |
| A/B validation & rollout | PM/Search PM | Launch prefix-safe pipeline vs baseline, monitor zero-result & CTR | Dec 3 |

### Deep Dive: Proposed Ranking Enhancements

1. **Prefix purity score** – boost documents whose normalized name starts exactly with the user prefix; penalize mid-token matches via a scripted score or `match_phrase_prefix` on edge-ngram fields.
2. **Behavioral priors** – ingest ClickHouse click logs to build `prefix → product/category` lookup and apply as `function_score` multipliers when classifier is empty.
3. **Dynamic view weighting** – scale down `numberOfViews` rescorer weight for queries shorter than 3 characters to avoid best-seller dominance.
4. **Hybrid vector blending** – re-enable vector signals by seeding prefix queries with curated vector candidates (learned from successful completions) and blending lexical/vector scores.
5. **Classifier fallback** – when segments/categories are missing, inject top categories inferred from prefix statistics so merchandising boosts can still operate.

--- 

## Operational Next Steps
1. **Search Ops (Week 1)** – Execute whitelist cleanup, aligning with the flagged CSV; document rationale for each retained rule.  
2. **Platform** – Ship configuration change for AnyQuery (`usePrefixes` toggle) and integrate spellchecker guards; rehearse spellchecker model rebuild in staging.  
3. **Ranking** – Prototype ES schema updates (edge n-gram fields); prepare migration plan and performance benchmarks.  
4. **NLP** – Produce prefix categorical lookup tables from ClickHouse and expose via RequestClassifier fallback.  
5. **Product/PM** – Draft experiment design (metrics, success thresholds) and coordinate cross-team communication.

---

## Appendix A – File Index

| File | Summary |
|---|---|
| `cache-investigation/PREFIX_SHORT_STATS_20251027.json` | Prefixed query metrics per site (7-day window). |
| `cache-investigation/PREFIX_WL_FLAGGED_TOP_20251027.csv` | Top suspicious whitelist entries for quick triage. |
| `cache-investigation/PREFIX_WL_QUALITY_REPORT_20251027.json` | Full whitelist audit with statistics and sample pairs. |
| `cache-investigation/SPELLCHECKER_AUTOFILL_ANALYSIS.md` | Module-level spellchecker analysis. |
| `cache-investigation/PREFIX_SEARCH_REMEDIATION_PLAN.md` | Workstream charter and milestone schedule. |
| `cache-investigation/PREFIX_REPORT_20251027.html` | Executive report with visuals and links. |
| `cache-investigation/run_prefix_debug_diff.py` | Script to generate correction diffs. |
| `cache-investigation/PREFIX_DEBUG_DIFF_REPORT.csv` | Latest execution output of the debug diff script. |

---

## Appendix B – Command Reference

| Task | Command |
|---|---|
| Generate debug diff report | `./cache-investigation/run_prefix_debug_diff.py` |
| Refresh HTML charts (open in browser) | `open cache-investigation/PREFIX_REPORT_20251027.html` |
| Regenerate whitelist risk summary | `python - <<'PY' ...` (see report generation section) |
| Collect ClickHouse stats (manual) | Refer to SQL in the investigation plan (`SELECT … FROM searches`). |

For maintenance, keep all artifacts under version control and update the dates in this document when new datasets are produced.
