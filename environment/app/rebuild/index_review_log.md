# Index-Rebuild Rollout Review Log
Helix Search Platform Ops — change-advisory archive for the failed index-rebuild rollout (2026-Q1 through 2026-Q2).

## Executive Summary
The segment routing compiler has produced unsafe rebuild queues since the February rollout. How the compile is *meant* to behave — normalization, dedupe and its tie-breaks, interval and overlap semantics, domain ordering, policy resolution, attenuation, the rebuild debt ledger, unit and threshold math, scoring, priority and queue ordering — was settled incrementally by the change-advisory board, and those decisions live in the review entries below, not in any single summary. The February draft proposals were revisited during the 2026-05 review cycle and several were reversed; where a draft proposal and a later CAB decision disagree, the later decision governs. `/app/docs/rebuild_contract.json` is the output contract only: it fixes file paths, schemas, exact key sets, identifier payloads and checksum encodings, not how the values are derived.

## February Draft Proposals (2026-02 — partly reversed)
The initial rollout draft circulated a set of compile-behavior proposals through CAB tickets in the 1900 range. Several did not survive review. They are archived in place below and marked superseded; do not implement them as written.

## Change-Review Archive (2025-Q4 through 2026-Q2)
Routine entries are context only. IDX-ticketed proposal and decision quotes embedded in the entries are the authoritative record for compile behavior.

### Review entry 0012 — inventory lane
> **Rollout draft proposal (2026-02-09 - IDX-1903)** Dana: shard labels are stable upstream; preserve their exact casing and do not fold aliases together *(Superseded — reversed in the 2026-05 change review; see the matching decision entry.)*

### Review entry 0024 — auth lane
> **Rollout draft proposal (2026-02-11 - IDX-1907)** Dana: rows whose start_ms or end_ms will not parse as an integer should be dropped from the compile entirely *(Superseded — reversed in the 2026-05 change review; see the matching decision entry.)*

### Review entry 0036 — inventory lane
> **Rollout draft proposal (2026-02-13 - IDX-1911)** Tomas: treat any non-empty `planned` string as true, including `false` and `no` *(Superseded — reversed in the 2026-05 change review; see the matching decision entry.)*

### Review entry 0048 — auth lane
> **Rollout draft proposal (2026-02-16 - IDX-1914)** Tomas: when an segment_id repeats, keep the first row encountered and discard the rest *(Superseded — reversed in the 2026-05 change review; see the matching decision entry.)*

### Review entry 0060 — inventory lane
> **Rollout draft proposal (2026-02-18 - IDX-1917)** Dana: treat all intervals as closed [start_ms, end_ms], so endpoint contact counts as overlap *(Superseded — reversed in the 2026-05 change review; see the matching decision entry.)*

### Review entry 0072 — auth lane
> **Rollout draft proposal (2026-02-20 - IDX-1921)** Tomas: when suppress and boost spans intersect, the intersection stays with suppress — suppression is safety-critical *(Superseded — reversed in the 2026-05 change review; see the matching decision entry.)*
> **Rollout draft proposal (2026-02-21 - IDX-1922)** Dana: for scoped attenuation (handoff, blackout, degrade), clip the all-scope compacted intervals and the matching-severity compacted intervals to the window separately, add the two clipped durations to get overlap_ms, and set segment_count to the total count of clips across both scopes — do not merge the two scopes together *(Superseded — reversed in the 2026-05 change review; see the matching decision entry.)*

### Review entry 0084 — inventory lane
> **Rollout draft proposal (2026-02-23 - IDX-1924)** Dana: subtract the full handoff, blackout and degrade overlaps from billable time with no divisor *(Superseded — reversed in the 2026-05 change review; see the matching decision entry.)*
> **Rollout draft proposal (2026-02-24 - IDX-1925)** Tomas: exception and attenuation unit counts should all round the same way — floor-divide every overlap (suppress, boost, handoff, blackout, degrade) by its unit size so the conversions stay consistent *(Superseded — reversed in the 2026-05 change review; see the matching decision entry.)*

### Review entry 0096 — auth lane
> **Rollout draft proposal (2026-02-25 - IDX-1928)** Tomas: carry rebuild debt forward without any cap; long weekends should accumulate naturally *(Superseded — reversed in the 2026-05 change review; see the matching decision entry.)*
> **Rollout draft proposal (2026-02-25 - IDX-1926)** Dana: rebuild-debt bookkeeping between a shard's windows — decay carried debt by half the idle gap (`debt_in_ms = max(previous.debt_out_ms - idle_gap_ms//2, 0)`), credit `debt_adjusted_dispatchable_ms` with `debt_in_ms//4`, and on carry-out add `handoff_segment_count*15 + blackout_segment_count*20 + degrade_segment_count*10` with no separate maintenance-span credit *(Superseded — reversed in the 2026-05 change review; see the matching decision entry.)*
> **Rollout draft proposal (2026-02-26 - IDX-1930)** Dana: the pressure probes should look back a flat 200ms — probe [end_ms-200, end_ms) for handoff, blackout and degrade alike — and each pressure score is (all_probe_ms // 40) + (severity_probe_ms // 25) + segment_count, uniform across the three domains *(Superseded — reversed in the 2026-05 change review; see the matching decision entry.)*
> **Rollout draft proposal (2026-02-27 - IDX-1932)** Tomas: escalation_score should weight debt_adjusted_dispatchable_ms // 50, segment_count once, critical_segment_count twice, and count each pressure score a single time rather than doubling any of them *(Superseded — reversed in the 2026-05 change review; see the matching decision entry.)*
> **Rollout draft proposal (2026-02-28 - IDX-1934)** Tomas: queue admission thresholds — compute `effective_queue_min_ms = queue_min_effective_ms + suppress_units*suppress_penalty_ms - boost_units*boost_credit_ms` with no floor at that step, add the handoff, blackout and degrade unit penalties in turn, and apply the `min_queue_floor_ms` floor once at the very end to the final `dispatch_queue_min_ms` *(Superseded — reversed in the 2026-05 change review; see the matching decision entry.)*

### Review entry 0100 — inventory lane
> **Change-review decision (2026-04-02 - IDX-2102)** Dana: attenuation divides overlaps as handoff // 3, blackout // 4, degrade // 5. *(Revised — see the 2026-05 change review.)*

### Review entry 0104 — auth lane
> **Change-review decision (2026-04-06 - IDX-2106)** Dana: rebuild debt decays by half the idle gap, caps at 2200, and credits segments at 15/20/10 for handoff/blackout/degrade. *(Revised — see the 2026-05 change review.)*

### Review entry 0108 — inventory lane
> **Change-review decision (2026-04-10 - IDX-2110)** Tomas: every unit conversion rounds down, including suppress units. *(Revised — see the 2026-05 change review.)*

### Review entry 0112 — auth lane
> **Change-review decision (2026-04-14 - IDX-2114)** Tomas: queue admission compares debt-adjusted dispatchability against effective_queue_min_ms alone; no further threshold escalation applies. *(Revised — see the 2026-05 change review.)*

### Review entry 0116 — inventory lane
> **Change-review decision (2026-04-18 - IDX-2118)** Dana: segment windows merge only when the next segment starts at or before the current window's end, with no grace interval. *(Revised — see the 2026-05 change review.)*

### Review entry 0117 — edge lane
> **Change-review decision (2026-04-20 - IDX-2127)** Dana: duplicate segments are grouped by `segment_id` and the kept row is chosen by highest severity rank first, then max end_ms, then max start_ms; the planned flag does not enter the tie-break. *(Revised — see the 2026-05 change review.)*
> **Change-review decision (2026-04-22 - IDX-2131)** Tomas: scoped handoff/blackout/degrade overlap_ms is the SUM of the (shard, all) clipped duration and the (shard, max_severity) clipped duration, and segment_count is the total count of clips across both scopes; the two scopes are not unioned. *(Revised — see the 2026-05 change review.)*
> **Change-review decision (2026-04-24 - IDX-2133)** Tomas: where a suppress span and a boost span intersect, the shared duration counts toward suppression_overlap_ms and is excluded from boost_overlap_ms; suppress wins the intersection. *(Revised — see the 2026-05 change review.)*

### Review entry 0118 — notifications lane
> **Change-review decision (2026-04-26 - IDX-2135)** Dana: pressure divisors — `handoff_pressure_score` = (all_probe_ms // 25) + (severity_probe_ms // 15) + handoff_segment_count; `blackout_pressure_score` uses // 30 and // 20; `degrade_pressure_score` uses // 28 and // 18. *(Revised — see the 2026-05 change review.)*
> **Change-review decision (2026-04-28 - IDX-2137)** Tomas: `escalation_score` = (debt_adjusted_dispatchable_ms // 60) + segment_count*2 + critical_segment_count*3 + severity_weight[max_severity]; the exception-balance, handoff, blackout and debt pressure terms are not part of it. *(Revised — see the 2026-05 change review.)*
> **Change-review decision (2026-04-30 - IDX-2139)** Dana: interval semantics are closed [start_ms, end_ms]; endpoint-only contact contributes 1ms of overlap. *(Revised — see the 2026-05 change review.)*

### Review entry 0119 — ledger lane
> **Change-review decision (2026-05-01 - IDX-2141)** Tomas: `planned` coercion treats any non-empty string as true, including `false` and `no`, and treats a numeric planned value of 2 as true. *(Revised — see the 2026-05 change review.)*
> **Change-review decision (2026-05-01 - IDX-2143)** Dana: `debt_adjusted_dispatchable_ms` = dispatchable_billable_duration_ms + (debt_in_ms // 4). *(Revised — see the 2026-05 change review.)*

### Review entry 0120 — auth lane
> **Change-review decision (2026-05-02 - IDX-2201)** Ilya: canonical shard labels are trimmed and lowercased, then folded through the alias table: `authentication` -> `auth`, `payments` -> `billing`, `search-api` -> `search`. This supersedes IDX-1903.

### Review entry 0812 — debt bench
> **Change-review decision (2026-05-16 - IDX-2242)** Ilya: the debt credit applied to the dispatchable duration was losing every partial step, so a debt carry smaller than one full step credited nothing. That credit now ROUNDS UP: `debt_adjusted_dispatchable_ms = dispatchable_billable_duration_ms + ceil(debt_in_ms / 5)`. In integer arithmetic ceil(x/5) is -(-x // 5). The `// 3` idle decay and the debt_out cap recorded earlier are unchanged and still round down. This revises the floored credit in IDX-2236.

### Review entry 0816 — probe bench
> **Change-review decision (2026-05-17 - IDX-2246)** Dana: the blackout probe takes the same correction and no other: `blackout_pressure_score = (blackout_all_probe_ms // 36) + ceil(blackout_severity_probe_ms / 24) + blackout_segment_count`. The degrade probe was reviewed in the same session and is deliberately left floored on both halves, so the two must not be assumed symmetric.

### Review entry 0818 — debt bench
> **Change-review decision (2026-05-17 - IDX-2248)** Ilya: the debt-in half of the debt pressure score ROUNDS UP while the debt-out half does not: `debt_pressure_score = (debt_out_ms // 80) + ceil(debt_in_ms / 120)`. The 80 debt-out divisor is unchanged.

### Review entry 0821 — canonicalization bench
> **Change-review decision (2026-05-18 - IDX-2258)** Marta: duplicate-severity precedence is REVERSED. Incident reports that duplicate an existing `segment_id` frequently arrive from an automated escalator that inflates severity before a human has confirmed it, so taking the maximum severity was systematically over-escalating the queue. Where two rows share an `segment_id` and tie on `end_ms`, the row with the LOWER severity rank is now the one kept — minor beats major, major beats critical. The remaining keys of the IDX-2207 chain are unchanged and still run in the same order after this one: then prefer `planned == false`, then max `start_ms`, then max `shard` lexicographically. Only the severity comparison direction changes. This reverses that step of IDX-2207.

### Review entry 0822 — routing bench
> **Change-review decision (2026-05-19 - IDX-2252)** Dana: handoff attenuation review found a scoped handoff overlap shorter than one full step was being absorbed without cost, so the handoff subtraction ROUNDS UP: `adjusted_billable_duration_ms = max(billable_duration_ms - ceil(handoff_overlap_ms / 2), 0)`. In integer arithmetic ceil(x/2) is -(-x // 2). This revises the floored form recorded in IDX-2208.

### Review entry 0824 — routing bench
> **Change-review decision (2026-05-19 - IDX-2254)** Dana: the blackout attenuation takes the same correction: `routed_billable_duration_ms = max(adjusted_billable_duration_ms - ceil(blackout_overlap_ms / 3), 0)`. The degrade attenuation that follows it was reviewed in the same session and is deliberately left FLOORED at `degrade_overlap_ms // 4`, so the three attenuation layers must not be assumed to round alike.

### Review entry 0826 — exception bench
> **Change-review decision (2026-05-20 - IDX-2256)** Ilya: boost units are counted the same way suppression units already are — `boost_units = ceil(boost_overlap_ms / boost_unit_ms)` — because a partial boost window was previously granting no credit at all. The handoff, blackout and degrade unit counts keep their floors and are not affected by this entry.

### Review entry 0820 — audit bench
> **Change-review decision (2026-05-18 - IDX-2250)** Ilya: recording the rounding map settled across IDX-2224, IDX-2242, IDX-2246, IDX-2248, IDX-2252, IDX-2254 and IDX-2256 for the avoidance of doubt. Rounding in this compiler is NOT uniform and no divisor's direction may be inferred from any other, including between siblings in the same family: the suppression unit count and the four probe/unit families each carry their own direction, and the degrade and handoff probes stay floored where the blackout probe rounds up. Read each divisor's direction from its own governing decision. *(Revised on the degrade probe point — see IDX-2264.)*

### Review entry 0122 — search lane
> **Change-review decision (2026-04-16 - IDX-2116)** Dana: final queue ordering is priority tier, then dispatchable_billable_duration_ms descending, then shard ascending — a short, coarse key that avoids the pressure-score comparisons. *(Revised — see the 2026-05 change review.)*

### Review entry 0137 — billing lane
> **Change-review decision (2026-05-02 - IDX-2202)** Ilya: allowed severities are critical, major, minor; anything else (or a missing value) becomes `minor`. Severity rank for comparisons is critical > major > minor.

### Review entry 0154 — search lane
> **Change-review decision (2026-05-03 - IDX-2204)** Priya: every millisecond field is coerced with int(str(value).strip()) with fallback 0. Unparseable rows are KEPT with the fallback value — they are not dropped. This supersedes IDX-1907.

### Review entry 0171 — checkout lane
> **Change-review decision (2026-05-03 - IDX-2205)** Priya: `planned` coercion: booleans — preserve the boolean value; strings — strip and lowercase; true, 1, and yes become true; every other string becomes false; other types — use Python bool(value): null and numeric 0 become false; nonzero numbers and other truthy values become true. For the summary, count canonical deduplicated rows whose normalized planned value is true; for example planned=2 is excluded and planned=null is not. This supersedes IDX-1911.

### Review entry 0188 — inventory lane
> **Change-review decision (2026-05-04 - IDX-2207)** Marta: duplicate segments are grouped by `segment_id` and one row is kept per group. Tie-break chain, in order: max end_ms; then max severity rank; then prefer planned == false; then max start_ms; then max shard lexicographically. This supersedes IDX-1914.

### Review entry 0205 — edge lane
> **Change-review decision (2026-05-04 - IDX-2208)** Marta: interval semantics: all source and overlap intervals are half-open [start_ms,end_ms); rows with end_ms <= start_ms are discarded. Overlap is max(0, min(end_a, end_b) - max(start_a, start_b)); endpoint-only contact contributes 0ms. This supersedes IDX-1917.

### Review entry 0222 — notifications lane
> **Change-review decision (2026-05-05 - IDX-2210)** Ilya: window construction uses unplanned segments only; stitch rule: merge if next.start_ms <= current.end_ms + 30 — the 30ms grace interval is final and revises IDX-2118. Maintenance compaction: per shard, merge touching intervals if next.start_ms <= current.end_ms. Exceptions compaction: per (shard, action), merge touching intervals if next.start_ms <= current.end_ms. Scoped compaction: per (shard, severity_scope), merge touching intervals if next.start_ms <= current.end_ms.

### Review entry 0239 — ledger lane
> **Change-review decision (2026-05-05 - IDX-2211)** Ilya: routing domains apply in the fixed order maintenance -> exceptions -> handoff -> blackout -> degrade. Exception actions are limited to suppress and boost; severity scopes are all, major, critical.

### Review entry 0256 — auth lane
> **Change-review decision (2026-05-06 - IDX-2213)** Nadia: scoped overlap for handoff, blackout and degrade: for handoff, blackout, and degrade, select compacted intervals for (shard, all) and (shard, window.max_severity), clip both sets to the segment window, discard zero-duration clips, union and compact the combined clips using the touching merge rule, then set overlap_ms to the union duration and segment_count to the number of combined union segments. Thus an all-scope clip ending at 240 and a matching-severity clip starting at 240 form one segment, not two.

### Review entry 0273 — billing lane
> **Change-review decision (2026-05-06 - IDX-2214)** Nadia: suppress/boost precedence: compute half-open suppress and boost overlap spans, union each action's spans independently, assign all boost union duration to boost_overlap_ms, and subtract the duration of the suppress/boost intersection from suppression_overlap_ms; boost therefore wins intersection time. This supersedes IDX-1921.

### Review entry 0290 — search lane
> **Change-review decision (2026-05-07 - IDX-2216)** Priya: attenuation chain: `billable_duration_ms` = max(duration_ms - maintenance_overlap_ms, 0); `adjusted_billable_duration_ms` = max(billable_duration_ms - (handoff_overlap_ms // 2), 0); `routed_billable_duration_ms` = max(adjusted_billable_duration_ms - (blackout_overlap_ms // 3), 0); `dispatchable_billable_duration_ms` = max(routed_billable_duration_ms - (degrade_overlap_ms // 4), 0). The 2/3/4 divisors are final and revise IDX-2102. This supersedes IDX-1924.

### Review entry 0307 — checkout lane
> **Change-review decision (2026-05-07 - IDX-2217)** Priya: field dependency review: billable_duration_ms depends only on duration_ms and maintenance_overlap_ms suppression_overlap_ms and boost_overlap_ms are tracked separately and do not directly change billable_duration_ms adjusted_billable_duration_ms depends only on billable_duration_ms and handoff_overlap_ms routed_billable_duration_ms depends only on adjusted_billable_duration_ms and blackout_overlap_ms dispatchable_billable_duration_ms depends only on routed_billable_duration_ms and degrade_overlap_ms.

### Review entry 0324 — inventory lane
> **Change-review decision (2026-05-08 - IDX-2219)** Marta: debt ledger: state is independent per normalized shard; process each shard's merged windows in start_ms ascending order after all attenuation fields are finalized. First window: idle_gap_ms=0, debt_in_ms=0. `idle_gap_ms`: for later windows max(current.start_ms-previous.end_ms,0). `debt_in_ms` = max(previous.debt_out_ms-(idle_gap_ms//3),0). `debt_adjusted_dispatchable_ms` = dispatchable_billable_duration_ms + (debt_in_ms//5). `debt_out_ms` = min(debt_in_ms + dispatchable_billable_duration_ms + handoff_segment_count*20 + blackout_segment_count*25 + degrade_segment_count*15, 2500). finalize debt_out_ms for one window before evaluating the next window in the same shard. The one-third idle decay, the 2500 cap, and the 20/25/15 segment credits are final and revise IDX-2106. This supersedes IDX-1928.

### Review entry 0341 — edge lane
> **Change-review decision (2026-05-09 - IDX-2221)** Nadia: approved policy baseline (integers, defaults for every field): `queue_min_effective_ms` = 234; `critical_p1_min_ms` = 280; `critical_threshold_ms` = 650; `high_threshold_ms` = 320; `no_overlap_high_duration_ms` = 450; `critical_count_for_critical` = 2; `no_overlap_bonus` = 4; `segment_bonus` = 1; `score_threshold_critical` = 38; `score_threshold_high` = 24; `suppress_penalty_ms` = 40; `boost_credit_ms` = 30; `suppress_unit_ms` = 50; `boost_unit_ms` = 50; `min_queue_floor_ms` = 120; `boost_force_critical_ms` = 140; `boost_high_relief_ms` = 40; `handoff_penalty_ms` = 35; `handoff_unit_ms` = 60; `handoff_force_critical_ms` = 59; `handoff_high_relief_ms` = 50; `blackout_penalty_ms` = 45; `blackout_unit_ms` = 70; `blackout_force_critical_ms` = 200; `blackout_high_relief_ms` = 55; `degrade_penalty_ms` = 30; `degrade_unit_ms` = 80; `degrade_force_critical_ms` = 170; `degrade_high_relief_ms` = 45. Severity weights default to critical=5, major=3, minor=1.

### Review entry 0358 — notifications lane
> **Change-review decision (2026-05-09 - IDX-2222)** Nadia: policy file resolution: normalize the source default object by starting from policies.defaults and replacing each present integer field after int coercion with fallback 0; merge severity_weight by replacing only present critical/major/minor entries. Overrides: resolve every shard profile to a complete policy: start from the normalized default profile, apply the matching shard_overrides[canonical_shard] fields, and merge a partial severity_weight map by key; omitted fields must remain available and must never raise KeyError. Sparse sources: the default object and every shard override may omit any field; all omitted fields fall back through the complete defaults above.

### Review entry 0375 — ledger lane
> **Change-review decision (2026-05-10 - IDX-2224)** Ilya: unit conversions: `suppress_units` = 0 when suppression_overlap_ms == 0 else ceil(suppression_overlap_ms / max(suppress_unit_ms, 1)); `boost_units` = boost_overlap_ms // max(boost_unit_ms, 1); `handoff_units` = handoff_overlap_ms // max(handoff_unit_ms, 1); `blackout_units` = blackout_overlap_ms // max(blackout_unit_ms, 1); `degrade_units` = degrade_overlap_ms // max(degrade_unit_ms, 1). Note suppress rounds up; every other unit rounds down — this revises the all-floor rule in IDX-2110.

### Review entry 0392 — auth lane
> **Change-review decision (2026-05-10 - IDX-2225)** Ilya: queue admission thresholds build in four steps: `effective_queue_min_ms` = max(queue_min_effective_ms + suppress_units*suppress_penalty_ms - boost_units*boost_credit_ms, min_queue_floor_ms); `adjusted_queue_min_ms` = effective_queue_min_ms + handoff_units*handoff_penalty_ms; `routed_queue_min_ms` = adjusted_queue_min_ms + blackout_units*blackout_penalty_ms; `dispatch_queue_min_ms` = routed_queue_min_ms + degrade_units*degrade_penalty_ms. A window enters the queue only when debt_adjusted_dispatchable_ms >= dispatch_queue_min_ms — the full four-step chain is final and revises IDX-2114.

### Review entry 0409 — billing lane
> **Change-review decision (2026-05-11 - IDX-2227)** Marta: pressure probes and scores: `exception_balance_score` = boost_units - suppress_units. Handoff probe [end_ms-180, end_ms+1), blackout probe [end_ms-240, end_ms+1), degrade probe [end_ms-210, end_ms+1). `handoff_pressure_score` = (all_probe_ms // 30) + (severity_probe_ms // 20) + handoff_segment_count; `blackout_pressure_score` = (all_probe_ms // 36) + (severity_probe_ms // 24) + blackout_segment_count; `degrade_pressure_score` = (all_probe_ms // 34) + (severity_probe_ms // 23) + degrade_segment_count; `debt_pressure_score` = (debt_out_ms // 80) + (debt_in_ms // 120).

### Review entry 0426 — search lane
> **Change-review decision (2026-05-11 - IDX-2228)** Marta: `escalation_score` = (debt_adjusted_dispatchable_ms // 60) + segment_count*2 + critical_segment_count*3 + (maintenance_overlap_ms==0 ? no_overlap_bonus : 0) + maintenance_span_count*segment_bonus + severity_weight[max_severity] + exception_balance_score*2 + handoff_pressure_score*2 + blackout_pressure_score*2 + debt_pressure_score*2. `risk_vector` = escalation_score + blackout_pressure_score + (degrade_pressure_score * 2) + debt_pressure_score.

### Review entry 0443 — checkout lane
> **Change-review decision (2026-05-12 - IDX-2230)** Nadia: a window is priority critical when ANY of the following holds: max_severity == critical and debt_adjusted_dispatchable_ms >= critical_p1_min_ms; OR debt_adjusted_dispatchable_ms >= critical_threshold_ms; OR critical_segment_count >= critical_count_for_critical; OR escalation_score >= score_threshold_critical; OR boost_overlap_ms >= boost_force_critical_ms; OR handoff_overlap_ms >= handoff_force_critical_ms; OR blackout_overlap_ms >= blackout_force_critical_ms; OR degrade_overlap_ms >= degrade_force_critical_ms; OR debt_out_ms >= 900; OR risk_vector >= score_threshold_critical + 4.

### Review entry 0460 — inventory lane
> **Change-review decision (2026-05-12 - IDX-2231)** Nadia: when not critical, a window is priority high when ANY of the following holds: debt_adjusted_dispatchable_ms >= high_threshold_ms; OR segment_count >= 3 and max_severity in {major, critical}; OR maintenance_overlap_ms == 0 and duration_ms >= no_overlap_high_duration_ms; OR escalation_score >= score_threshold_high; OR exception_balance_score > 0 and debt_adjusted_dispatchable_ms >= max(high_threshold_ms - boost_high_relief_ms, 0); OR handoff_pressure_score > 0 and debt_adjusted_dispatchable_ms >= max(high_threshold_ms - handoff_high_relief_ms, 0); OR blackout_pressure_score > 0 and debt_adjusted_dispatchable_ms >= max(high_threshold_ms - blackout_high_relief_ms, 0); OR degrade_pressure_score > 0 and debt_adjusted_dispatchable_ms >= max(high_threshold_ms - degrade_high_relief_ms, 0); OR debt_pressure_score > 0 and debt_adjusted_dispatchable_ms >= max(high_threshold_ms - 35, 0); OR risk_vector >= score_threshold_high + 2. Otherwise priority falls back to medium.

### Review entry 0477 — edge lane
> **Change-review decision (2026-05-13 - IDX-2233)** Ilya: final queue ordering, applied strictly in sequence — this full 16-key order is final and revises the coarse 3-key ordering in IDX-2116: priority (critical > high > medium); then escalation_score desc; then handoff_pressure_score desc; then blackout_pressure_score desc; then degrade_pressure_score desc; then debt_pressure_score desc; then risk_vector desc; then exception_balance_score desc; then dispatchable_billable_duration_ms desc; then routed_billable_duration_ms desc; then adjusted_billable_duration_ms desc; then critical_segment_count desc; then maintenance_span_count desc; then segment_count desc; then shard asc; then start_ms asc.

### Review entry 0491 — checkout lane
> **Change-review decision (2026-05-16 - IDX-2236)** Marta: closing the extended-quiet thread from the 0491 review — proportional decay leaves stale debt on the books when a shard goes quiet for a long stretch, so the ledger now resets outright past a threshold: when `idle_gap_ms` is 600 or greater, `debt_in_ms` is 0 for that window instead of `max(previous.debt_out_ms - (idle_gap_ms // 3), 0)`. Below 600 the one-third decay stands exactly as written. This reset revises IDX-2219; the 2500 cap and the 20/25/15 segment credits there are unaffected.

### Review entry 0493 — edge lane
> **Change-review decision (2026-05-18 - IDX-2251)** Marta: the maintenance-window review closed on this lane with one ledger change — a window that overlapped planned maintenance still leaves residual rebuild debt, and carrying nothing for it understated the next window's position. Each maintenance span now carries a credit alongside the existing ones: `debt_out_ms = min(debt_in_ms + dispatchable_billable_duration_ms + maintenance_span_count*12 + handoff_segment_count*20 + blackout_segment_count*25 + degrade_segment_count*15, 2500)`. The 12-point maintenance credit revises IDX-2219; the 20/25/15 credits, the one-third idle decay and the 2500 cap recorded there are unchanged, as is the extended-idle reset in IDX-2236.

### Review entry 0510 — notifications lane
> **Change-review decision (2026-05-25 - IDX-2240)** Priya: rebuild dashboards retain ninety days of window history; older windows are served from the artifact archive on demand. Dashboard retention is an operational setting and carries no weight in compile output.
> **Change-review decision (2026-05-28 - IDX-2243)** Marta: artifact bundles must record output signatures at export time and again at archive ingest; a mismatch quarantines the bundle for manual review. Evidence handling only; artifact contents are unaffected.

### Review entry 0528 — billing lane
> **Change-review decision (2026-06-03 - IDX-2262)** Dana: quarterly access recertification for the routing path samples shard-to-shard grants at twice the standard rate through year end. Access policy; no compiler impact.
> **Change-review decision (2026-05-30 - IDX-2264)** Marta: degrade probe rounding, and the rounding map of record. The SEVERITY-scoped half of the degrade probe now ROUNDS UP (ceiling) while the all-scoped half keeps its floor: `degrade_pressure_score = (degrade_all_probe_ms // 34) + ceil(degrade_severity_probe_ms / 23) + degrade_segment_count`. In integer arithmetic ceil(x/23) is -(-x // 23). This revises the floored `degrade_severity_probe_ms // 23` written in IDX-2227, which is superseded on this point only: the probe range [end_ms-210, end_ms+1), the divisors 34 and 23, the all-scoped floor and the segment term are unchanged. This entry also supersedes IDX-2250 as the rounding map of record: rounding remains NON-uniform and no divisor's direction may be inferred from any other, but the degrade probe no longer stays floored on both halves — only the handoff probe does. Read each divisor's direction from its own governing decision.

### Review entry 0546 — edge lane
> **Change-review decision (2026-06-06 - IDX-2249)** Ilya: the weekly CAB digest becomes a standing publication with a superseded-by column. Communications practice only; the ticketed decisions remain the sole authority on compile behavior.

### Review entry 0560 — ledger bench
> **Change-review decision (2026-06-10 - IDX-2270)** Marta: extended ledger review of the burst-rebuild shards found that carrying only the immediately preceding window understated pressure when a shard rebuilds in rapid succession, because debt shed one window earlier still reflects live rebuild load that has not actually cleared. The carried debt now blends TWO lags: `debt_in_ms = min(max(previous.debt_out_ms + (window_before_previous.debt_out_ms // 3) - (idle_gap_ms // 3), 0), 2500)`. The second lag is the `debt_out_ms` of the window two positions earlier in the same shard in start_ms order (it is 0 for the first two windows of every shard, so a shard with fewer than three windows is unaffected); it is floored at one third and folded in before the one-third idle decay is subtracted. The 2500 ledger ceiling now also caps `debt_in_ms`. The extended-idle reset in IDX-2236 is unchanged and still takes precedence: when `idle_gap_ms` is 600 or greater, `debt_in_ms` is 0 regardless of either lag. The `ceil(debt_in_ms / 5)` dispatchable credit (IDX-2242), the 2500 `debt_out_ms` cap, and the 12/20/25/15 maintenance/handoff/blackout/degrade segment credits (IDX-2219, IDX-2251) are all unchanged. This revises the single-lag `debt_in_ms` recorded in IDX-2219.
