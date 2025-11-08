# Prefix Search Remediation Plan (2025-10-27)

## Goals
1. Eliminate harmful query rewrites for partial inputs.
2. Restore relevance signals (classification, boosting, vectors) for prefix traffic.
3. Provide monitoring & guardrails for future whitelist/spellchecker updates.

## Workstreams

### A. Data Audit & Monitoring (Owner: Search Analytics)
- [x] Build ClickHouse metrics for short vs long query performance (`PREFIX_SHORT_STATS_20251027.json`).
- [ ] Daily dashboard: short-query share, zero-result rate, correction source (`normalizedBy`).
- [ ] Weekly review of `prefix_bad_examples` from the debug API diff.

### B. Whitelist Cleanup (Owner: Search Ops)
- [x] Generate quality report + flagged entries (`PREFIX_WL_QUALITY_REPORT_20251027.json`, `PREFIX_WL_FLAGGED_TOP_20251027.csv`).
- [ ] Approve removal/blacklisting of high-impact entries (Samokat, Dixy, Dixy App, Auchan).
- [ ] Automate nightly report that highlights new suspicious rules.

### C. Spellchecker Adjustments (Owner: Platform)
- [x] Document module behavior (`SPELLCHECKER_AUTOFILL_ANALYSIS.md`).
- [ ] Deploy configuration to enable `usePrefixes=true` for short tokens in SORT.
- [ ] Add guard in AnyQuery to reject corrections where `len(correction) ≥ 3 * len(query)` or alphabet set changes.
- [ ] Rebuild AutoFiller models with stricter dataset filters (min frequency, feed validation).

### D. Ranking Improvements (Owner: Ranking Team)
- [ ] Add edge-ngram fields and point prefix rescorers to them.
- [ ] Modify boosting rules to accept prefix matches.
- [ ] Introduce prefix fallback for vector strategies (disable for tokens <3 characters).

### E. Query Understanding (Owner: NLP Team)
- [ ] Derive `prefix -> top categories` lookup from ClickHouse logs.
- [ ] Integrate fallback category prediction when classifier confidence is low.

### F. Validation & Rollout (Owner: PM)
- [ ] A/B test “prefix-safe pipeline” vs current baseline.
- [ ] Monitor zero-result rate, CTR, conversion lift.
- [ ] Publish migration guide & SOP for whitelist updates.

## Milestones
| Milestone | Owner | Target |
|-----------|-------|--------|
| Audit Complete & Cleanup Approved | Search Ops | Nov 5 |
| AnyQuery + ES Prefix Fix deployed | Platform/Ranking | Nov 12 |
| Query understanding + vectors fallback | NLP | Nov 19 |
| A/B Test Results & Final Rollout | PM | Dec 3 |

