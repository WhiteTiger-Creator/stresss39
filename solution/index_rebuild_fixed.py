#!/usr/bin/env python3
"""Repaired segment window compiler."""  # noqa: EXE001

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SEVERITY_RANK = {"minor": 1, "major": 2, "critical": 3}
SEVERITY_ORDER = ("critical", "major", "minor")
PRIORITY_ORDER = ("critical", "high", "medium")
MAINTENANCE_PATH = Path("/app/data/maintenance_windows.json")
POLICY_PATH = Path("/app/data/response_policies.json")
EXCEPTIONS_PATH = Path("/app/data/rebuild_exceptions.json")
HANDOFF_PATH = Path("/app/data/handoff_windows.json")
BLACKOUT_PATH = Path("/app/data/blackout_windows.json")
DEGRADE_PATH = Path("/app/data/degrade_windows.json")
SHARD_ALIASES = {
    "authentication": "auth",
    "payments": "billing",
    "search-api": "search",
}
DEFAULT_POLICY = {
    "queue_min_effective_ms": 220,
    "critical_p1_min_ms": 280,
    "critical_threshold_ms": 650,
    "high_threshold_ms": 320,
    "no_overlap_high_duration_ms": 450,
    "critical_count_for_critical": 2,
    "no_overlap_bonus": 4,
    "segment_bonus": 1,
    "severity_weight": {"critical": 5, "major": 3, "minor": 1},
    "score_threshold_critical": 34,
    "score_threshold_high": 18,
    "suppress_penalty_ms": 40,
    "boost_credit_ms": 30,
    "suppress_unit_ms": 50,
    "boost_unit_ms": 50,
    "min_queue_floor_ms": 120,
    "boost_force_critical_ms": 140,
    "boost_high_relief_ms": 40,
    "handoff_penalty_ms": 35,
    "handoff_unit_ms": 60,
    "handoff_force_critical_ms": 59,
    "handoff_high_relief_ms": 50,
    "blackout_penalty_ms": 45,
    "blackout_unit_ms": 70,
    "blackout_force_critical_ms": 200,
    "blackout_high_relief_ms": 55,
    "degrade_penalty_ms": 30,
    "degrade_unit_ms": 80,
    "degrade_force_critical_ms": 170,
    "degrade_high_relief_ms": 45,
}


def load_segments(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def load_maintenance(path: Path = MAINTENANCE_PATH) -> list[dict]:
    return json.loads(path.read_text())


def load_policies(path: Path = POLICY_PATH) -> dict:
    return json.loads(path.read_text())


def load_exceptions(path: Path = EXCEPTIONS_PATH) -> list[dict]:
    return json.loads(path.read_text())


def load_handoffs(path: Path = HANDOFF_PATH) -> list[dict]:
    return json.loads(path.read_text())


def load_blackouts(path: Path = BLACKOUT_PATH) -> list[dict]:
    return json.loads(path.read_text())


def load_degrades(path: Path = DEGRADE_PATH) -> list[dict]:
    return json.loads(path.read_text())


def normalize_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def normalize_shard(value: object) -> str:
    normalized = str(value if value is not None else "").strip().lower()
    return SHARD_ALIASES.get(normalized, normalized)


def normalize_severity(value: object) -> str:
    normalized = str(value if value is not None else "").strip().lower()
    return normalized if normalized in SEVERITY_RANK else "minor"


def normalize_ms(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def normalize_handoff_scope(value: object) -> str:
    scope = str(value if value is not None else "").strip().lower()
    return scope if scope in {"all", "major", "critical"} else ""


def normalize_blackout_scope(value: object) -> str:
    scope = str(value if value is not None else "").strip().lower()
    return scope if scope in {"all", "major", "critical"} else ""


def normalize_degrade_scope(value: object) -> str:
    scope = str(value if value is not None else "").strip().lower()
    return scope if scope in {"all", "major", "critical"} else ""


def _normalize_policy(raw_policy: dict | None) -> dict:
    raw_policy = raw_policy or {}
    normalized = dict(DEFAULT_POLICY)
    for key in (
        "queue_min_effective_ms",
        "critical_p1_min_ms",
        "critical_threshold_ms",
        "high_threshold_ms",
        "no_overlap_high_duration_ms",
        "critical_count_for_critical",
        "no_overlap_bonus",
        "segment_bonus",
        "score_threshold_critical",
        "score_threshold_high",
        "suppress_penalty_ms",
        "boost_credit_ms",
        "suppress_unit_ms",
        "boost_unit_ms",
        "min_queue_floor_ms",
        "boost_force_critical_ms",
        "boost_high_relief_ms",
        "handoff_penalty_ms",
        "handoff_unit_ms",
        "handoff_force_critical_ms",
        "handoff_high_relief_ms",
        "blackout_penalty_ms",
        "blackout_unit_ms",
        "blackout_force_critical_ms",
        "blackout_high_relief_ms",
        "degrade_penalty_ms",
        "degrade_unit_ms",
        "degrade_force_critical_ms",
        "degrade_high_relief_ms",
    ):
        if key in raw_policy:
            normalized[key] = normalize_ms(raw_policy.get(key))
    raw_weights = raw_policy.get("severity_weight", {})
    if isinstance(raw_weights, dict):
        weights = dict(DEFAULT_POLICY["severity_weight"])
        for severity in ("critical", "major", "minor"):
            if severity in raw_weights:
                weights[severity] = normalize_ms(raw_weights.get(severity))
        normalized["severity_weight"] = weights
    return normalized


def _policy_for_shard(shard: str, policy_data: dict) -> tuple[str, dict]:
    default_policy = _normalize_policy(policy_data.get("default", {}))
    overrides = policy_data.get("shard_overrides", {})
    if not isinstance(overrides, dict):
        return "default", default_policy
    raw_override = overrides.get(shard)
    if not isinstance(raw_override, dict):
        return "default", default_policy
    merged = dict(default_policy)
    for key in DEFAULT_POLICY:
        if key != "severity_weight" and key in raw_override:
            merged[key] = normalize_ms(raw_override.get(key))
    merged_weights = dict(default_policy["severity_weight"])
    raw_weights = raw_override.get("severity_weight")
    if isinstance(raw_weights, dict):
        for severity in ("critical", "major", "minor"):
            if severity in raw_weights:
                merged_weights[severity] = normalize_ms(raw_weights.get(severity))
    merged["severity_weight"] = merged_weights
    return shard, merged


def _policy_checksum(policy_data: dict) -> str:
    lines: list[str] = []
    default_policy = _normalize_policy(policy_data.get("default", {}))
    lines.append(
        "default|{queue_min_effective_ms}|{critical_p1_min_ms}|{critical_threshold_ms}|"
        "{high_threshold_ms}|{no_overlap_high_duration_ms}|{critical_count_for_critical}|"
        "{no_overlap_bonus}|{segment_bonus}|{score_threshold_critical}|"
        "{score_threshold_high}|{suppress_penalty_ms}|{boost_credit_ms}|"
        "{suppress_unit_ms}|{boost_unit_ms}|{min_queue_floor_ms}|"
        "{boost_force_critical_ms}|{boost_high_relief_ms}|{handoff_penalty_ms}|"
        "{handoff_unit_ms}|{handoff_force_critical_ms}|{handoff_high_relief_ms}|"
        "{blackout_penalty_ms}|{blackout_unit_ms}|{blackout_force_critical_ms}|"
        "{blackout_high_relief_ms}|{degrade_penalty_ms}|{degrade_unit_ms}|"
        "{degrade_force_critical_ms}|{degrade_high_relief_ms}|"
        "{critical}|{major}|{minor}".format(
            **default_policy, **default_policy["severity_weight"]
        )
    )
    overrides = policy_data.get("shard_overrides", {})
    if isinstance(overrides, dict):
        for shard in sorted(overrides):
            profile, policy = _policy_for_shard(shard, policy_data)
            lines.append(
                "{profile}|{queue_min_effective_ms}|{critical_p1_min_ms}|{critical_threshold_ms}|"
                "{high_threshold_ms}|{no_overlap_high_duration_ms}|{critical_count_for_critical}|"
                "{no_overlap_bonus}|{segment_bonus}|{score_threshold_critical}|"
                "{score_threshold_high}|{suppress_penalty_ms}|{boost_credit_ms}|"
                "{suppress_unit_ms}|{boost_unit_ms}|{min_queue_floor_ms}|"
                "{boost_force_critical_ms}|{boost_high_relief_ms}|{handoff_penalty_ms}|"
                "{handoff_unit_ms}|{handoff_force_critical_ms}|{handoff_high_relief_ms}|"
                "{blackout_penalty_ms}|{blackout_unit_ms}|{blackout_force_critical_ms}|"
                "{blackout_high_relief_ms}|{degrade_penalty_ms}|{degrade_unit_ms}|"
                "{degrade_force_critical_ms}|{degrade_high_relief_ms}|"
                "{critical}|{major}|{minor}".format(
                    profile=profile, **policy, **policy["severity_weight"]
                )
            )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def canonicalize(rows: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for row in rows:
        normalized = dict(row)
        normalized["shard"] = normalize_shard(normalized.get("shard", ""))
        normalized["severity"] = normalize_severity(normalized.get("severity", ""))
        normalized["planned"] = normalize_bool(normalized.get("planned", False))
        normalized["start_ms"] = normalize_ms(normalized.get("start_ms", 0))
        normalized["end_ms"] = normalize_ms(normalized.get("end_ms", 0))
        normalized["end_ms"] = max(normalized["end_ms"], normalized["start_ms"])
        segment_id = str(normalized["segment_id"])
        current = deduped.get(segment_id)
        if current is None:
            deduped[segment_id] = normalized
            continue
        replace = False
        if normalized["end_ms"] > current["end_ms"]:
            replace = True
        elif normalized["end_ms"] == current["end_ms"]:
            next_rank = SEVERITY_RANK[normalized["severity"]]
            current_rank = SEVERITY_RANK[current["severity"]]
            # IDX-2258 reverses this: the LOWER-ranked severity wins a duplicate tie.
            if next_rank < current_rank:
                replace = True
            elif next_rank == current_rank:
                if current["planned"] and not normalized["planned"]:
                    replace = True
                elif current["planned"] == normalized["planned"]:
                    if normalized["start_ms"] > current["start_ms"]:
                        replace = True
                    elif normalized["start_ms"] == current["start_ms"]:  # noqa: SIM102
                        if normalized["shard"] > current["shard"]:
                            replace = True
        if replace:
            deduped[segment_id] = normalized

    return sorted(
        deduped.values(),
        key=lambda row: (row["shard"], row["start_ms"], str(row["segment_id"])),
    )


def overlap_ms(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def _compact_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _window_overlap_spans(
    start_ms: int,
    end_ms: int,
    intervals: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for interval_start, interval_end in intervals:
        span_start = max(start_ms, interval_start)
        span_end = min(end_ms, interval_end)
        if span_end > span_start:
            spans.append((span_start, span_end))
    return spans


def _probe_overlap_ms(
    anchor_ms: int,
    intervals: list[tuple[int, int]],
    lookback_ms: int = 180,
) -> int:
    probe_start = anchor_ms - lookback_ms
    probe_end = anchor_ms + 1
    return sum(
        overlap_ms(probe_start, probe_end, interval_start, interval_end)
        for interval_start, interval_end in intervals
    )


def maintenance_by_shard(maintenance_rows: list[dict]) -> dict[str, list[tuple[int, int]]]:
    by_shard: dict[str, list[tuple[int, int]]] = {}
    for row in maintenance_rows:
        shard = normalize_shard(row.get("shard", ""))
        start = normalize_ms(row.get("start_ms", 0))
        end = normalize_ms(row.get("end_ms", 0))
        if end <= start:
            continue
        by_shard.setdefault(shard, []).append((start, end))
    merged_by_shard: dict[str, list[tuple[int, int]]] = {}
    for shard in by_shard:  # noqa: PLC0206
        merged_by_shard[shard] = _compact_intervals(by_shard[shard])
    return merged_by_shard


def exceptions_by_shard(
    exception_rows: list[dict],
) -> dict[str, dict[str, list[tuple[int, int]]]]:
    by_shard_action: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for row in exception_rows:
        action = str(row.get("action", "")).strip().lower()
        if action not in {"suppress", "boost"}:
            continue
        shard = normalize_shard(row.get("shard", ""))
        start = normalize_ms(row.get("start_ms", 0))
        end = normalize_ms(row.get("end_ms", 0))
        if end <= start:
            continue
        by_shard_action.setdefault((shard, action), []).append((start, end))

    compacted: dict[str, dict[str, list[tuple[int, int]]]] = {}
    for (shard, action), intervals in by_shard_action.items():
        compacted.setdefault(shard, {})[action] = _compact_intervals(intervals)
    return compacted


def handoffs_by_shard_scope(
    handoff_rows: list[dict],
) -> dict[tuple[str, str], list[tuple[int, int]]]:
    by_key: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for row in handoff_rows:
        shard = normalize_shard(row.get("shard", ""))
        scope = normalize_handoff_scope(row.get("severity_scope", ""))
        if not scope:
            continue
        start = normalize_ms(row.get("start_ms", 0))
        end = normalize_ms(row.get("end_ms", 0))
        if end <= start:
            continue
        by_key.setdefault((shard, scope), []).append((start, end))
    return {
        key: _compact_intervals(intervals)
        for key, intervals in by_key.items()
    }


def blackouts_by_shard_scope(
    blackout_rows: list[dict],
) -> dict[tuple[str, str], list[tuple[int, int]]]:
    by_key: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for row in blackout_rows:
        shard = normalize_shard(row.get("shard", ""))
        scope = normalize_blackout_scope(row.get("severity_scope", ""))
        if not scope:
            continue
        start = normalize_ms(row.get("start_ms", 0))
        end = normalize_ms(row.get("end_ms", 0))
        if end <= start:
            continue
        by_key.setdefault((shard, scope), []).append((start, end))
    return {
        key: _compact_intervals(intervals)
        for key, intervals in by_key.items()
    }


def degrades_by_shard_scope(
    degrade_rows: list[dict],
) -> dict[tuple[str, str], list[tuple[int, int]]]:
    by_key: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for row in degrade_rows:
        shard = normalize_shard(row.get("shard", ""))
        scope = normalize_degrade_scope(row.get("severity_scope", ""))
        if not scope:
            continue
        start = normalize_ms(row.get("start_ms", 0))
        end = normalize_ms(row.get("end_ms", 0))
        if end <= start:
            continue
        by_key.setdefault((shard, scope), []).append((start, end))
    return {
        key: _compact_intervals(intervals)
        for key, intervals in by_key.items()
    }


def _intervals_intersection_ms(
    intervals_a: list[tuple[int, int]], intervals_b: list[tuple[int, int]]
) -> int:
    total = 0
    i = 0
    j = 0
    while i < len(intervals_a) and j < len(intervals_b):
        a_start, a_end = intervals_a[i]
        b_start, b_end = intervals_b[j]
        overlap_start = max(a_start, b_start)
        overlap_end = min(a_end, b_end)
        if overlap_end > overlap_start:
            total += overlap_end - overlap_start
        if a_end <= b_end:
            i += 1
        else:
            j += 1
    return total


def merge_windows(
    canonical_rows: list[dict],
    maintenance_rows: list[dict],
    exception_rows: list[dict],
    handoff_rows: list[dict],
    blackout_rows: list[dict],
    degrade_rows: list[dict],
) -> tuple[
    dict[str, list[dict]],
    int,
    dict[str, list[tuple[int, int]]],
    dict[str, dict[str, list[tuple[int, int]]]],
    dict[tuple[str, str], list[tuple[int, int]]],
    dict[tuple[str, str], list[tuple[int, int]]],
    dict[tuple[str, str], list[tuple[int, int]]],
]:
    by_shard: dict[str, list[dict]] = {}
    planned_excluded_count = 0
    for row in canonical_rows:
        if row["planned"]:
            planned_excluded_count += 1
            continue
        by_shard.setdefault(row["shard"], []).append(row)

    maintenance = maintenance_by_shard(maintenance_rows)
    exceptions = exceptions_by_shard(exception_rows)
    handoffs = handoffs_by_shard_scope(handoff_rows)
    blackouts = blackouts_by_shard_scope(blackout_rows)
    degrades = degrades_by_shard_scope(degrade_rows)
    windows: dict[str, list[dict]] = {}
    for shard in sorted(by_shard):
        rows = sorted(by_shard[shard], key=lambda row: row["start_ms"])
        merged: list[dict] = []
        for row in rows:
            if not merged:
                merged.append(
                    {
                        "start_ms": row["start_ms"],
                        "end_ms": row["end_ms"],
                        "segment_count": 1,
                        "critical_segment_count": 1 if row["severity"] == "critical" else 0,
                        "source_segment_ids": [str(row["segment_id"])],
                        "max_severity": row["severity"],
                    }
                )
                continue

            prev = merged[-1]
            if row["start_ms"] <= prev["end_ms"] + 30:
                prev["end_ms"] = max(prev["end_ms"], row["end_ms"])
                prev["segment_count"] += 1
                if row["severity"] == "critical":
                    prev["critical_segment_count"] += 1
                segment_id = str(row["segment_id"])
                if segment_id not in prev["source_segment_ids"]:
                    prev["source_segment_ids"].append(segment_id)
                if SEVERITY_RANK[row["severity"]] > SEVERITY_RANK[prev["max_severity"]]:
                    prev["max_severity"] = row["severity"]
            else:
                merged.append(
                    {
                        "start_ms": row["start_ms"],
                        "end_ms": row["end_ms"],
                        "segment_count": 1,
                        "critical_segment_count": 1 if row["severity"] == "critical" else 0,
                        "source_segment_ids": [str(row["segment_id"])],
                        "max_severity": row["severity"],
                    }
                )

        for block in merged:
            block["duration_ms"] = block["end_ms"] - block["start_ms"]
            block["source_segment_ids"] = sorted(block["source_segment_ids"])
            overlap_spans = _window_overlap_spans(
                block["start_ms"],
                block["end_ms"],
                maintenance.get(shard, []),
            )
            overlap_total = sum(span_end - span_start for span_start, span_end in overlap_spans)
            block["maintenance_overlap_ms"] = overlap_total
            block["maintenance_span_count"] = len(overlap_spans)
            block["billable_duration_ms"] = max(block["duration_ms"] - overlap_total, 0)
            suppress_spans = _window_overlap_spans(
                block["start_ms"],
                block["end_ms"],
                exceptions.get(shard, {}).get("suppress", []),
            )
            boost_spans = _window_overlap_spans(
                block["start_ms"],
                block["end_ms"],
                exceptions.get(shard, {}).get("boost", []),
            )
            suppression_raw_ms = sum(
                span_end - span_start for span_start, span_end in suppress_spans
            )
            boost_overlap_ms = sum(
                span_end - span_start for span_start, span_end in boost_spans
            )
            # When suppress and boost overlaps intersect, intersection time belongs to boost.
            intersection_ms = _intervals_intersection_ms(suppress_spans, boost_spans)
            block["suppression_overlap_ms"] = max(suppression_raw_ms - intersection_ms, 0)
            block["boost_overlap_ms"] = boost_overlap_ms

            handoff_spans = _window_overlap_spans(
                block["start_ms"],
                block["end_ms"],
                handoffs.get((shard, "all"), []),
            )
            handoff_spans.extend(
                _window_overlap_spans(
                    block["start_ms"],
                    block["end_ms"],
                    handoffs.get((shard, block["max_severity"]), []),
                )
            )
            compacted_handoff_spans = _compact_intervals(handoff_spans)
            block["handoff_overlap_ms"] = sum(
                span_end - span_start for span_start, span_end in compacted_handoff_spans
            )
            block["handoff_segment_count"] = len(compacted_handoff_spans)
            block["adjusted_billable_duration_ms"] = max(
                # Handoff overlap subtracted ROUNDED UP per IDX-2252. ceil(x/2)=-(-x//2).
                block["billable_duration_ms"] - (-(-block["handoff_overlap_ms"] // 2)),
                0,
            )
            blackout_spans = _window_overlap_spans(
                block["start_ms"],
                block["end_ms"],
                blackouts.get((shard, "all"), []),
            )
            blackout_spans.extend(
                _window_overlap_spans(
                    block["start_ms"],
                    block["end_ms"],
                    blackouts.get((shard, block["max_severity"]), []),
                )
            )
            compacted_blackout_spans = _compact_intervals(blackout_spans)
            block["blackout_overlap_ms"] = sum(
                span_end - span_start for span_start, span_end in compacted_blackout_spans
            )
            block["blackout_segment_count"] = len(compacted_blackout_spans)
            block["routed_billable_duration_ms"] = max(
                # Blackout overlap subtracted ROUNDED UP per IDX-2254. ceil(x/3)=-(-x//3).
                block["adjusted_billable_duration_ms"] - (-(-block["blackout_overlap_ms"] // 3)),
                0,
            )
            degrade_spans = _window_overlap_spans(
                block["start_ms"],
                block["end_ms"],
                degrades.get((shard, "all"), []),
            )
            degrade_spans.extend(
                _window_overlap_spans(
                    block["start_ms"],
                    block["end_ms"],
                    degrades.get((shard, block["max_severity"]), []),
                )
            )
            compacted_degrade_spans = _compact_intervals(degrade_spans)
            block["degrade_overlap_ms"] = sum(
                span_end - span_start for span_start, span_end in compacted_degrade_spans
            )
            block["degrade_segment_count"] = len(compacted_degrade_spans)
            block["dispatchable_billable_duration_ms"] = max(
                block["routed_billable_duration_ms"] - (block["degrade_overlap_ms"] // 4),
                0,
            )
            block["window_signature"] = hashlib.sha1(
                (
                    f"{shard}|{block['start_ms']}|{block['end_ms']}|"
                    f"{','.join(block['source_segment_ids'])}|{block['max_severity']}|"
                    f"{block['handoff_segment_count']}|{block['blackout_segment_count']}|"
                    f"{block['degrade_segment_count']}"
                ).encode()
            ).hexdigest()[:10]

        previous_end_ms = 0
        previous_debt_out_ms = 0
        prev2_debt_out_ms = 0
        for index, block in enumerate(merged):
            idle_gap_ms = (
                0
                if index == 0
                else max(block["start_ms"] - previous_end_ms, 0)
            )
            debt_in_ms = (
                0
                if index == 0 or idle_gap_ms >= 600
                # Two-lag carry per IDX-2270: the carried debt is the previous window's
                # debt_out plus one third (floored) of the window before it, decayed by a
                # third of the idle gap and capped at the 2500 ledger ceiling.
                else min(
                    max(
                        previous_debt_out_ms
                        + (prev2_debt_out_ms // 3)
                        - (idle_gap_ms // 3),
                        0,
                    ),
                    2500,
                )
            )
            debt_adjusted_dispatchable_ms = (
                # Debt credit ROUNDS UP per IDX-2242. ceil(x/5) = -(-x // 5).
                block["dispatchable_billable_duration_ms"] + (-(-debt_in_ms // 5))
            )
            debt_out_ms = min(
                debt_in_ms
                + block["dispatchable_billable_duration_ms"]
                + (block["maintenance_span_count"] * 12)
                + (block["handoff_segment_count"] * 20)
                + (block["blackout_segment_count"] * 25)
                + (block["degrade_segment_count"] * 15),
                2500,
            )
            block["idle_gap_ms"] = idle_gap_ms
            block["debt_in_ms"] = debt_in_ms
            block["debt_out_ms"] = debt_out_ms
            block["debt_adjusted_dispatchable_ms"] = debt_adjusted_dispatchable_ms
            prev2_debt_out_ms = previous_debt_out_ms
            previous_end_ms = block["end_ms"]
            previous_debt_out_ms = debt_out_ms

        windows[shard] = merged

    return windows, planned_excluded_count, maintenance, exceptions, handoffs, blackouts, degrades


def build_queue(
    windows: dict[str, list[dict]],
    policy_data: dict,
    handoffs: dict[tuple[str, str], list[tuple[int, int]]],
    blackouts: dict[tuple[str, str], list[tuple[int, int]]],
    degrades: dict[tuple[str, str], list[tuple[int, int]]],
) -> list[dict]:
    rows: list[dict] = []
    for shard, blocks in windows.items():
        policy_profile, policy = _policy_for_shard(shard, policy_data)
        for block in blocks:
            suppress_unit = max(policy["suppress_unit_ms"], 1)
            boost_unit = max(policy["boost_unit_ms"], 1)
            handoff_unit = max(policy["handoff_unit_ms"], 1)
            blackout_unit = max(policy["blackout_unit_ms"], 1)
            degrade_unit = max(policy["degrade_unit_ms"], 1)
            suppress_units = (
                (block["suppression_overlap_ms"] + suppress_unit - 1) // suppress_unit
                if block["suppression_overlap_ms"] > 0
                else 0
            )
            # Boost units counted ROUNDED UP per IDX-2256, like the suppression unit.
            boost_units = -(-block["boost_overlap_ms"] // boost_unit)
            effective_queue_min_ms = max(
                policy["queue_min_effective_ms"]
                + suppress_units * policy["suppress_penalty_ms"]
                - boost_units * policy["boost_credit_ms"],
                policy["min_queue_floor_ms"],
            )
            handoff_units = block["handoff_overlap_ms"] // handoff_unit
            adjusted_queue_min_ms = (
                effective_queue_min_ms
                + handoff_units * policy["handoff_penalty_ms"]
            )
            blackout_units = block["blackout_overlap_ms"] // blackout_unit
            routed_queue_min_ms = (
                adjusted_queue_min_ms
                + blackout_units * policy["blackout_penalty_ms"]
            )
            degrade_units = block["degrade_overlap_ms"] // degrade_unit
            dispatch_queue_min_ms = (
                routed_queue_min_ms
                + degrade_units * policy["degrade_penalty_ms"]
            )
            if block["debt_adjusted_dispatchable_ms"] < dispatch_queue_min_ms:
                continue

            all_probe_ms = _probe_overlap_ms(
                block["end_ms"],
                handoffs.get((shard, "all"), []),
            )
            severity_probe_ms = _probe_overlap_ms(
                block["end_ms"],
                handoffs.get((shard, block["max_severity"]), []),
            )
            handoff_pressure_score = (
                (all_probe_ms // 30)
                + (severity_probe_ms // 20)
                + block["handoff_segment_count"]
            )
            blackout_all_probe_ms = _probe_overlap_ms(
                block["end_ms"],
                blackouts.get((shard, "all"), []),
                lookback_ms=240,
            )
            blackout_severity_probe_ms = _probe_overlap_ms(
                block["end_ms"],
                blackouts.get((shard, block["max_severity"]), []),
                lookback_ms=240,
            )
            blackout_pressure_score = (
                (blackout_all_probe_ms // 36)
                # Severity-scoped blackout probe ROUNDS UP per IDX-2246. ceil(x/24)=-(-x//24).
                + (-(-blackout_severity_probe_ms // 24))
                + block["blackout_segment_count"]
            )
            degrade_all_probe_ms = _probe_overlap_ms(
                block["end_ms"],
                degrades.get((shard, "all"), []),
                lookback_ms=210,
            )
            degrade_severity_probe_ms = _probe_overlap_ms(
                block["end_ms"],
                degrades.get((shard, block["max_severity"]), []),
                lookback_ms=210,
            )
            degrade_pressure_score = (
                (degrade_all_probe_ms // 34)
                + (-(-degrade_severity_probe_ms // 23))
                + block["degrade_segment_count"]
            )
            debt_pressure_score = (
                (block["debt_out_ms"] // 80)
                # Debt-in term ROUNDS UP per IDX-2248. ceil(x/120)=-(-x//120).
                + (-(-block["debt_in_ms"] // 120))
            )

            exception_balance_score = int(boost_units - suppress_units)
            severity_weight = policy["severity_weight"].get(block["max_severity"], 0)
            escalation_score = (
                block["debt_adjusted_dispatchable_ms"] // 60
                + block["segment_count"] * 2
                + block["critical_segment_count"] * 3
                + (policy["no_overlap_bonus"] if block["maintenance_overlap_ms"] == 0 else 0)
                + block["maintenance_span_count"] * policy["segment_bonus"]
                + severity_weight
                + exception_balance_score * 2
                + handoff_pressure_score * 2
                + blackout_pressure_score * 2
                + debt_pressure_score * 2
            )
            risk_vector = (
                escalation_score
                + blackout_pressure_score
                + (degrade_pressure_score * 2)
                + debt_pressure_score
            )
            if (
                (
                    block["max_severity"] == "critical"
                    and block["debt_adjusted_dispatchable_ms"] >= policy["critical_p1_min_ms"]
                )
                or block["debt_adjusted_dispatchable_ms"] >= policy["critical_threshold_ms"]
                or block["critical_segment_count"] >= policy["critical_count_for_critical"]
                or escalation_score >= policy["score_threshold_critical"]
                or block["boost_overlap_ms"] >= policy["boost_force_critical_ms"]
                or block["handoff_overlap_ms"] >= policy["handoff_force_critical_ms"]
                or block["blackout_overlap_ms"] >= policy["blackout_force_critical_ms"]
                or block["degrade_overlap_ms"] >= policy["degrade_force_critical_ms"]
                or block["debt_out_ms"] >= 900
                or risk_vector >= (policy["score_threshold_critical"] + 4)
            ):
                priority = "critical"
            elif (
                block["debt_adjusted_dispatchable_ms"] >= policy["high_threshold_ms"]
                or (block["segment_count"] >= 3 and block["max_severity"] in {"major", "critical"})
                or (
                    block["maintenance_overlap_ms"] == 0
                    and block["duration_ms"] >= policy["no_overlap_high_duration_ms"]
                )
                or escalation_score >= policy["score_threshold_high"]
                or (
                    exception_balance_score > 0
                    and block["debt_adjusted_dispatchable_ms"]
                    >= max(policy["high_threshold_ms"] - policy["boost_high_relief_ms"], 0)
                )
                or (
                    handoff_pressure_score > 0
                    and block["debt_adjusted_dispatchable_ms"]
                    >= max(policy["high_threshold_ms"] - policy["handoff_high_relief_ms"], 0)
                )
                or (
                    blackout_pressure_score > 0
                    and block["debt_adjusted_dispatchable_ms"]
                    >= max(policy["high_threshold_ms"] - policy["blackout_high_relief_ms"], 0)
                )
                or (
                    degrade_pressure_score > 0
                    and block["debt_adjusted_dispatchable_ms"]
                    >= max(policy["high_threshold_ms"] - policy["degrade_high_relief_ms"], 0)
                )
                or (
                    debt_pressure_score > 0
                    and block["debt_adjusted_dispatchable_ms"]
                    >= max(policy["high_threshold_ms"] - 35, 0)
                )
                or risk_vector >= (policy["score_threshold_high"] + 2)
            ):
                priority = "high"
            else:
                priority = "medium"
            segment_ids_csv = ",".join(block["source_segment_ids"])
            signature = hashlib.sha1(
                (
                    f"{shard}|{block['start_ms']}|{block['end_ms']}|"
                    f"{segment_ids_csv}|{block['window_signature']}|{block['max_severity']}|"
                    f"{block['maintenance_span_count']}|{policy_profile}|"
                    f"{block['suppression_overlap_ms']}|{block['boost_overlap_ms']}|"
                    f"{effective_queue_min_ms}|{adjusted_queue_min_ms}|"
                    f"{block['handoff_overlap_ms']}|{handoff_pressure_score}|"
                    f"{block['blackout_overlap_ms']}|{blackout_pressure_score}|"
                    f"{routed_queue_min_ms}|{block['degrade_overlap_ms']}|"
                    f"{degrade_pressure_score}|{dispatch_queue_min_ms}|"
                    f"{block['debt_in_ms']}|{block['debt_out_ms']}|"
                    f"{block['debt_adjusted_dispatchable_ms']}|{debt_pressure_score}|"
                    f"{exception_balance_score}"
                ).encode()
            ).hexdigest()[:12]
            queue_digest = hashlib.sha1(
                (
                    f"{shard}:{block['start_ms']}-{block['end_ms']}|{priority}|"
                    f"{escalation_score}|{handoff_pressure_score}|{blackout_pressure_score}|"
                    f"{degrade_pressure_score}|{debt_pressure_score}|{risk_vector}"
                ).encode()
            ).hexdigest()[:10]
            rows.append(
                {
                    "window_id": f"{shard}:{block['start_ms']}-{block['end_ms']}",
                    "shard": shard,
                    "start_ms": block["start_ms"],
                    "end_ms": block["end_ms"],
                    "duration_ms": block["duration_ms"],
                    "maintenance_overlap_ms": block["maintenance_overlap_ms"],
                    "maintenance_span_count": block["maintenance_span_count"],
                    "suppression_overlap_ms": block["suppression_overlap_ms"],
                    "boost_overlap_ms": block["boost_overlap_ms"],
                    "billable_duration_ms": block["billable_duration_ms"],
                    "handoff_overlap_ms": block["handoff_overlap_ms"],
                    "handoff_segment_count": block["handoff_segment_count"],
                    "adjusted_billable_duration_ms": block["adjusted_billable_duration_ms"],
                    "blackout_overlap_ms": block["blackout_overlap_ms"],
                    "blackout_segment_count": block["blackout_segment_count"],
                    "routed_billable_duration_ms": block["routed_billable_duration_ms"],
                    "degrade_overlap_ms": block["degrade_overlap_ms"],
                    "degrade_segment_count": block["degrade_segment_count"],
                    "dispatchable_billable_duration_ms": block["dispatchable_billable_duration_ms"],
                    "debt_in_ms": block["debt_in_ms"],
                    "debt_out_ms": block["debt_out_ms"],
                    "debt_adjusted_dispatchable_ms": block["debt_adjusted_dispatchable_ms"],
                    "segment_count": block["segment_count"],
                    "critical_segment_count": block["critical_segment_count"],
                    "source_segment_ids": block["source_segment_ids"],
                    "max_severity": block["max_severity"],
                    "window_signature": block["window_signature"],
                    "policy_profile": policy_profile,
                    "policy_queue_min_ms": policy["queue_min_effective_ms"],
                    "effective_queue_min_ms": effective_queue_min_ms,
                    "adjusted_queue_min_ms": adjusted_queue_min_ms,
                    "routed_queue_min_ms": routed_queue_min_ms,
                    "dispatch_queue_min_ms": dispatch_queue_min_ms,
                    "exception_balance_score": exception_balance_score,
                    "handoff_pressure_score": handoff_pressure_score,
                    "blackout_pressure_score": blackout_pressure_score,
                    "degrade_pressure_score": degrade_pressure_score,
                    "debt_pressure_score": debt_pressure_score,
                    "escalation_score": escalation_score,
                    "risk_vector": risk_vector,
                    "priority": priority,
                    "segment_signature": signature,
                    "queue_digest": queue_digest,
                }
            )

    rank = {name: idx for idx, name in enumerate(PRIORITY_ORDER)}
    rows.sort(
        key=lambda row: (
            rank[row["priority"]],
            -row["escalation_score"],
            -row["handoff_pressure_score"],
            -row["blackout_pressure_score"],
            -row["degrade_pressure_score"],
            -row["debt_pressure_score"],
            -row["risk_vector"],
            -row["exception_balance_score"],
            -row["dispatchable_billable_duration_ms"],
            -row["routed_billable_duration_ms"],
            -row["adjusted_billable_duration_ms"],
            -row["critical_segment_count"],
            -row["maintenance_span_count"],
            -row["segment_count"],
            row["shard"],
            row["start_ms"],
        )
    )
    return rows


def build_summary(
    raw_rows: list[dict],
    canonical_rows: list[dict],
    maintenance: dict[str, list[tuple[int, int]]],
    exceptions: dict[str, dict[str, list[tuple[int, int]]]],
    handoffs: dict[tuple[str, str], list[tuple[int, int]]],
    blackouts: dict[tuple[str, str], list[tuple[int, int]]],
    degrades: dict[tuple[str, str], list[tuple[int, int]]],
    policy_data: dict,
    windows: dict[str, list[dict]],
    queue: list[dict],
    planned_excluded_count: int,
) -> dict:
    severity_counts = {name: 0 for name in SEVERITY_ORDER}
    for row in canonical_rows:
        severity_counts[row["severity"]] += 1

    total_unplanned = sum(block["duration_ms"] for blocks in windows.values() for block in blocks)
    total_maintenance = sum(
        block["maintenance_overlap_ms"] for blocks in windows.values() for block in blocks
    )
    total_maintenance_span_count = sum(
        block["maintenance_span_count"] for blocks in windows.values() for block in blocks
    )
    total_suppression_overlap = sum(
        block["suppression_overlap_ms"] for blocks in windows.values() for block in blocks
    )
    total_boost_overlap = sum(
        block["boost_overlap_ms"] for blocks in windows.values() for block in blocks
    )
    total_handoff_overlap = sum(
        block["handoff_overlap_ms"] for blocks in windows.values() for block in blocks
    )
    total_handoff_segments = sum(
        block["handoff_segment_count"] for blocks in windows.values() for block in blocks
    )
    total_blackout_overlap = sum(
        block["blackout_overlap_ms"] for blocks in windows.values() for block in blocks
    )
    total_blackout_segments = sum(
        block["blackout_segment_count"] for blocks in windows.values() for block in blocks
    )
    total_degrade_overlap = sum(
        block["degrade_overlap_ms"] for blocks in windows.values() for block in blocks
    )
    total_degrade_segments = sum(
        block["degrade_segment_count"] for blocks in windows.values() for block in blocks
    )
    total_billable = sum(
        block["billable_duration_ms"] for blocks in windows.values() for block in blocks
    )
    total_adjusted_billable = sum(
        block["adjusted_billable_duration_ms"]
        for blocks in windows.values()
        for block in blocks
    )
    total_routed_billable = sum(
        block["routed_billable_duration_ms"]
        for blocks in windows.values()
        for block in blocks
    )
    total_dispatchable_billable = sum(
        block["dispatchable_billable_duration_ms"]
        for blocks in windows.values()
        for block in blocks
    )
    total_debt_adjusted_dispatchable = sum(
        block["debt_adjusted_dispatchable_ms"]
        for blocks in windows.values()
        for block in blocks
    )
    longest_window = max(
        (block["duration_ms"] for blocks in windows.values() for block in blocks),
        default=0,
    )
    critical_window_count = sum(
        1 for blocks in windows.values() for block in blocks if block["max_severity"] == "critical"
    )
    priority_counts = {name: 0 for name in PRIORITY_ORDER}
    for row in queue:
        priority_counts[row["priority"]] += 1
    max_escalation_score = max((row["escalation_score"] for row in queue), default=0)
    max_exception_balance_score = max(
        (row["exception_balance_score"] for row in queue),
        default=0,
    )
    max_handoff_pressure_score = max(
        (row["handoff_pressure_score"] for row in queue),
        default=0,
    )
    max_blackout_pressure_score = max(
        (row["blackout_pressure_score"] for row in queue),
        default=0,
    )
    max_degrade_pressure_score = max(
        (row["degrade_pressure_score"] for row in queue),
        default=0,
    )
    max_debt_pressure_score = max(
        (row["debt_pressure_score"] for row in queue),
        default=0,
    )
    max_risk_vector = max(
        (row["risk_vector"] for row in queue),
        default=0,
    )
    max_debt_out_ms = max(
        (block["debt_out_ms"] for blocks in windows.values() for block in blocks),
        default=0,
    )
    canonical_input_checksum = hashlib.sha256(
        "\n".join(
            (
                f"{row['segment_id']}|{row['shard']}|{row['start_ms']}|"
                f"{row['end_ms']}|{row['severity']}|{1 if row['planned'] else 0}"
            )
            for row in canonical_rows
        ).encode("utf-8")
    ).hexdigest()
    queue_signature_checksum = hashlib.sha256(
        "|".join(row["segment_signature"] for row in queue).encode("utf-8")
    ).hexdigest()
    maintenance_compaction_checksum = hashlib.sha256(
        "\n".join(
            f"{shard}|{start}|{end}"
            for shard in sorted(maintenance)
            for start, end in maintenance[shard]
        ).encode("utf-8")
    ).hexdigest()
    exception_compaction_checksum = hashlib.sha256(
        "\n".join(
            f"{shard}|{action}|{start}|{end}"
            for shard in sorted(exceptions)
            for action in ("boost", "suppress")
            for start, end in exceptions.get(shard, {}).get(action, [])
        ).encode("utf-8")
    ).hexdigest()
    handoff_compaction_checksum = hashlib.sha256(
        "\n".join(
            f"{shard}|{scope}|{start}|{end}"
            for shard, scope in sorted(handoffs)
            for start, end in handoffs[(shard, scope)]
        ).encode("utf-8")
    ).hexdigest()
    blackout_compaction_checksum = hashlib.sha256(
        "\n".join(
            f"{shard}|{scope}|{start}|{end}"
            for shard, scope in sorted(blackouts)
            for start, end in blackouts[(shard, scope)]
        ).encode("utf-8")
    ).hexdigest()
    degrade_compaction_checksum = hashlib.sha256(
        "\n".join(
            f"{shard}|{scope}|{start}|{end}"
            for shard, scope in sorted(degrades)
            for start, end in degrades[(shard, scope)]
        ).encode("utf-8")
    ).hexdigest()
    queue_digest_checksum = hashlib.sha256(
        "|".join(row["queue_digest"] for row in queue).encode("utf-8")
    ).hexdigest()
    policy_checksum = _policy_checksum(policy_data)

    return {
        "schema_version": "rebuild-windows-v1",
        "raw_segment_count": len(raw_rows),
        "unique_segment_ids": len({str(row["segment_id"]) for row in raw_rows}),
        "canonical_segment_count": len(canonical_rows),
        "shard_count": len(windows),
        "severity_counts": severity_counts,
        "total_unplanned_disruption_ms": total_unplanned,
        "total_maintenance_overlap_ms": total_maintenance,
        "total_maintenance_span_count": total_maintenance_span_count,
        "total_suppression_overlap_ms": total_suppression_overlap,
        "total_boost_overlap_ms": total_boost_overlap,
        "total_handoff_overlap_ms": total_handoff_overlap,
        "total_handoff_segment_count": total_handoff_segments,
        "total_blackout_overlap_ms": total_blackout_overlap,
        "total_blackout_segment_count": total_blackout_segments,
        "total_degrade_overlap_ms": total_degrade_overlap,
        "total_degrade_segment_count": total_degrade_segments,
        "total_billable_disruption_ms": total_billable,
        "total_adjusted_billable_disruption_ms": total_adjusted_billable,
        "total_routed_billable_disruption_ms": total_routed_billable,
        "total_dispatchable_billable_disruption_ms": total_dispatchable_billable,
        "total_debt_adjusted_dispatchable_disruption_ms": total_debt_adjusted_dispatchable,
        "longest_window_ms": longest_window,
        "queued_window_count": len(queue),
        "priority_counts": priority_counts,
        "max_escalation_score": max_escalation_score,
        "max_exception_balance_score": max_exception_balance_score,
        "max_handoff_pressure_score": max_handoff_pressure_score,
        "max_blackout_pressure_score": max_blackout_pressure_score,
        "max_degrade_pressure_score": max_degrade_pressure_score,
        "max_debt_pressure_score": max_debt_pressure_score,
        "max_debt_out_ms": max_debt_out_ms,
        "max_risk_vector": max_risk_vector,
        "planned_excluded_count": planned_excluded_count,
        "critical_window_count": critical_window_count,
        "canonical_input_checksum": canonical_input_checksum,
        "queue_signature_checksum": queue_signature_checksum,
        "maintenance_compaction_checksum": maintenance_compaction_checksum,
        "exception_compaction_checksum": exception_compaction_checksum,
        "handoff_compaction_checksum": handoff_compaction_checksum,
        "blackout_compaction_checksum": blackout_compaction_checksum,
        "degrade_compaction_checksum": degrade_compaction_checksum,
        "queue_digest_checksum": queue_digest_checksum,
        "policy_checksum": policy_checksum,
    }


def write_outputs(
    output_dir: Path,
    summary: dict,
    windows: dict[str, list[dict]],
    queue: list[dict],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "rebuild_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (output_dir / "segment_windows.json").write_text(json.dumps(windows, indent=2) + "\n")
    with (output_dir / "rebuild_queue.jsonl").open("w", encoding="utf-8") as handle:
        for row in queue:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def index_rebuild(input_path: Path, output_dir: Path) -> None:
    raw_rows = load_segments(input_path)
    maintenance_rows = load_maintenance()
    exception_rows = load_exceptions()
    handoff_rows = load_handoffs()
    blackout_rows = load_blackouts()
    degrade_rows = load_degrades()
    policy_data = load_policies()
    canonical_rows = canonicalize(raw_rows)
    windows, planned_excluded_count, maintenance, exceptions, handoffs, blackouts, degrades = merge_windows(
        canonical_rows,
        maintenance_rows,
        exception_rows,
        handoff_rows,
        blackout_rows,
        degrade_rows,
    )
    queue = build_queue(windows, policy_data, handoffs, blackouts, degrades)
    summary = build_summary(
        raw_rows=raw_rows,
        canonical_rows=canonical_rows,
        maintenance=maintenance,
        exceptions=exceptions,
        handoffs=handoffs,
        blackouts=blackouts,
        degrades=degrades,
        policy_data=policy_data,
        windows=windows,
        queue=queue,
        planned_excluded_count=planned_excluded_count,
    )
    write_outputs(output_dir=output_dir, summary=summary, windows=windows, queue=queue)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/app/data/segments.json")
    parser.add_argument("--output-dir", default="/app/output")
    args = parser.parse_args()

    index_rebuild(input_path=Path(args.input), output_dir=Path(args.output_dir))
    print(f"Wrote report to {args.output_dir}")


if __name__ == "__main__":
    main()
