# Prefix Search vs SORT Behaviour (Sites 2056, 2164, 5631, 6321, 221, 674)

## Scope & Data
- **Window:** last 7 days relative to `2025-10-27` (rolling `now() - 7d` in ClickHouse).
- **Source:** `sessions.searches` table in production ClickHouse (`cache-investigation/PREFIX_SEARCH_STATS_20251027.json` keeps raw aggregates).
- **Definitions:**  
  - *Rewrite* – `searchTerm` differs from `originalSearchTerm`.  
  - *Prefix expansion* – `length(searchTerm) > length(originalSearchTerm)` for non-empty terms.  
  - *Short single* – single-word queries with 2–5 UTF-8 chars; proxy for incomplete input that still triggered SORT.  
  - *Zero-hit* – records with `isZeroQuery = 'true'`.
- **How SORT handles prefixes:** `AbstractProductsQueryProvider` adds a `match_bool_prefix` rescorer for every SORT request (`src/main/java/com/diginetica/autocomplete/strategy/AbstractProductsQueryProvider.java:108`), and `SortingAttributesModifierImpl` wires it in by default (`src/main/java/com/diginetica/autocomplete/services/SortingAttributesModifierImpl.java:170`). Prefix candidates themselves come from the external prefix-search service (`src/main/java/com/diginetica/autocomplete/services/PrefixSearchServiceExternal.java:75`).

## SORT Prefix Code Path
- Request flow: `/search` hits `RangingController.java:66`, which hands off to `RangingServiceImpl.java:52` to build a `ProductsQueryRequest` and execute ES queries.
- Request construction: `CommonProductsRequestFactory.java:31` seeds the builder; modifiers attach classification (`QueryClassificationProductsRequestModifier.java:23`) and sourcing (`SourceProductsRequestModifier.java:21`). Ranking-specific modifiers (e.g. `RankingVectorsProductsRequestModifier.java:36`) append vector candidates and category guesses.
- Classification fallback: `ExternalRequestClassifier.java:60` calls REST classifiers per strategy. When the external service cannot understand a prefix fragment it returns sparse categories/attributes, leaving ranking with almost no semantic features.
- Query build: `DefaultProductsQueryService.java:51` collects should-clauses (name/xname/tags/brand/attributes) and wraps them in a bool query. Prefix rescoring is not optional: the rescorer gets attached by `SortingAttributesModifierImpl.java:170` with the provider’s `getPrefixMatchPartRescorer`.
- Candidate retrieval nuances:  
  - `QueryProviderUtils.java:31` tokenises the normalized query, keeps alphanumeric codes intact, and feeds subtokens into `multi_match` with `prefixLength=1`—that is where partial tokens first enter the candidate pool.  
  - `MultiTextProductsQueryProvider.java:27` even adds a prefix filter (`matchBoolPrefix(name, …)`) into the base candidate set when that strategy is enabled.  
  - Vector strategies (`AbstractVectorsProductsQueryProvider.java:104`) still fall back to the generic prefix rescorer when an LTR model is unavailable.
- Normalisation & whitelists: `AnyQueryServiceImpl.java:103` loads AQ white/black lists and a per-site prefix map; if the prefix map knows the stem the query is *not* sent to spellchecker, otherwise the whitelist decides the rewrite. This is the current choke-point for truncated inputs.
- Prefix suggestions: `PrefixSearchServiceExternal.java:129` calls the dedicated prefix-search service to retrieve prefix-normalised search terms; these suggestions feed autocomplete as well as SORT feature bags through the classifier’s stemmed bag.

## Observed Prefix Behaviour in SORT Logs
Metrics come from `cache-investigation/PREFIX_SEARCH_STATS_20251027.json:1` (7-day window).

| site | total queries | prefix expansions | expansions → zero | short 2–5 char singles | short → zero |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2056 | 28.79 M | 3.17 M (11.0 %) | 308 k (9.7 %) | 9.43 M (32.8 %) | 502 k (5.3 %) |
| 2164 | 120 k | 5.5 k (4.6 %) | 0 | 34 k (28.4 %) | 0 |
| 5631 | 7.4 k | 955 (12.9 %) | 166 (17.4 %) | 1.86 k (25.1 %) | 114 (6.1 %) |
| 6321 | 2.14 M | 1.16 M (54.4 %) | 106 k (9.1 %) | 857 k (40.1 %) | 54 k (6.3 %) |
| 221 | 37.6 k | instrumentation gap (0 recorded) | – | 9.8 k (26.1 %) | – |
| 674 | 1.13 M | 8.0 k (0.7 %) | 1.9 k (23.7 %) | 147 k (13.0 %) | 1.3 k (0.9 %) |

Additional findings (`cache-investigation/PREFIX_EXPANSIONS_20251027.json:1`):
- Site 2056’s top zero-hit rewrites are brand drifts: `теос`→«густой йогурт и творожки», `панировочные сухари`→«панировочные сухарики», `чебу`→«чебуреки».
- Site 674 lacks a whitelist entry for `frambini`→`frambinini` (82 executions, 64 zero hits) and exhibits several wrong-side expansions (`вода святой источник`→«сахарозаменитель milford жидкий»).
- Site 5631 shows transliteration issues: mixed-case `ХОЛС`/`холс`→`halls` still yield zero when inventory is empty or the correction is absent.
- Site 221 writes empty `originalSearchTerm` / `isZeroQuery` columns, so every metric around prefixes is currently blind—logging must be restored before remediation.

### Zero-Hit Backlog
Top zero-result expansions per site were materialised to `cache-investigation/PREFIX_ZERO_EXPANSION_BACKLOG_20251027.csv:1`. Highlights:
- **674:** 50/50 pairs missing from whitelist; biggest offenders are `frambini`→`frambinini` (38 zero hits) and `вода святой источник`→«сахарозаменитель milford жидкий» (22). All require new whitelist entries or outright blocking.
- **2056:** Split evenly between existing and missing rules. High-volume misses include `teos` and `теос` variants (no whitelist) and `панировочные сухари`→«панировочные сухарики» (should map to the base product, not a diminutive). Existing rules like `мороз`→`морозко` still fail, hinting at assortment gaps.
- **5631:** 45 missing, 5 present. `ХОЛС`/`холс` already whitelisted but still zero—stock issue. Missing rules (`Фреш бар`→`fresh баранки`) need review.
- **6321:** 25 missing, 25 present. Many failures stem from mid-token submissions (`масло  `→`масло с`) that should be handled via partial matching rather than whitelist rewrites.
- **2164/221:** No data (zero-hit list empty due to low traffic or instrumentation outage).

Use the CSV to drive WL/BL tickets; each row carries the recommended action (`Add-whitelist` vs `Investigate-existing`).

## Cross-Site Highlights
- Prefix rewriting is widespread: |site 6321| rewrote **99.5 %** of queries, |2056| ~30 %, |5631| ~52 %, |674| ~76 %.
- Prefix expansions are strongly site-dependent: |6321| expands **54.4 %** of traffic, |2056| 11.0 %, |5631| 12.9 %, |2164| 4.6 %, |674| only 0.7 %, |221| 0 % (instrumentation gap).
- Short single-word queries (2–5 chars) already reach SORT frequently (32.8 % for 2056, 40.1 % for 6321). Zero-hit rate among them stays single-digit except for low-volume sites.
- Zero results after prefix expansion remain non-negligible: 9.7 % (2056), 17.4 % (5631), 23.7 % (674), signalling dictionary gaps or overly aggressive rewrites.

## Site Deep Dives
### Site 2056 (28.8 M queries / 7 d)
- **Diversity:** 556 k unique executed terms vs 1.08 M original inputs → aggressive normalisation.  
- **Rewrites:** 30.4 % overall; **11.0 %** explicit prefix completions (`моро`→`мороженое`, `карто`→`картофель`).  
- **Short single words:** 32.8 % of traffic; 5.3 % of those end in zero results.  
- **Zero hits:** 9.6 % overall; prefix expansions fail 9.7 % of the time (~308 k events).  
- **Top prefix completions:** `моро`→`мороженое` (36.9 k), `моло`→`молоко` (31.7 k), `энер`→`энергетический` (29.5 k) – all succeed, but long-tail prefixes like `огур`→`огурцы` show isolated failures (25 zero hits).  
- **Observation:** Heavy restaurant/grocery intent mixing in sample sessions indicates iterative user typing; SORT tolerates partial tokens but relies on prefix completions to anchor ranking.

### Site 2164 (120 k queries)
- **Rewrites:** 13.9 % (mostly casing/diacritics). Prefix expansions modest (4.6 %).  
- **Stability:** zero-hit rate effectively 0; even empty submissions are rare.  
- **Top expansions:** `пицца`→`пицца москва`-style enrichments absent; instead morphological pluralisation (`яблоко`→`яблоки`) used sparingly.  
- **Takeaway:** SORT handles prefixes, but current load does not stress prefix dictionaries.

### Site 5631 (7.4 k queries)
- **Rewrites:** 52.1 % with 12.9 % true expansions.  
- **Zero hits:** 10.9 % overall; prefix expansions fail 17.4 % of the time (e.g., `halls` capitalisation issues).  
- **Top expansions:** brand transliterations dominate (`ролтон`→`роллтон`, `вискас`→`whiskas`, `хохланд`→`hochland`), revealing reliance on Latin-script canonical forms.  
- **Risk:** Low-volume site is sensitive to dictionary drift; missing transliteration pairs turn into zero hits quickly (e.g., `hals` variations).

### Site 6321 (2.14 M queries)
- **Rewrites:** 99.5 % (!) – original payloads are almost always short stems (`сы`, `мас`, `коф`).  
- **Prefix expansions:** 54.4 % of all traffic; zero-hit rate for expanded queries still 9.1 %.  
- **Short singles:** 40.1 % of queries; despite aggressive completions, users also execute short tokens outright (`мас`, `коф`, `тв`).  
- **Implication:** Client-side (probably mobile) sends early keystrokes into SORT, relying on backend to finish tokens. Without robust prefix lists, ranking quality degrades severely.

### Site 221 (37.7 k queries)
- **Instrumentation gap:** `originalSearchTerm` empty and `isZeroQuery` null in ClickHouse (`SELECT` sample confirms). Rewrites appear at 100 % only because raw term is missing.  
- **Action:** Restore logging pipeline (likely Sort-side event serializer) to regain visibility before drawing prefix conclusions.

### Site 674 (1.13 M queries)
- **Rewrites:** 76.0 % (mostly normalisation). Prefix expansions tiny (0.7 %) yet risky: **23.7 %** of expanded cases still zero out (`frambini`→`frambinini`, `айсберг`→`салат айсберга`).  
- **Short singles:** 13.0 % of traffic with only 0.9 % zero-hit ratio.  
- **Next step:** Audit prefix whitelist for specialist terms (imported goods) – a few incorrect expansions generate a disproportionate share of failures.

## Mechanism Notes
- Prefix completions originate from the dedicated prefix-search service, cached per-site (`PrefixSearchServiceExternal`, `src/main/java/com/diginetica/autocomplete/services/PrefixSearchServiceExternal.java:75`).  
- SORT always adds a prefix rescorer over `extended_name`, weighting it via per-site coefficients (`Coefficient.PREFIX`, default 3.0).  
- `AnyQueryServiceImpl` uses the local `prefixMap` to decide whether to send text to spellchecker (`src/main/java/com/diginetica/autocomplete/services/AnyQueryServiceImpl.java:116`). Sites with poor coverage (e.g., 6321) fall back to prefix completions on nearly every keystroke.

## Recommendations
1. **Repair logging for site 221** so `originalSearchTerm`/`isZeroQuery` are populated; otherwise we cannot measure prefix effectiveness.
2. **6321:** validate `prefixMap` coverage and consider throttling client submissions (debounce) – 54 % expansions with 9 % failure suggest client sends keystrokes too early.
3. **5631 & 674:** enrich transliteration/brand dictionaries; target expansions with double-digit zero-hit share (e.g., `halls`, `frambini`, `fresh` variants).
4. **2056:** monitor long-tail prefixes causing misses (`огур`, `энерг`) and adjust ANY Query white/black lists or prefix dictionaries to cut ~300 k failed expansions per week.
5. **All sites:** expose metrics for prefix rescorer hit-rate in SORT (e.g., log `match_bool_prefix` contribution) to confirm ES-side scoring matches expectations.

## Whitelist/Blacklist Review (PostgreSQL)
Using `POSTGRESQL_URL` we inspected AQ correction lists:
- Tables: `aq_config.correction_white_list`, `aq_config.correction_site_white_list`, `aq_config.correction_black_list`, `aq_config.correction_site_black_list`.
- Entry counts per site (white/black):
  - 2056: 10,187 / 2,829
  - 2164: 12,636 / 17
  - 5631: 15,771 / 18
  - 6321: 20,777 / 243
  - 221: 7,094 / 336
  - 674: 13,542 / 22

Observations:
- Many common grocery stems are already whitelisted across sites (`огур`→`огурцы`, `энерг`→`энергетический`, `холс`→`halls`, `вискас`→`whiskas`).
- Site 674 shows a high-failure prefix expansion `frambini`→`frambinini` in ClickHouse (64/82 zero hits in 7d), but this pair is NOT present in `correction_site_white_list` for 674, indicating a missing whitelist rule.
- On 2056, multiple zero-hit expansions are brand/typo drifts (e.g., `теос`→"густой йогурт и творожки", `панировочные сухари`→`панировочные сухарики`). These require correction to precise brands/terms instead of broad phrases.
- `cache-investigation/PREFIX_WL_CANDIDATES_20251027.csv:1` contains the top-15 missing corrections per site. Highlights:
  - 674: `frambini`→`frambinini`, `вода святой источник`→(stay as is), `бон пари`→`bon paris`, `подарочный набор чай гринфилд`→`… greenfield`. All currently lack whitelist coverage.
  - 2056: `teos`/`теос`→`teos`, `панировочные сухари`→`панировочные сухари`, `Крупс`→`krups`, `пингви`→`pinguin`. Many zero hits despite high volume—should be fixed before further tuning.
  - 5631: `Фреш бар`→`fresh bar`, case-insensitive `холс`→`halls`. Several capitalisation variants missing.
  - 6321: mid-token fragments (`масло `→`масло`, `си`→`сиг`) dominate; treat as ranking feature gaps rather than whitelist candidates.

Prioritised whitelist backlog suggestions:
- 674: add `frambini`→`frambinini`; verify and fix erroneous expansions listed in top zero-hit pairs (e.g., `вода святой источник`→`сахарозаменитель milford жидкий` is likely incorrect and should be blocked or corrected).
- 5631: verify transliterations (`fresh bar`, `halls`, `whiskas`) and add missing pairs per top zero-hit expansions; ensure casing-insensitive rules.
- 2056: curate brand/phrase corrections for top zero-hit expansions (e.g., `теос`→`teos`, `панировочные сухари` stay within same product class).

## Beyond Whitelists: Ranking Strategy for Partial Queries
- **Candidate generation**
  - Add explicit prefix fields (edge-ngram) for product name, xname, and brand so incomplete tokens produce high-recall matches without lexical rewrites; wire them into `getBaseMatchPart` alongside existing trigram/extended queries.
  - Backfill a ClickHouse-derived prefix→product co-occurrence table (e.g., top 50 products per prefix) to seed `ProductsQueryRequest.setIds` similarly to how vectors are injected today (`RankingVectorsProductsRequestModifier.java:70`).
- **Feature design without categories/attributes**
  - Generate char n‑gram overlap scores (Jaccard, cosine) between prefix and candidate names inside ES using painless scripts; they remain meaningful even when the classifier returns empty attribute sets.
  - Expose behavioural priors (prefix frequency, conversion CTR) as numeric features inside the stored LTR model (for sites where `AbstractVectorsProductsQueryProvider` falls back to sltr).
  - Build a prefix→category distribution from logs to fill `QueryClassification` when the REST classifier fails; use the high-probability category as a soft boost via `categories_with_scripted_similarity` rather than a hard filter.
- **Reducing manual whitelists**
  - Promote top prefix expansions with healthy conversion & zero-hit deltas into an automated correction dataset (updated nightly) instead of editing `aq_config` tables by hand.
  - Add a guardrail that blocks obviously wrong rewrites (e.g., query/category mismatches) by emitting black-list candidates when `searchTerm` drifts outside the original token’s trigram envelope.
- **Instrumentation**
  - Log prefix rescorer deltas, candidate counts, and classification fallbacks so we can quantify the impact of each new feature; publish them per site/segment for regression monitors.

## Improved Research Plan (Repeatable)
1) Data pulls
- ClickHouse: extract 7-day aggregates for each site (done in `PREFIX_SEARCH_STATS_20251027.json`) and a focused export of top 50 zero-hit prefix expansions per site.
- PostgreSQL: export per-site correction whitelist/blacklist and join to identify missing pairs for top zero-hit expansions.

2) Diagnostics
- Compute KPIs: rewrite%, prefix-expansion%, zero-hit% overall and for short single tokens; zero-hit% among expanded queries; top failing (orig→search) pairs per site.
- Join with whitelist to classify each failing pair as: missing, incorrect, or needs blacklist.

3) Remediation backlog
- For each site, propose: (a) whitelist additions (orig→target), (b) blacklist entries for clearly wrong expansions, (c) normalization fixes (casing, spacing), (d) client debouncing (for sites like 6321).

4) SORT scoring validation
- Add ES-side metric: contribution from `match_bool_prefix` rescorer to final score distribution per site/query-length bucket; verify weight `Coefficient.PREFIX` sufficiency.
- Capture n-gram overlap and prefix-hit features to confirm the new partial-query signals fire as intended.

5) Rollout & verification
- Apply top 20 site-specific whitelist additions; block top 10 erroneous expansions per site.
- Re-run ClickHouse checks after 24–48h: expect drop in zero-hit% among prefix expansions and improved conversion on short singles.

6) Automation
- Add a nightly job to: pull last 7d top zero-hit expansions, diff against whitelist/blacklist, create CSV for approval, and (optionally) an automated PR to update correction lists.

## How to Run Locally
- ClickHouse queries are embedded in helper scripts used for `PREFIX_SEARCH_STATS_20251027.json` and zero-hit exports.
- PostgreSQL extraction: connect to `aq_config` schema and join `correction_site_white_list`↔`correction_white_list`, `correction_site_black_list`↔`correction_black_list`.
- Output: JSON reports + a CSV backlog per site with proposed actions (Add WL / Add BL / Fix mapping) to feed into moderation.
