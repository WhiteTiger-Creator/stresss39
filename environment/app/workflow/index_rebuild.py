#!/usr/bin/env python3
"""Outage window compiler: builds shard disruption windows and the rebuild queue."""  # noqa: EXE001

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_segments(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def dedupe_segments(rows: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for row in rows:
        segment_id = str(row["segment_id"])
        if segment_id not in deduped:
            deduped[segment_id] = dict(row)
    return list(deduped.values())


def merge_windows(rows: list[dict]) -> dict[str, list[dict]]:
    by_shard: dict[str, list[dict]] = {}
    for row in rows:
        shard = str(row.get("shard", ""))
        by_shard.setdefault(shard, []).append(dict(row))

    windows: dict[str, list[dict]] = {}
    for shard, items in by_shard.items():
        items.sort(key=lambda x: x["start_ms"])
        merged: list[dict] = []
        for item in items:
            if not merged:
                merged.append(
                    {
                        "start_ms": item["start_ms"],
                        "end_ms": item["end_ms"],
                        "segment_count": 1,
                        "max_severity": item["severity"],
                    }
                )
                continue
            prev = merged[-1]
            if item["start_ms"] < prev["end_ms"]:
                prev["end_ms"] = max(prev["end_ms"], item["end_ms"])
                prev["segment_count"] += 1
                if item["severity"] == "critical":
                    prev["max_severity"] = "critical"
            else:
                merged.append(
                    {
                        "start_ms": item["start_ms"],
                        "end_ms": item["end_ms"],
                        "segment_count": 1,
                        "max_severity": item["severity"],
                    }
                )
        for block in merged:
            block["duration_ms"] = block["end_ms"] - block["start_ms"] + 1
        windows[shard] = merged
    return windows


def build_queue(windows: dict[str, list[dict]]) -> list[dict]:
    queue: list[dict] = []
    for shard, blocks in windows.items():
        for block in blocks:
            if block["duration_ms"] < 500:
                continue
            priority = "high" if block["max_severity"] == "critical" else "medium"
            queue.append(
                {
                    "window_id": f"{shard}:{block['start_ms']}-{block['end_ms']}",
                    "shard": shard,
                    "start_ms": block["start_ms"],
                    "end_ms": block["end_ms"],
                    "duration_ms": block["duration_ms"],
                    "segment_count": block["segment_count"],
                    "max_severity": block["max_severity"],
                    "priority": priority,
                }
            )
    queue.sort(key=lambda row: (row["priority"], row["duration_ms"], row["shard"]))
    return queue


def build_summary(raw_rows: list[dict], canonical_rows: list[dict], queue: list[dict], windows: dict[str, list[dict]]) -> dict:
    severity_counts = {"critical": 0, "major": 0, "minor": 0}
    for row in canonical_rows:
        sev = str(row.get("severity", ""))
        if sev in severity_counts:
            severity_counts[sev] += 1

    total_disruption = 0
    for blocks in windows.values():
        for block in blocks:
            total_disruption += block["duration_ms"]

    return {
        "schema_version": "rebuild-windows-v1",
        "raw_segment_count": len(raw_rows),
        "unique_segment_ids": len({str(row["segment_id"]) for row in raw_rows}),
        "canonical_segment_count": len(canonical_rows),
        "shard_count": len(windows),
        "severity_counts": severity_counts,
        "total_unplanned_disruption_ms": total_disruption,
        "queued_window_count": len(queue),
        "planned_excluded_count": 0,
    }


def write_outputs(output_dir: Path, summary: dict, windows: dict[str, list[dict]], queue: list[dict]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "rebuild_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (output_dir / "segment_windows.json").write_text(json.dumps(windows, indent=2) + "\n")
    with (output_dir / "rebuild_queue.jsonl").open("w", encoding="utf-8") as handle:
        for row in queue:
            handle.write(json.dumps(row) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/app/data/segments.json")
    parser.add_argument("--output-dir", default="/app/output")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)

    raw_rows = load_segments(input_path)
    canonical_rows = dedupe_segments(raw_rows)
    windows = merge_windows(canonical_rows)
    queue = build_queue(windows)
    summary = build_summary(raw_rows, canonical_rows, queue, windows)
    write_outputs(output_dir, summary, windows, queue)
    print(f"Wrote report to {output_dir}")


if __name__ == "__main__":
    main()
