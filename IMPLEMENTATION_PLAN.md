## Implementation Plan: AAA Knowledge Surfacer

This plan operationalizes the AAA direction into concrete engineering phases and records what has already been executed.

### Phase 1: Deterministic Discovery First (Lane A)
- [x] Add deterministic-first handling for file-location queries so locate requests can return authoritative paths without waiting on retrieval + LLM.
- [x] Preserve existing response contract fields (`intents`, `file_location`, `duplicate_info`, `personnel_data`) so frontend behavior remains compatible.
- [ ] Expand deterministic lane to include canonical project resolver outputs (project ID, aliases, drive/server path) for all locate-style queries.
- [ ] Add stale-data indicators sourced from directory index and Ajera sync timestamps.

### Phase 2: Semantic Retrieval Resilience (Lane B)
- [x] Improve semantic expansion for outcomes/results language (e.g., findings, conclusions, recommendations) to reduce dependence on exact keywords.
- [x] Add doc-type hints for outcomes/results queries to bias toward report/assessment artifacts.
- [ ] Extend query rewriting to better cover natural-language locate/identity questions from pilot transcript examples.
- [ ] Add retrieval quality tests for outcomes-style vague queries against known pilot fixtures.

### Phase 3: Ranking and Fallback Behavior
- [x] Keep graceful low-confidence fallback when retrieval returns no chunks.
- [x] Keep citation provenance requirement (citations always returned or empty with low confidence).
- [ ] Add stronger deterministic-vs-retrieval intent gating (locate/identity -> deterministic first, content questions -> retrieval first).
- [ ] Add explicit "couldn't find that" phrasing standardization across all fallback paths.

### Phase 4: Observability and Pilot Scorecard
- [x] Add single primary `intent_class` to query logs for dashboarding.
- [x] Add `retrieval_count` to logs for query quality trend analysis.
- [x] Add `fallback_used` to logs for trust and failure-rate tracking.
- [ ] Add event counters for time-to-first-credible-answer and correction/rephrase rate.
- [ ] Build closed-beta scorecard job (baseline vs AAA on locate and knowledge-surfacing tasks).

### Execution Notes (Completed This Pass)
- Implemented deterministic short-circuit for successful file-location intent handling in the query endpoint.
- Implemented semantic expansion and hinting for outcomes/results queries.
- Extended query logging with `intent_class`, `retrieval_count`, and `fallback_used` fields.
- Added tests for outcomes expansion and outcomes doc-type hints.

### Files Updated
- app/backend/app/api/query.py
- app/backend/app/core/query_expander.py
- tests/test_query_endpoint.py
