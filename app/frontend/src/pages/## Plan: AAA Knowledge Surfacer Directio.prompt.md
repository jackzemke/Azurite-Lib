## Plan: AAA Knowledge Surfacer Direction

Validate and de-risk a pivot toward deterministic project discovery (Ajera + hardcoded directory map + refresh + key project identifiers) while preserving a retrieval layer for deeper Q&A where AI provides unique value.

**Steps**
1. Define AAA as a two-lane product: Lane A = deterministic discovery (where is the project, what is it, who worked on it), Lane B = retrieval-assisted answers inside documents (*depends on step 1*).
2. Specify Lane A data model: project canonical ID, aliases, office/server path, doc family tags, key identifier summary, Ajera staffing/roles/time windows; add reverse lookup by person (*parallel with step 3*).
3. Define refresh architecture: scheduled index refresh + manual refresh trigger + stale-data indicator shown in UI (*parallel with step 2*).
4. Design user journeys for pilot personas from transcript: IT dedupe/governance, marketing project lookup/on-call agreements, engineering content lookup, and reverse person->projects lookup (*depends on steps 1-3*).
5. Set ranking/fallback rules: deterministic path first for locate queries; retrieval answers require citations + confidence, with graceful not-found response (*depends on step 4*).
6. Add observability and event taxonomy: query intent class, time-to-first-credible-answer, citation click-through, correction/rephrase rate, zero-result and fallback rates (*depends on step 5*).
7. Run closed beta scorecard (existing ~15-user group): compare baseline workflow vs AAA on locate and knowledge-surfacing tasks; decide go/no-go for wider rollout based on threshold metrics (*depends on steps 1-6*).

**Relevant files**
- /home/jack/Azurite-Lib/transcript.txt — sentiment source for user needs and trust barriers.
- /home/jack/Azurite-Lib/.github/copilot-instructions.md — AAA mission, reliability priority, and acceptance constraints.
- /home/jack/Azurite-Lib/app/backend/app/api/query.py — query logging and response behavior patterns to extend for intent/fallback metrics.
- /home/jack/Azurite-Lib/app/backend/app/core/indexer.py — retrieval/ranking behavior if Lane B remains.
- /home/jack/Azurite-Lib/app/backend/config.yaml — top_k/chunking knobs for retrieval quality tuning.

**Verification**
1. Transcript alignment check: each major requirement maps to at least one explicit pilot sentiment line.
2. Deterministic discovery tests: project-description->project-path resolution precision/recall on curated pilot set.
3. Backward lookup tests: person->projects correctness against Ajera records across date ranges.
4. Trust tests: answer includes source path/citations and confidence; not-found path triggers graceful message.
5. Time-savings test: median task time reduction vs manual folder digging.
6. Adoption test: weekly active pilot users and repeat use on real tasks.

**Decisions**
- Included: shift AAA framing from tribal-memory assistant to general knowledge surfacer with deterministic grounding.
- Included: backward compatibility for who-worked-on-what via Ajera.
- Excluded (for initial phase): fully autonomous dedupe/remediation actions; keep to surfacing and flagging.
- Excluded (for initial phase): broad generative drafting workflows beyond retrieval-supported answers.

**Further Considerations**
1. Keep Lane B now vs defer: Recommendation is keep a minimal retrieval lane to satisfy users who want capability beyond Windows search.
2. Governance strictness: Recommendation is soft alerts first (flag potential misfile/duplicate), no auto-moves.
3. Refresh cadence: Recommendation is nightly refresh + on-demand refresh for newly ingested/high-priority projects.
