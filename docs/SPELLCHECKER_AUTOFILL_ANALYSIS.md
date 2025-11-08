# Spellchecker Autocomplete Analysis (2025-10-27)

## Module Overview
- **Kostyl** (`correction/src/kostyl.py`)
  - Applies site-specific whitelist/blacklist rules before any ML logic.
  - Iterates over n-grams (1–5 tokens) and replaces them with corrections from `aq_config.correction_site_white_list`.
  - Masks processed tokens, preventing further modules from altering them.
  - Source of deterministic rewrites (e.g., `"бар" → "баранки"`).

- **AutoFiller** (`correction/src/filler.py`)
  - Statistical auto-completion for the last token in a query.
  - Builds per-site Trie + `CTyposModel` from feed and search logs (`update_site_model`).
  - Generates candidate completions using typo probabilities, language model scores, and draw probabilities.
  - Beam-search (top 3) and final sanity check via `storage.check_in_feed`.
  - Disabled for `site_id = 2056` (Samokat) in production.

- **Amender**
  - Traditional typo correction module with edit-distance heuristics.

## Key Findings
1. Whitelist rules are applied **before** AutoFiller, so manual corrections override learned behavior.
2. AutoFiller only targets the **last token** and only when a valid prefix exists in the Trie.
3. Candidate priors rely heavily on historical frequency; noisy logs lead to poor suggestions.
4. For short prefixes, missing `prefixMap` guard means AnyQuery still sends requests to spellchecker, re-triggering these modules.

## Risks & Next Steps
- Remove or constrain whitelist entries that perform aggressive rewrites (see `PREFIX_WL_FLAGGED_TOP_20251027.csv`).
- Enable `usePrefixes=true` in SORT for short tokens to bypass spellchecker when prefix is known.
- Audit `update_site_model` inputs; ensure only high-confidence prefixes enter the Trie and typo datasets.
- Consider A/B testing AutoFiller with stricter thresholds (min frequency, max completion length).

