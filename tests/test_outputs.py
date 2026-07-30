"""Verifier tests for segment compiler hard task."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

OUTPUT_DIR = Path("/app/output")
SUMMARY_PATH = OUTPUT_DIR / "rebuild_summary.json"
WINDOWS_PATH = OUTPUT_DIR / "segment_windows.json"
QUEUE_PATH = OUTPUT_DIR / "rebuild_queue.jsonl"

PIPELINE = Path("/app/workflow/index_rebuild.py")
ORIGINAL_PIPELINE = Path("/app/workflow/.index_rebuild.original")
INPUT_PATH = Path("/app/data/segments.json")
MAINTENANCE_PATH = Path("/app/data/maintenance_windows.json")
POLICY_PATH = Path("/app/data/response_policies.json")
EXCEPTIONS_PATH = Path("/app/data/rebuild_exceptions.json")
HANDOFF_PATH = Path("/app/data/handoff_windows.json")
BLACKOUT_PATH = Path("/app/data/blackout_windows.json")
DEGRADE_PATH = Path("/app/data/degrade_windows.json")
CONTRACT_PATH = Path("/app/docs/rebuild_contract.json")
ALT_INPUT_PATH = Path("/tests/fixtures/alt_segments.json")

FIXTURE = json.loads(Path("/tests/fixtures/expected_outputs.json").read_text())
CONTRACT = json.loads(CONTRACT_PATH.read_text())
BROKEN_PIPELINE_SHA256 = "defdc3b253cd09efc412ab1e4842c3f8b6bfff4751275d156203cdfa946ad82a"

SEVERITY_ORDER = ("critical", "major", "minor")
PRIORITY_ORDER = ("critical", "high", "medium")


def test_checksum_serialization_contract_vectors():
    """The contract's checksum test vectors reproduce under the specified serialization."""
    vectors = CONTRACT["checksums"]["test_vectors"]
    for prefix in (
        "canonical",
        "maintenance",
        "exception",
        "scoped",
        "default_policy",
    ):
        payload = vectors[f"{prefix}_payload"].encode("utf-8")
        assert hashlib.sha256(payload).hexdigest() == vectors[f"{prefix}_sha256"]


def test_identifier_contract_vectors():
    """The contract's identifier test vectors reproduce under the specified payload encoding."""
    vectors = CONTRACT["queue"]["identifiers"]["identifier_test_vectors"]
    assert (
        hashlib.sha1(vectors["window_signature_payload"].encode("utf-8")).hexdigest()[:10]
        == vectors["window_signature"]
    )
    assert len(vectors["window_signature"]) == 10
    assert (
        hashlib.sha1(vectors["segment_signature_payload"].encode("utf-8")).hexdigest()[:12]
        == vectors["segment_signature"]
    )
    assert (
        hashlib.sha1(vectors["queue_digest_payload"].encode("utf-8")).hexdigest()[:10]
        == vectors["queue_digest"]
    )


def _run_pipeline(
    pipeline: Path = PIPELINE,
    input_path: Path = INPUT_PATH,
    output_dir: Path = OUTPUT_DIR,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: PLW1510
        [
            "python3",
            str(pipeline),
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def _stable_json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _stable_jsonl_hash(rows: list[dict]) -> str:
    payload = "\n".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"))
        for row in rows
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reset_output_dir() -> None:
    """Recreate /app/output while preserving its ownership and mode.

    The deployment state (owner/group/mode of /app/output) is itself under
    test, so harness resets must not destroy it.
    """
    if OUTPUT_DIR.exists():
        info = OUTPUT_DIR.stat()
        shutil.rmtree(OUTPUT_DIR)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        os.chown(OUTPUT_DIR, info.st_uid, info.st_gid)
        os.chmod(OUTPUT_DIR, info.st_mode & 0o7777)
    else:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="session", autouse=True)
def _prepare_outputs():
    _reset_output_dir()
    result = _run_pipeline()
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="session")
def summary() -> dict:
    return _load_json(SUMMARY_PATH)


@pytest.fixture(scope="session")
def windows() -> dict[str, list[dict]]:
    return _load_json(WINDOWS_PATH)


@pytest.fixture(scope="session")
def queue_rows() -> list[dict]:
    return _load_jsonl(QUEUE_PATH)


def test_cli_exists():
    """The segment compiler exists at its operational path."""
    assert PIPELINE.exists(), f"pipeline missing at {PIPELINE}"


def test_outputs_exist():
    """A compile run produces all three required output files."""
    for path in (SUMMARY_PATH, WINDOWS_PATH, QUEUE_PATH):
        assert path.exists(), f"missing required output: {path}"


def test_output_dir_contains_exactly_three_files():
    """The output directory contains exactly the three contract files, nothing else."""
    names = {p.name for p in OUTPUT_DIR.iterdir() if p.is_file()}
    assert names == {"rebuild_summary.json", "segment_windows.json", "rebuild_queue.jsonl"}


def test_primary_summary_exact_fixture(summary: dict):
    """rebuild_summary.json from the primary input matches its canonical SHA-256 exactly."""
    assert _stable_json_hash(summary) == FIXTURE["primary_summary_sha256"]


def test_primary_windows_exact_fixture(windows: dict[str, list[dict]]):
    """segment_windows.json from the primary input matches its canonical SHA-256 exactly."""
    assert _stable_json_hash(windows) == FIXTURE["primary_windows_sha256"]


def test_primary_queue_exact_fixture(queue_rows: list[dict]):
    """rebuild_queue.jsonl from the primary input matches its canonical SHA-256 exactly."""
    assert _stable_jsonl_hash(queue_rows) == FIXTURE["primary_queue_sha256"]


def test_alternate_input_exact_fixture():
    """Outputs computed from the unseen alternate input match their canonical SHA-256 hashes."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "alt"
        out.mkdir(parents=True, exist_ok=True)
        result = _run_pipeline(input_path=ALT_INPUT_PATH, output_dir=out)
        assert result.returncode == 0, result.stderr
        assert _stable_json_hash(_load_json(out / "rebuild_summary.json")) == FIXTURE[
            "alternate_summary_sha256"
        ]
        assert _stable_json_hash(_load_json(out / "segment_windows.json")) == FIXTURE[
            "alternate_windows_sha256"
        ]
        assert _stable_jsonl_hash(_load_jsonl(out / "rebuild_queue.jsonl")) == FIXTURE[
            "alternate_queue_sha256"
        ]


def test_summary_schema_and_order(summary: dict):
    """rebuild_summary.json carries exactly the contract keys with required orderings."""
    assert set(summary.keys()) == {
        "schema_version",
        "raw_segment_count",
        "unique_segment_ids",
        "canonical_segment_count",
        "shard_count",
        "severity_counts",
        "total_unplanned_disruption_ms",
        "total_maintenance_overlap_ms",
        "total_maintenance_span_count",
        "total_suppression_overlap_ms",
        "total_boost_overlap_ms",
        "total_handoff_overlap_ms",
        "total_handoff_segment_count",
        "total_blackout_overlap_ms",
        "total_blackout_segment_count",
        "total_degrade_overlap_ms",
        "total_degrade_segment_count",
        "total_billable_disruption_ms",
        "total_adjusted_billable_disruption_ms",
        "total_routed_billable_disruption_ms",
        "total_dispatchable_billable_disruption_ms",
        "total_debt_adjusted_dispatchable_disruption_ms",
        "longest_window_ms",
        "queued_window_count",
        "priority_counts",
        "max_escalation_score",
        "max_exception_balance_score",
        "max_handoff_pressure_score",
        "max_blackout_pressure_score",
        "max_degrade_pressure_score",
        "max_debt_pressure_score",
        "max_debt_out_ms",
        "max_risk_vector",
        "planned_excluded_count",
        "critical_window_count",
        "canonical_input_checksum",
        "queue_signature_checksum",
        "maintenance_compaction_checksum",
        "exception_compaction_checksum",
        "handoff_compaction_checksum",
        "blackout_compaction_checksum",
        "degrade_compaction_checksum",
        "queue_digest_checksum",
        "policy_checksum",
    }
    assert summary["schema_version"] == "rebuild-windows-v1"
    assert list(summary["severity_counts"].keys()) == list(SEVERITY_ORDER)
    assert list(summary["priority_counts"].keys()) == list(PRIORITY_ORDER)
    assert len(summary["canonical_input_checksum"]) == 64
    assert len(summary["queue_signature_checksum"]) == 64
    assert len(summary["maintenance_compaction_checksum"]) == 64
    assert len(summary["exception_compaction_checksum"]) == 64
    assert len(summary["handoff_compaction_checksum"]) == 64
    assert len(summary["blackout_compaction_checksum"]) == 64
    assert len(summary["degrade_compaction_checksum"]) == 64
    assert len(summary["queue_digest_checksum"]) == 64
    assert len(summary["policy_checksum"]) == 64


def test_window_shape_and_sorting(windows: dict[str, list[dict]]):
    """segment_windows.json is a shard-keyed map of sorted window rows with exact keys."""
    expected_keys = {
        "start_ms",
        "end_ms",
        "duration_ms",
        "maintenance_overlap_ms",
        "maintenance_span_count",
        "suppression_overlap_ms",
        "boost_overlap_ms",
        "billable_duration_ms",
        "handoff_overlap_ms",
        "handoff_segment_count",
        "adjusted_billable_duration_ms",
        "blackout_overlap_ms",
        "blackout_segment_count",
        "routed_billable_duration_ms",
        "degrade_overlap_ms",
        "degrade_segment_count",
        "dispatchable_billable_duration_ms",
        "idle_gap_ms",
        "debt_in_ms",
        "debt_out_ms",
        "debt_adjusted_dispatchable_ms",
        "segment_count",
        "critical_segment_count",
        "source_segment_ids",
        "max_severity",
        "window_signature",
    }
    assert list(windows.keys()) == sorted(windows.keys())
    for blocks in windows.values():
        starts = [b["start_ms"] for b in blocks]
        assert starts == sorted(starts)
        for block in blocks:
            assert set(block.keys()) == expected_keys
            assert block["duration_ms"] == block["end_ms"] - block["start_ms"]
            assert block["billable_duration_ms"] == max(
                block["duration_ms"] - block["maintenance_overlap_ms"], 0
            )
            # Handoff attenuation rounds UP per IDX-2252.
            assert block["adjusted_billable_duration_ms"] == max(
                block["billable_duration_ms"] - (-(-block["handoff_overlap_ms"] // 2)),
                0,
            )
            # Blackout attenuation rounds UP per IDX-2254; degrade below stays floored.
            assert block["routed_billable_duration_ms"] == max(
                block["adjusted_billable_duration_ms"] - (-(-block["blackout_overlap_ms"] // 3)),
                0,
            )
            assert block["dispatchable_billable_duration_ms"] == max(
                block["routed_billable_duration_ms"] - (block["degrade_overlap_ms"] // 4),
                0,
            )
            # Debt credit rounds UP per IDX-2242; the layer divisors above stay floored.
            assert block["debt_adjusted_dispatchable_ms"] == (
                block["dispatchable_billable_duration_ms"]
                + (-(-block["debt_in_ms"] // 5))
            )
            assert block["debt_out_ms"] >= block["debt_in_ms"]
            assert block["source_segment_ids"] == sorted(block["source_segment_ids"])
            assert isinstance(block["source_segment_ids"], list)
            assert all(isinstance(value, str) for value in block["source_segment_ids"])


def test_queue_required_fields_and_lengths(queue_rows: list[dict]):
    """Queue rows carry exactly the required fields with valid identifier lengths."""
    expected = {
        "window_id",
        "shard",
        "start_ms",
        "end_ms",
        "duration_ms",
        "maintenance_overlap_ms",
        "maintenance_span_count",
        "suppression_overlap_ms",
        "boost_overlap_ms",
        "billable_duration_ms",
        "handoff_overlap_ms",
        "handoff_segment_count",
        "adjusted_billable_duration_ms",
        "blackout_overlap_ms",
        "blackout_segment_count",
        "routed_billable_duration_ms",
        "degrade_overlap_ms",
        "degrade_segment_count",
        "dispatchable_billable_duration_ms",
        "debt_in_ms",
        "debt_out_ms",
        "debt_adjusted_dispatchable_ms",
        "segment_count",
        "critical_segment_count",
        "source_segment_ids",
        "max_severity",
        "window_signature",
        "policy_profile",
        "policy_queue_min_ms",
        "effective_queue_min_ms",
        "adjusted_queue_min_ms",
        "routed_queue_min_ms",
        "dispatch_queue_min_ms",
        "exception_balance_score",
        "handoff_pressure_score",
        "blackout_pressure_score",
        "degrade_pressure_score",
        "debt_pressure_score",
        "escalation_score",
        "risk_vector",
        "priority",
        "segment_signature",
        "queue_digest",
    }
    for row in queue_rows:
        assert set(row.keys()) == expected
        assert row["priority"] in PRIORITY_ORDER
        assert len(row["window_signature"]) == 10
        assert len(row["segment_signature"]) == 12
        assert len(row["queue_digest"]) == 10


def test_priority_rules_are_enforced(queue_rows: list[dict]):
    """Queue priorities follow the decided critical/high/medium rules."""
    for row in queue_rows:
        assert row["debt_adjusted_dispatchable_ms"] >= row["dispatch_queue_min_ms"]
        assert row["dispatch_queue_min_ms"] >= row["routed_queue_min_ms"]
        assert row["routed_queue_min_ms"] >= row["adjusted_queue_min_ms"]
        assert row["adjusted_queue_min_ms"] >= row["effective_queue_min_ms"]
        assert row["effective_queue_min_ms"] >= 0
        assert row["policy_profile"] in {"default", "auth", "billing", "search"}
        assert isinstance(row["exception_balance_score"], int)
        assert isinstance(row["handoff_pressure_score"], int)
        assert isinstance(row["blackout_pressure_score"], int)
        assert isinstance(row["degrade_pressure_score"], int)
        assert isinstance(row["debt_pressure_score"], int)
        assert isinstance(row["risk_vector"], int)


def test_queue_sorted_with_all_tiebreaks(queue_rows: list[dict]):
    """The queue is ordered by the full decided tie-break sequence."""
    rank = {name: i for i, name in enumerate(PRIORITY_ORDER)}
    sort_keys = [
        (
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
        for row in queue_rows
    ]
    assert sort_keys == sorted(sort_keys)


def test_jsonl_compact_format():
    """rebuild_queue.jsonl uses compact JSON separators."""
    for line in QUEUE_PATH.read_text().splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        assert ": " not in line
        assert json.dumps(parsed, separators=(",", ":")) == line


def test_maintenance_math_consistency(summary: dict, windows: dict[str, list[dict]]):
    """Window arithmetic stays internally consistent across attenuation layers."""
    total_duration = sum(b["duration_ms"] for blocks in windows.values() for b in blocks)
    total_overlap = sum(b["maintenance_overlap_ms"] for blocks in windows.values() for b in blocks)
    total_spans = sum(b["maintenance_span_count"] for blocks in windows.values() for b in blocks)
    total_suppression = sum(b["suppression_overlap_ms"] for blocks in windows.values() for b in blocks)
    total_boost = sum(b["boost_overlap_ms"] for blocks in windows.values() for b in blocks)
    total_handoff = sum(b["handoff_overlap_ms"] for blocks in windows.values() for b in blocks)
    total_handoff_segments = sum(
        b["handoff_segment_count"] for blocks in windows.values() for b in blocks
    )
    total_blackout = sum(b["blackout_overlap_ms"] for blocks in windows.values() for b in blocks)
    total_blackout_segments = sum(
        b["blackout_segment_count"] for blocks in windows.values() for b in blocks
    )
    total_degrade = sum(b["degrade_overlap_ms"] for blocks in windows.values() for b in blocks)
    total_degrade_segments = sum(
        b["degrade_segment_count"] for blocks in windows.values() for b in blocks
    )
    total_billable = sum(b["billable_duration_ms"] for blocks in windows.values() for b in blocks)
    total_adjusted_billable = sum(
        b["adjusted_billable_duration_ms"] for blocks in windows.values() for b in blocks
    )
    total_routed_billable = sum(
        b["routed_billable_duration_ms"] for blocks in windows.values() for b in blocks
    )
    total_dispatchable_billable = sum(
        b["dispatchable_billable_duration_ms"] for blocks in windows.values() for b in blocks
    )
    total_debt_adjusted_dispatchable = sum(
        b["debt_adjusted_dispatchable_ms"] for blocks in windows.values() for b in blocks
    )
    assert summary["total_unplanned_disruption_ms"] == total_duration
    assert summary["total_maintenance_overlap_ms"] == total_overlap
    assert summary["total_maintenance_span_count"] == total_spans
    assert summary["total_suppression_overlap_ms"] == total_suppression
    assert summary["total_boost_overlap_ms"] == total_boost
    assert summary["total_handoff_overlap_ms"] == total_handoff
    assert summary["total_handoff_segment_count"] == total_handoff_segments
    assert summary["total_blackout_overlap_ms"] == total_blackout
    assert summary["total_blackout_segment_count"] == total_blackout_segments
    assert summary["total_degrade_overlap_ms"] == total_degrade
    assert summary["total_degrade_segment_count"] == total_degrade_segments
    assert summary["total_billable_disruption_ms"] == total_billable
    assert summary["total_adjusted_billable_disruption_ms"] == total_adjusted_billable
    assert summary["total_routed_billable_disruption_ms"] == total_routed_billable
    assert summary["total_dispatchable_billable_disruption_ms"] == total_dispatchable_billable
    assert (
        summary["total_debt_adjusted_dispatchable_disruption_ms"]
        == total_debt_adjusted_dispatchable
    )


def test_checksum_fields_match_fixture(summary: dict):
    """Summary checksum fields match canonical values."""
    assert len(summary["canonical_input_checksum"]) == 64
    assert len(summary["queue_signature_checksum"]) == 64
    assert len(summary["maintenance_compaction_checksum"]) == 64
    assert len(summary["exception_compaction_checksum"]) == 64
    assert len(summary["handoff_compaction_checksum"]) == 64
    assert len(summary["blackout_compaction_checksum"]) == 64
    assert len(summary["degrade_compaction_checksum"]) == 64
    assert len(summary["queue_digest_checksum"]) == 64
    assert len(summary["policy_checksum"]) == 64


def test_original_snapshot_preserved():
    """The frozen broken compiler snapshot is untouched."""
    assert ORIGINAL_PIPELINE.exists()
    digest = hashlib.sha256(ORIGINAL_PIPELINE.read_bytes()).hexdigest()
    assert digest == BROKEN_PIPELINE_SHA256


def test_pipeline_does_not_reference_test_artifacts():
    """The repaired compiler never references verifier artifacts."""
    code = PIPELINE.read_text()
    for token in ("/tests", "expected_outputs.json", "test_outputs.py"):
        assert token not in code


def test_pipeline_runtime_does_not_read_tests_tree():
    """Guard runtime file reads under /tests via sitecustomize hook."""
    with tempfile.TemporaryDirectory() as tmp:
        guard_path = Path(tmp) / "sitecustomize.py"
        guard_path.write_text(
            "\n".join(  # noqa: FLY002
                [
                    "import builtins",
                    "import os",
                    "from pathlib import Path",
                    "_orig_open = builtins.open",
                    "_orig_read_text = Path.read_text",
                    "_orig_read_bytes = Path.read_bytes",
                    "def _blocked(value):",
                    "    try:",
                    "        p = Path(value).resolve()",
                    "    except Exception:",
                    "        return False",
                    "    return '/tests' in str(p)",
                    "def _guarded_open(file, *args, **kwargs):",
                    "    if _blocked(file):",
                    "        raise PermissionError(f'blocked test-tree read: {file}')",
                    "    return _orig_open(file, *args, **kwargs)",
                    "def _guarded_read_text(self, *args, **kwargs):",
                    "    if _blocked(self):",
                    "        raise PermissionError(f'blocked test-tree read: {self}')",
                    "    return _orig_read_text(self, *args, **kwargs)",
                    "def _guarded_read_bytes(self, *args, **kwargs):",
                    "    if _blocked(self):",
                    "        raise PermissionError(f'blocked test-tree read: {self}')",
                    "    return _orig_read_bytes(self, *args, **kwargs)",
                    "builtins.open = _guarded_open",
                    "Path.read_text = _guarded_read_text",
                    "Path.read_bytes = _guarded_read_bytes",
                ]
            )
            + "\n"
        )
        with tempfile.TemporaryDirectory() as out_tmp:
            out = Path(out_tmp) / "out"
            out.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{tmp}:{existing}" if existing else tmp
            result = subprocess.run(  # noqa: PLW1510
                [
                    "python3",
                    str(PIPELINE),
                    "--input",
                    str(INPUT_PATH),
                    "--output-dir",
                    str(out),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )
            assert result.returncode == 0, result.stderr


def test_broken_snapshot_is_wrong():
    """The broken snapshot genuinely produces different output."""
    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / "index_rebuild.py"
        out = Path(tmp) / "broken_out"
        shutil.copy(ORIGINAL_PIPELINE, broken)
        result = _run_pipeline(pipeline=broken, output_dir=out)
        assert result.returncode == 0, result.stderr
        broken_summary = _load_json(out / "rebuild_summary.json")
        broken_windows = _load_json(out / "segment_windows.json")
        queue = _load_jsonl(out / "rebuild_queue.jsonl")
        assert _stable_json_hash(broken_summary) != FIXTURE["primary_summary_sha256"]
        assert _stable_json_hash(broken_windows) != FIXTURE["primary_windows_sha256"]
        assert _stable_jsonl_hash(queue) != FIXTURE["primary_queue_sha256"]


def test_pipeline_rerun_idempotent(summary: dict, windows: dict[str, list[dict]], queue_rows: list[dict]):
    """Recompiling the same input reproduces identical output."""
    with tempfile.TemporaryDirectory() as tmp:
        rerun = Path(tmp) / "rerun"
        rerun.mkdir(parents=True, exist_ok=True)
        result = _run_pipeline(output_dir=rerun)
        assert result.returncode == 0, result.stderr
        assert _load_json(rerun / "rebuild_summary.json") == summary
        assert _load_json(rerun / "segment_windows.json") == windows
        assert _load_jsonl(rerun / "rebuild_queue.jsonl") == queue_rows


def test_pipeline_supports_custom_output_dir():
    """The compiler honors a custom output directory."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "custom"
        out.mkdir(parents=True, exist_ok=True)
        result = _run_pipeline(output_dir=out)
        assert result.returncode == 0, result.stderr
        files = {p.name for p in out.iterdir() if p.is_file()}
        assert files == {"rebuild_summary.json", "segment_windows.json", "rebuild_queue.jsonl"}


def test_cli_defaults_work_and_match_explicit_run():
    """Default CLI arguments produce the same output as explicit ones."""
    with tempfile.TemporaryDirectory() as tmp:
        explicit_out = Path(tmp) / "explicit"
        explicit_out.mkdir(parents=True, exist_ok=True)
        explicit = _run_pipeline(input_path=INPUT_PATH, output_dir=explicit_out)
        assert explicit.returncode == 0, explicit.stderr

        _reset_output_dir()

        implicit = subprocess.run(["python3", str(PIPELINE)], capture_output=True, text=True, timeout=60)  # noqa: PLW1510
        assert implicit.returncode == 0, implicit.stderr
        assert _load_json(SUMMARY_PATH) == _load_json(explicit_out / "rebuild_summary.json")
        assert _load_json(WINDOWS_PATH) == _load_json(explicit_out / "segment_windows.json")
        assert _load_jsonl(QUEUE_PATH) == _load_jsonl(explicit_out / "rebuild_queue.jsonl")


def test_maintenance_source_path_affects_output():
    """Maintenance windows are read from their fixed source path at run time.

    Emptying the maintenance source changes the maintenance overlap the summary reports,
    proving the compile re-reads that file rather than carrying overlaps baked in at build.
    """
    original = MAINTENANCE_PATH.read_text()
    try:
        MAINTENANCE_PATH.write_text("[]\n")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "nomaint"
            out.mkdir(parents=True, exist_ok=True)
            result = _run_pipeline(output_dir=out)
            assert result.returncode == 0, result.stderr
            summary = _load_json(out / "rebuild_summary.json")
            assert summary["total_maintenance_overlap_ms"] == 0
            assert summary["total_maintenance_span_count"] == 0
    finally:
        MAINTENANCE_PATH.write_text(original)


def test_policy_source_path_affects_output():
    """Response policies are resolved from their fixed source path at run time.

    Rewriting the policy source changes the compiled queue, proving thresholds come from the
    policy file rather than from values hardcoded in the compile.
    """
    original = POLICY_PATH.read_text()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_a = Path(tmp) / "a"
            out_b = Path(tmp) / "b"
            out_a.mkdir(parents=True, exist_ok=True)
            out_b.mkdir(parents=True, exist_ok=True)
            result_a = _run_pipeline(output_dir=out_a)
            assert result_a.returncode == 0, result_a.stderr
            summary_a = _load_json(out_a / "rebuild_summary.json")
            queue_a = _load_jsonl(out_a / "rebuild_queue.jsonl")

            strict_policy = {
                "default": {
                    "queue_min_effective_ms": 10000,
                    "critical_p1_min_ms": 10000,
                    "critical_threshold_ms": 10000,
                    "high_threshold_ms": 10000,
                    "no_overlap_high_duration_ms": 10000,
                    "critical_count_for_critical": 10,
                    "no_overlap_bonus": 0,
                    "segment_bonus": 0,
                    "severity_weight": {"critical": 1, "major": 1, "minor": 1},
                    "score_threshold_critical": 999,
                    "score_threshold_high": 999
                },
                "shard_overrides": {}
            }
            _write_json(POLICY_PATH, strict_policy)
            result_b = _run_pipeline(output_dir=out_b)
            assert result_b.returncode == 0, result_b.stderr
            summary_b = _load_json(out_b / "rebuild_summary.json")
            queue_b = _load_jsonl(out_b / "rebuild_queue.jsonl")
            assert summary_a["queued_window_count"] > summary_b["queued_window_count"]
            assert len(queue_b) == 0
            assert summary_a["policy_checksum"] != summary_b["policy_checksum"]
            assert len(queue_a) > 0
    finally:
        POLICY_PATH.write_text(original)


def test_sparse_policy_and_override_inherit_complete_defaults():
    """A sparse policy file still yields a complete effective policy.

    Keys absent from both the default block and a shard override fall back to the contract's
    built-in defaults, so a partial policy never produces missing or null thresholds.
    """
    original = POLICY_PATH.read_text()
    try:
        _write_json(
            POLICY_PATH,
            {
                "default": {"suppress_unit_ms": 77},
                "shard_overrides": {"auth": {"queue_min_effective_ms": 205}},
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sparse-policy"
            out.mkdir(parents=True, exist_ok=True)
            result = _run_pipeline(output_dir=out)
            assert result.returncode == 0, result.stderr
            summary = _load_json(out / "rebuild_summary.json")
            queue = _load_jsonl(out / "rebuild_queue.jsonl")
            assert len(summary["policy_checksum"]) == 64
            assert all(
                row["policy_queue_min_ms"] == 205
                for row in queue
                if row["shard"] == "auth"
            )
    finally:
        POLICY_PATH.write_text(original)


def test_exception_source_path_affects_output():
    """Routing exceptions are read from their fixed source path at run time.

    Rewriting the exception source changes the compiled output, proving exceptions are not
    baked into the compile.
    """
    original = EXCEPTIONS_PATH.read_text()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_a = Path(tmp) / "a"
            out_b = Path(tmp) / "b"
            out_a.mkdir(parents=True, exist_ok=True)
            out_b.mkdir(parents=True, exist_ok=True)
            result_a = _run_pipeline(output_dir=out_a)
            assert result_a.returncode == 0, result_a.stderr
            summary_a = _load_json(out_a / "rebuild_summary.json")
            queue_a = _load_jsonl(out_a / "rebuild_queue.jsonl")

            EXCEPTIONS_PATH.write_text("[]\n")
            result_b = _run_pipeline(output_dir=out_b)
            assert result_b.returncode == 0, result_b.stderr
            summary_b = _load_json(out_b / "rebuild_summary.json")
            queue_b = _load_jsonl(out_b / "rebuild_queue.jsonl")
            assert summary_a["exception_compaction_checksum"] != summary_b["exception_compaction_checksum"]
            assert summary_a["total_boost_overlap_ms"] != summary_b["total_boost_overlap_ms"]
            assert summary_a["total_suppression_overlap_ms"] != summary_b["total_suppression_overlap_ms"]
            assert queue_a != queue_b
    finally:
        EXCEPTIONS_PATH.write_text(original)


def test_handoff_source_path_affects_output():
    """Handoff windows are read from their fixed source path at run time.

    Rewriting the handoff source changes the compiled output, proving the attenuation layer
    reads that file rather than carrying its spans internally.
    """
    original = HANDOFF_PATH.read_text()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_a = Path(tmp) / "a"
            out_b = Path(tmp) / "b"
            out_a.mkdir(parents=True, exist_ok=True)
            out_b.mkdir(parents=True, exist_ok=True)
            result_a = _run_pipeline(output_dir=out_a)
            assert result_a.returncode == 0, result_a.stderr
            summary_a = _load_json(out_a / "rebuild_summary.json")
            queue_a = _load_jsonl(out_a / "rebuild_queue.jsonl")

            HANDOFF_PATH.write_text("[]\n")
            result_b = _run_pipeline(output_dir=out_b)
            assert result_b.returncode == 0, result_b.stderr
            summary_b = _load_json(out_b / "rebuild_summary.json")
            queue_b = _load_jsonl(out_b / "rebuild_queue.jsonl")
            assert summary_a["handoff_compaction_checksum"] != summary_b["handoff_compaction_checksum"]
            assert summary_a["total_handoff_overlap_ms"] != summary_b["total_handoff_overlap_ms"]
            assert summary_a["total_adjusted_billable_disruption_ms"] != summary_b["total_adjusted_billable_disruption_ms"]
            assert summary_a != summary_b
            assert isinstance(queue_a, list) and isinstance(queue_b, list)
    finally:
        HANDOFF_PATH.write_text(original)


def test_blackout_source_path_affects_output():
    """Blackout windows are read from their fixed source path at run time.

    Rewriting the blackout source changes the compiled output, proving the attenuation layer
    reads that file rather than carrying its spans internally.
    """
    original = BLACKOUT_PATH.read_text()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_a = Path(tmp) / "a"
            out_b = Path(tmp) / "b"
            out_a.mkdir(parents=True, exist_ok=True)
            out_b.mkdir(parents=True, exist_ok=True)
            result_a = _run_pipeline(output_dir=out_a)
            assert result_a.returncode == 0, result_a.stderr
            summary_a = _load_json(out_a / "rebuild_summary.json")
            queue_a = _load_jsonl(out_a / "rebuild_queue.jsonl")

            BLACKOUT_PATH.write_text("[]\n")
            result_b = _run_pipeline(output_dir=out_b)
            assert result_b.returncode == 0, result_b.stderr
            summary_b = _load_json(out_b / "rebuild_summary.json")
            queue_b = _load_jsonl(out_b / "rebuild_queue.jsonl")
            assert summary_a["blackout_compaction_checksum"] != summary_b["blackout_compaction_checksum"]
            assert summary_a["total_blackout_overlap_ms"] != summary_b["total_blackout_overlap_ms"]
            assert (
                summary_a["total_routed_billable_disruption_ms"]
                != summary_b["total_routed_billable_disruption_ms"]
            )
            assert summary_a != summary_b
            assert isinstance(queue_a, list) and isinstance(queue_b, list)
    finally:
        BLACKOUT_PATH.write_text(original)


def test_degrade_source_path_affects_output():
    """Degrade windows are read from their fixed source path at run time.

    Rewriting the degrade source changes the compiled output, proving the attenuation layer
    reads that file rather than carrying its spans internally.
    """
    original = DEGRADE_PATH.read_text()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_a = Path(tmp) / "a"
            out_b = Path(tmp) / "b"
            out_a.mkdir(parents=True, exist_ok=True)
            out_b.mkdir(parents=True, exist_ok=True)
            result_a = _run_pipeline(output_dir=out_a)
            assert result_a.returncode == 0, result_a.stderr
            summary_a = _load_json(out_a / "rebuild_summary.json")
            queue_a = _load_jsonl(out_a / "rebuild_queue.jsonl")

            DEGRADE_PATH.write_text("[]\n")
            result_b = _run_pipeline(output_dir=out_b)
            assert result_b.returncode == 0, result_b.stderr
            summary_b = _load_json(out_b / "rebuild_summary.json")
            queue_b = _load_jsonl(out_b / "rebuild_queue.jsonl")
            assert summary_a["degrade_compaction_checksum"] != summary_b["degrade_compaction_checksum"]
            assert summary_a["total_degrade_overlap_ms"] != summary_b["total_degrade_overlap_ms"]
            assert (
                summary_a["total_dispatchable_billable_disruption_ms"]
                != summary_b["total_dispatchable_billable_disruption_ms"]
            )
            assert summary_a != summary_b
            assert isinstance(queue_a, list) and isinstance(queue_b, list)
    finally:
        DEGRADE_PATH.write_text(original)


def test_maintenance_compaction_and_span_count_exercised():
    """Overlapping and touching maintenance windows are compacted before measurement.

    Windows for the same shard merge into unioned spans, so the measured overlap and the
    reported span count follow the merged spans rather than the raw row count.
    """
    original = MAINTENANCE_PATH.read_text()
    try:
        maintenance_rows = [
            {"shard": "billing", "start_ms": 100, "end_ms": 150},
            {"shard": "billing", "start_ms": 140, "end_ms": 170},
            {"shard": "payments", "start_ms": 170, "end_ms": 190},
            {"shard": "billing", "start_ms": 210, "end_ms": 240},
        ]
        _write_json(MAINTENANCE_PATH, maintenance_rows)

        rows = [
            {
                "segment_id": "m1",
                "shard": "billing",
                "start_ms": 50,
                "end_ms": 300,
                "severity": "major",
                "planned": False,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "in.json"
            out = Path(tmp) / "out"
            _write_json(in_path, rows)
            out.mkdir(parents=True, exist_ok=True)
            result = _run_pipeline(input_path=in_path, output_dir=out)
            assert result.returncode == 0, result.stderr
            windows = _load_json(out / "segment_windows.json")
            block = windows["billing"][0]
            assert block["maintenance_overlap_ms"] == 120
            assert block["maintenance_span_count"] == 2
    finally:
        MAINTENANCE_PATH.write_text(original)


def test_dedupe_tie_break_chain_exercised():
    """Duplicate segment_id rows collapse to one row via the full governed tie-break chain.

    The surviving row is selected by the ordered tie-break rules, not by input order, so
    reordering the duplicates cannot change which row wins.
    """
    original = MAINTENANCE_PATH.read_text()
    try:
        MAINTENANCE_PATH.write_text("[]\n")
        rows = [
            {"segment_id": "d1", "shard": "payments", "start_ms": 100, "end_ms": 200, "severity": "major", "planned": True},
            {"segment_id": "d1", "shard": "billing", "start_ms": 120, "end_ms": 200, "severity": "major", "planned": False},
            {"segment_id": "d1", "shard": "auth", "start_ms": 130, "end_ms": 200, "severity": "critical", "planned": False},
            {"segment_id": "d1", "shard": "billing", "start_ms": 130, "end_ms": 200, "severity": "critical", "planned": False},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "in.json"
            out = Path(tmp) / "out"
            _write_json(in_path, rows)
            out.mkdir(parents=True, exist_ok=True)
            result = _run_pipeline(input_path=in_path, output_dir=out)
            assert result.returncode == 0, result.stderr
            windows = _load_json(out / "segment_windows.json")
            assert list(windows.keys()) == ["billing"]
            block = windows["billing"][0]
            # IDX-2258 reverses the severity step: the LOWER rank wins the tie, so the
            # two `major` rows survive the critical ones, and `planned == false` then
            # picks billing/120 over payments/100.
            assert block["start_ms"] == 120
            assert block["max_severity"] == "major"
            assert block["source_segment_ids"] == ["d1"]
    finally:
        MAINTENANCE_PATH.write_text(original)


def test_planned_coercion_aliases_and_unknown_severity_exercised():
    """Canonicalization coerces planned aliases and normalizes unknown severities.

    String forms of the planned flag are parsed to booleans and a severity outside the known
    set falls back to its governed default, so raw input spellings never reach the aggregates.
    """
    original = MAINTENANCE_PATH.read_text()
    try:
        MAINTENANCE_PATH.write_text("[]\n")
        rows = [
            {"segment_id": "p1", "shard": "authentication", "start_ms": 10, "end_ms": 300, "severity": "major", "planned": "no"},
            {"segment_id": "p2", "shard": "search-api", "start_ms": 20, "end_ms": 260, "severity": "weird", "planned": "yes"},
            {"segment_id": "p3", "shard": "payments", "start_ms": 30, "end_ms": 280, "severity": "critical", "planned": 2},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "in.json"
            out = Path(tmp) / "out"
            _write_json(in_path, rows)
            out.mkdir(parents=True, exist_ok=True)
            result = _run_pipeline(input_path=in_path, output_dir=out)
            assert result.returncode == 0, result.stderr
            summary = _load_json(out / "rebuild_summary.json")
            windows = _load_json(out / "segment_windows.json")
            assert summary["planned_excluded_count"] == 2
            assert summary["severity_counts"] == {"critical": 1, "major": 1, "minor": 1}
            assert list(windows.keys()) == ["auth"]
    finally:
        MAINTENANCE_PATH.write_text(original)


def test_exception_compaction_and_balance_exercised():
    """Routing exceptions compact per normalized shard and net out by action.

    Boost and suppress spans merge before use and are balanced under the governed precedence
    rather than being counted independently.
    """
    original_maint = MAINTENANCE_PATH.read_text()
    original_ex = EXCEPTIONS_PATH.read_text()
    try:
        MAINTENANCE_PATH.write_text("[]\n")
        _write_json(
            EXCEPTIONS_PATH,
            [
                {"shard": "search-api", "start_ms": 100, "end_ms": 180, "action": "boost"},
                {"shard": "search", "start_ms": 170, "end_ms": 220, "action": "boost"},
                {"shard": "search", "start_ms": 210, "end_ms": 260, "action": "suppress"},
                {"shard": "search", "start_ms": 260, "end_ms": 280, "action": "suppress"},
                {"shard": "search", "start_ms": 280, "end_ms": 280, "action": "boost"},
            ],
        )
        rows = [
            {
                "segment_id": "e1",
                "shard": "search",
                "start_ms": 90,
                "end_ms": 360,
                "severity": "major",
                "planned": False,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "in.json"
            out = Path(tmp) / "out"
            _write_json(in_path, rows)
            out.mkdir(parents=True, exist_ok=True)
            result = _run_pipeline(input_path=in_path, output_dir=out)
            assert result.returncode == 0, result.stderr
            windows = _load_json(out / "segment_windows.json")
            queue = _load_jsonl(out / "rebuild_queue.jsonl")
            block = windows["search"][0]
            assert block["boost_overlap_ms"] == 120
            assert block["suppression_overlap_ms"] == 60
            assert queue[0]["effective_queue_min_ms"] == 220
            assert queue[0]["exception_balance_score"] == 1
    finally:
        MAINTENANCE_PATH.write_text(original_maint)
        EXCEPTIONS_PATH.write_text(original_ex)


def test_handoff_compaction_and_scope_exercised():
    """Handoff windows compact per (shard, severity scope) and match only in-scope segments.

    A window attenuates an segment only when its severity scope covers that segment, and the
    overlap is measured against the merged in-scope spans.
    """
    original_maint = MAINTENANCE_PATH.read_text()
    original_ex = EXCEPTIONS_PATH.read_text()
    original_handoff = HANDOFF_PATH.read_text()
    try:
        MAINTENANCE_PATH.write_text("[]\n")
        EXCEPTIONS_PATH.write_text("[]\n")
        _write_json(
            HANDOFF_PATH,
            [
                {"shard": "search-api", "severity_scope": "all", "start_ms": 120, "end_ms": 200},
                {"shard": "search", "severity_scope": "all", "start_ms": 200, "end_ms": 240},
                {"shard": "search", "severity_scope": "critical", "start_ms": 240, "end_ms": 320},
                {"shard": "search", "severity_scope": "debug", "start_ms": 0, "end_ms": 1},
            ],
        )
        rows = [
            {
                "segment_id": "h1",
                "shard": "search",
                "start_ms": 100,
                "end_ms": 400,
                "severity": "critical",
                "planned": False,
            },
            {
                "segment_id": "h2",
                "shard": "search",
                "start_ms": 500,
                "end_ms": 760,
                "severity": "major",
                "planned": False,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "in.json"
            out = Path(tmp) / "out"
            _write_json(in_path, rows)
            out.mkdir(parents=True, exist_ok=True)
            result = _run_pipeline(input_path=in_path, output_dir=out)
            assert result.returncode == 0, result.stderr
            windows = _load_json(out / "segment_windows.json")
            queue = _load_jsonl(out / "rebuild_queue.jsonl")
            summary = _load_json(out / "rebuild_summary.json")
            first = windows["search"][0]
            second = windows["search"][1]
            assert first["handoff_overlap_ms"] == 200
            assert first["handoff_segment_count"] == 1
            assert first["adjusted_billable_duration_ms"] == 200
            assert second["handoff_overlap_ms"] == 0
            assert summary["total_handoff_overlap_ms"] == 200
            assert summary["total_handoff_segment_count"] == 1
            assert all("queue_digest" in row for row in queue)
    finally:
        MAINTENANCE_PATH.write_text(original_maint)
        EXCEPTIONS_PATH.write_text(original_ex)
        HANDOFF_PATH.write_text(original_handoff)


def test_blackout_compaction_and_scope_exercised():
    """Blackout windows compact per (shard, severity scope) and match only in-scope segments.

    Overlap is measured against the merged in-scope spans, so out-of-scope windows contribute
    nothing and duplicate spans are not double-counted.
    """
    original_maint = MAINTENANCE_PATH.read_text()
    original_ex = EXCEPTIONS_PATH.read_text()
    original_handoff = HANDOFF_PATH.read_text()
    original_blackout = BLACKOUT_PATH.read_text()
    try:
        MAINTENANCE_PATH.write_text("[]\n")
        EXCEPTIONS_PATH.write_text("[]\n")
        HANDOFF_PATH.write_text("[]\n")
        _write_json(
            BLACKOUT_PATH,
            [
                {"shard": "search-api", "severity_scope": "all", "start_ms": 120, "end_ms": 210},
                {"shard": "search", "severity_scope": "all", "start_ms": 210, "end_ms": 250},
                {"shard": "search", "severity_scope": "critical", "start_ms": 260, "end_ms": 320},
                {"shard": "search", "severity_scope": "debug", "start_ms": 0, "end_ms": 1},
            ],
        )
        rows = [
            {
                "segment_id": "k1",
                "shard": "search",
                "start_ms": 100,
                "end_ms": 400,
                "severity": "critical",
                "planned": False,
            },
            {
                "segment_id": "k2",
                "shard": "search",
                "start_ms": 500,
                "end_ms": 760,
                "severity": "major",
                "planned": False,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "in.json"
            out = Path(tmp) / "out"
            _write_json(in_path, rows)
            out.mkdir(parents=True, exist_ok=True)
            result = _run_pipeline(input_path=in_path, output_dir=out)
            assert result.returncode == 0, result.stderr
            windows = _load_json(out / "segment_windows.json")
            queue = _load_jsonl(out / "rebuild_queue.jsonl")
            summary = _load_json(out / "rebuild_summary.json")
            first = windows["search"][0]
            second = windows["search"][1]
            assert first["blackout_overlap_ms"] == 190
            assert first["blackout_segment_count"] == 2
            # adjusted - ceil(190/3) = adjusted - 64 per IDX-2254 (floor gave 237)
            assert first["routed_billable_duration_ms"] == 236
            assert second["blackout_overlap_ms"] == 0
            assert summary["total_blackout_overlap_ms"] == 190
            assert summary["total_blackout_segment_count"] == 2
            assert all("blackout_pressure_score" in row for row in queue)
    finally:
        MAINTENANCE_PATH.write_text(original_maint)
        EXCEPTIONS_PATH.write_text(original_ex)
        HANDOFF_PATH.write_text(original_handoff)
        BLACKOUT_PATH.write_text(original_blackout)


def test_degrade_compaction_and_scope_exercised():
    """Degrade windows compact per (shard, severity scope) and match only in-scope segments.

    Overlap is measured against the merged in-scope spans, so out-of-scope windows contribute
    nothing and duplicate spans are not double-counted.
    """
    original_maint = MAINTENANCE_PATH.read_text()
    original_ex = EXCEPTIONS_PATH.read_text()
    original_handoff = HANDOFF_PATH.read_text()
    original_blackout = BLACKOUT_PATH.read_text()
    original_degrade = DEGRADE_PATH.read_text()
    try:
        MAINTENANCE_PATH.write_text("[]\n")
        EXCEPTIONS_PATH.write_text("[]\n")
        HANDOFF_PATH.write_text("[]\n")
        BLACKOUT_PATH.write_text("[]\n")
        _write_json(
            DEGRADE_PATH,
            [
                {"shard": "search-api", "severity_scope": "all", "start_ms": 120, "end_ms": 220},
                {"shard": "search", "severity_scope": "all", "start_ms": 220, "end_ms": 260},
                {"shard": "search", "severity_scope": "critical", "start_ms": 270, "end_ms": 335},
                {"shard": "search", "severity_scope": "debug", "start_ms": 0, "end_ms": 1},
            ],
        )
        rows = [
            {
                "segment_id": "g1",
                "shard": "search",
                "start_ms": 100,
                "end_ms": 420,
                "severity": "critical",
                "planned": False,
            },
            {
                "segment_id": "g2",
                "shard": "search",
                "start_ms": 500,
                "end_ms": 760,
                "severity": "major",
                "planned": False,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "in.json"
            out = Path(tmp) / "out"
            _write_json(in_path, rows)
            out.mkdir(parents=True, exist_ok=True)
            result = _run_pipeline(input_path=in_path, output_dir=out)
            assert result.returncode == 0, result.stderr
            windows = _load_json(out / "segment_windows.json")
            queue = _load_jsonl(out / "rebuild_queue.jsonl")
            summary = _load_json(out / "rebuild_summary.json")
            first = windows["search"][0]
            second = windows["search"][1]
            assert first["degrade_overlap_ms"] == 205
            assert first["degrade_segment_count"] == 2
            assert first["dispatchable_billable_duration_ms"] == 269
            assert second["degrade_overlap_ms"] == 0
            assert summary["total_degrade_overlap_ms"] == 205
            assert summary["total_degrade_segment_count"] == 2
            assert all("degrade_pressure_score" in row for row in queue)
    finally:
        MAINTENANCE_PATH.write_text(original_maint)
        EXCEPTIONS_PATH.write_text(original_ex)
        HANDOFF_PATH.write_text(original_handoff)
        BLACKOUT_PATH.write_text(original_blackout)
        DEGRADE_PATH.write_text(original_degrade)


def test_debt_ledger_propagates_and_decays_between_windows():
    """The per-shard debt ledger carries between consecutive windows and decays across idle gaps.

    A window's ledger-adjusted duration therefore depends on the windows preceding it in the
    same shard, not on that window in isolation.
    """
    original_maint = MAINTENANCE_PATH.read_text()
    original_ex = EXCEPTIONS_PATH.read_text()
    original_handoff = HANDOFF_PATH.read_text()
    original_blackout = BLACKOUT_PATH.read_text()
    original_degrade = DEGRADE_PATH.read_text()
    try:
        MAINTENANCE_PATH.write_text("[]\n")
        EXCEPTIONS_PATH.write_text("[]\n")
        HANDOFF_PATH.write_text("[]\n")
        BLACKOUT_PATH.write_text("[]\n")
        DEGRADE_PATH.write_text("[]\n")
        rows = [
            {
                "segment_id": "d-ledger-1",
                "shard": "auth",
                "start_ms": 0,
                "end_ms": 400,
                "severity": "major",
                "planned": False,
            },
            {
                "segment_id": "d-ledger-2",
                "shard": "auth",
                "start_ms": 470,
                "end_ms": 760,
                "severity": "major",
                "planned": False,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "in.json"
            out = Path(tmp) / "out"
            _write_json(in_path, rows)
            out.mkdir(parents=True, exist_ok=True)
            result = _run_pipeline(input_path=in_path, output_dir=out)
            assert result.returncode == 0, result.stderr
            windows = _load_json(out / "segment_windows.json")
            queue = _load_jsonl(out / "rebuild_queue.jsonl")
            summary = _load_json(out / "rebuild_summary.json")
            assert list(windows.keys()) == ["auth"]
            first, second = windows["auth"]
            assert first["idle_gap_ms"] == 0
            assert first["debt_in_ms"] == 0
            assert first["debt_out_ms"] == 400
            assert first["debt_adjusted_dispatchable_ms"] == 400
            assert second["idle_gap_ms"] == 70
            assert second["debt_in_ms"] == 377
            assert second["debt_out_ms"] == 667
            # 290 + ceil(377/5) = 290 + 76; the floored credit would have given 365
            assert second["debt_adjusted_dispatchable_ms"] == 366
            queue_by_start = {row["start_ms"]: row for row in queue}
            assert queue_by_start[0]["debt_pressure_score"] == 5
            # debt_out//80 + ceil(debt_in/120) = 8 + 4 per IDX-2248 (floored debt_in gave 11)
            assert queue_by_start[470]["debt_pressure_score"] == 12
            assert summary["max_debt_out_ms"] == 667
            # 400 + 366; the second window gained 1ms from the ceilinged debt credit
            assert summary["total_debt_adjusted_dispatchable_disruption_ms"] == 766
    finally:
        MAINTENANCE_PATH.write_text(original_maint)
        EXCEPTIONS_PATH.write_text(original_ex)
        HANDOFF_PATH.write_text(original_handoff)
        BLACKOUT_PATH.write_text(original_blackout)
        DEGRADE_PATH.write_text(original_degrade)


def test_debt_ledger_resets_after_extended_idle_gap():
    """An idle gap at or beyond the reset threshold zeroes debt_in_ms instead of decaying it."""
    original_maint = MAINTENANCE_PATH.read_text()
    original_ex = EXCEPTIONS_PATH.read_text()
    original_handoff = HANDOFF_PATH.read_text()
    original_blackout = BLACKOUT_PATH.read_text()
    original_degrade = DEGRADE_PATH.read_text()
    try:
        MAINTENANCE_PATH.write_text("[]\n")
        EXCEPTIONS_PATH.write_text("[]\n")
        HANDOFF_PATH.write_text("[]\n")
        BLACKOUT_PATH.write_text("[]\n")
        DEGRADE_PATH.write_text("[]\n")
        rows = [
            {
                "segment_id": "d-reset-1",
                "shard": "auth",
                "start_ms": 0,
                "end_ms": 400,
                "severity": "major",
                "planned": False,
            },
            {
                "segment_id": "d-reset-2",
                "shard": "auth",
                "start_ms": 1100,
                "end_ms": 1400,
                "severity": "major",
                "planned": False,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "in.json"
            out = Path(tmp) / "out"
            _write_json(in_path, rows)
            out.mkdir(parents=True, exist_ok=True)
            result = _run_pipeline(input_path=in_path, output_dir=out)
            assert result.returncode == 0, result.stderr
            windows = _load_json(out / "segment_windows.json")
            first, second = windows["auth"]
            assert first["debt_out_ms"] == 400
            # Gap of 700 is at or beyond the reset threshold: the ledger clears
            # outright rather than decaying to max(400 - 700 // 3, 0) == 167.
            assert second["idle_gap_ms"] == 700
            assert second["debt_in_ms"] == 0
            assert second["debt_out_ms"] == 300
            assert second["debt_adjusted_dispatchable_ms"] == 300
    finally:
        MAINTENANCE_PATH.write_text(original_maint)
        EXCEPTIONS_PATH.write_text(original_ex)
        HANDOFF_PATH.write_text(original_handoff)
        BLACKOUT_PATH.write_text(original_blackout)
        DEGRADE_PATH.write_text(original_degrade)


def test_effective_queue_threshold_uses_exception_units_and_ceil_suppress():
    """Queue admission uses the exception-unit arithmetic with the suppression count rounded up.

    The effective threshold is derived from boost and suppress unit counts under the governed
    rounding direction, so admission follows the unit arithmetic rather than the raw threshold.
    """
    original_maint = MAINTENANCE_PATH.read_text()
    original_ex = EXCEPTIONS_PATH.read_text()
    original_policy = POLICY_PATH.read_text()
    original_blackout = BLACKOUT_PATH.read_text()
    original_degrade = DEGRADE_PATH.read_text()
    try:
        MAINTENANCE_PATH.write_text("[]\n")
        BLACKOUT_PATH.write_text("[]\n")
        DEGRADE_PATH.write_text("[]\n")
        _write_json(
            EXCEPTIONS_PATH,
            [
                {"shard": "auth", "start_ms": 0, "end_ms": 120, "action": "suppress"},
                {"shard": "authentication", "start_ms": 60, "end_ms": 180, "action": "boost"},
            ],
        )
        _write_json(
            POLICY_PATH,
            {
                "default": {
                    "queue_min_effective_ms": 250,
                    "critical_p1_min_ms": 280,
                    "critical_threshold_ms": 650,
                    "high_threshold_ms": 320,
                    "no_overlap_high_duration_ms": 450,
                    "critical_count_for_critical": 2,
                    "no_overlap_bonus": 0,
                    "segment_bonus": 0,
                    "suppress_penalty_ms": 50,
                    "boost_credit_ms": 20,
                    "suppress_unit_ms": 50,
                    "boost_unit_ms": 40,
                    "min_queue_floor_ms": 150,
                    "boost_force_critical_ms": 999,
                    "boost_high_relief_ms": 30,
                    "severity_weight": {"critical": 5, "major": 3, "minor": 1},
                    "score_threshold_critical": 999,
                    "score_threshold_high": 999
                },
                "shard_overrides": {}
            },
        )
        rows = [
            {
                "segment_id": "q1",
                "shard": "auth",
                "start_ms": 0,
                "end_ms": 300,
                "severity": "major",
                "planned": False,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "in.json"
            out = Path(tmp) / "out"
            _write_json(in_path, rows)
            out.mkdir(parents=True, exist_ok=True)
            result = _run_pipeline(input_path=in_path, output_dir=out)
            assert result.returncode == 0, result.stderr
            queue = _load_jsonl(out / "rebuild_queue.jsonl")
            assert len(queue) == 1
            row = queue[0]
            assert row["effective_queue_min_ms"] == 290
            assert row["adjusted_queue_min_ms"] == 290
            assert row["routed_queue_min_ms"] == 290
            assert row["dispatch_queue_min_ms"] == 290
            assert row["exception_balance_score"] == 1
            assert row["priority"] == "high"
    finally:
        MAINTENANCE_PATH.write_text(original_maint)
        EXCEPTIONS_PATH.write_text(original_ex)
        POLICY_PATH.write_text(original_policy)
        BLACKOUT_PATH.write_text(original_blackout)
        DEGRADE_PATH.write_text(original_degrade)



WRAPPER_PATH = Path("/usr/local/bin/index-rebuild")
LOCK_PATH = Path("/var/lock/index-rebuild.lock")
CRON_PATH = Path("/etc/cron.d/index-rebuild")
CRON_LINE = (
    "*/5 * * * * svc-indexer /usr/local/bin/index-rebuild "
    "--input /app/data/segments.json --output-dir /app/output"
)


def test_system_account_provisioned():
    """The svc-indexer system account exists with a non-interactive shell."""
    import pwd

    entry = pwd.getpwnam("svc-indexer")
    assert entry.pw_shell in ("/usr/sbin/nologin", "/sbin/nologin", "/bin/false")


def test_stale_compile_lock_cleared():
    """The stale rollout lock under /var/lock has been removed."""
    assert not LOCK_PATH.exists()


def test_wrapper_installed_and_functional(tmp_path_factory):
    """The operator wrapper is executable, targets the live compiler, and runs it."""
    assert WRAPPER_PATH.exists()
    mode = WRAPPER_PATH.stat().st_mode
    assert mode & 0o111, "wrapper must be executable"
    source = WRAPPER_PATH.read_text()
    assert ".legacy" not in source
    out_dir = tmp_path_factory.mktemp("wrapper_out")
    result = subprocess.run(  # noqa: PLW1510
        [str(WRAPPER_PATH), "--input", str(INPUT_PATH), "--output-dir", str(out_dir)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    for name in ("rebuild_summary.json", "segment_windows.json", "rebuild_queue.jsonl"):
        assert (out_dir / name).exists()


def test_wrapper_honors_compile_lock(tmp_path_factory):
    """With the lock present the wrapper exits 75 and writes nothing."""
    out_dir = tmp_path_factory.mktemp("locked_out")
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text("999999\n")
    try:
        result = subprocess.run(  # noqa: PLW1510
            [str(WRAPPER_PATH), "--input", str(INPUT_PATH), "--output-dir", str(out_dir)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 75
        # The lock branch must be silent on BOTH streams and must write no output file.
        assert result.stdout == "", f"wrapper wrote to stdout under lock: {result.stdout!r}"
        assert result.stderr == "", f"wrapper wrote to stderr under lock: {result.stderr!r}"
        for name in ("rebuild_summary.json", "segment_windows.json", "rebuild_queue.jsonl"):
            assert not (out_dir / name).exists(), f"wrapper wrote {name} despite the lock"
    finally:
        LOCK_PATH.unlink(missing_ok=True)


def test_cron_schedule_installed():
    """The cron drop-in exists with mode 0644 and the exact runbook job line."""
    assert CRON_PATH.exists()
    assert (CRON_PATH.stat().st_mode & 0o777) == 0o644
    lines = [line.strip() for line in CRON_PATH.read_text().splitlines() if line.strip()]
    assert CRON_LINE in lines


def test_output_dir_ownership_and_mode():
    """/app/output is owned by svc-indexer with mode 0750."""
    import pwd

    entry = pwd.getpwnam("svc-indexer")
    info = OUTPUT_DIR.stat()
    assert info.st_uid == entry.pw_uid
    assert info.st_gid == entry.pw_gid
    assert (info.st_mode & 0o777) == 0o750


def test_governing_entry_index_is_complete():
    """Every governing (non-superseded) review entry is reachable from the index.

    The instruction directs agents to the index, so an entry missing from it is
    effectively undiscoverable no matter how clearly the log states the rule.
    """
    import re
    gi = CONTRACT["governing_entry_index"]
    listed = {e for v in gi["stages"].values() for e in v}
    nonnorm = set(re.findall(r"IDX-\d+", gi.get("non_normative_entries", "")))
    log_text = Path("/app/rebuild/index_review_log.md").read_text(encoding="utf-8")
    pattern = re.compile(r"\*\*[A-Za-z -]+? \(\d{4}-\d{2}-\d{2} - (IDX-\d+)\)\*\*([^\n]*)")
    governing = {
        m.group(1)
        for m in pattern.finditer(log_text)
        if "*(superseded" not in m.group(2).lower() and "*(revised" not in m.group(2).lower()
    }
    assert governing, "no governing entries found -- parser segmented from the log format"
    missing = sorted(governing - listed - nonnorm)
    assert not missing, f"governing entries absent from governing_entry_index: {missing}"


def test_log_directory_ownership_and_mode():
    """/var/log/index-rebuild is handed to the system account and is not world-writable.

    The rollout left the compile log directory root-owned at mode 0777. Recovery must place it
    under svc-indexer:svc-indexer at mode 0750, since the scheduled compile writes there as that
    account and a world-writable log directory is a rollout defect.
    """
    import pwd

    log_dir = Path("/var/log/index-rebuild")
    assert log_dir.is_dir(), "compile log directory is missing"
    info = log_dir.stat()
    svc = pwd.getpwnam("svc-indexer")
    assert info.st_uid == svc.pw_uid and info.st_gid == svc.pw_gid, "log dir not owned by svc-indexer"
    assert (info.st_mode & 0o777) == 0o750, "log dir must be 0750, not world-writable"


def test_rollout_leftover_log_pruned():
    """The crashed rollout's unrotated leftover is removed while the live log survives.

    /var/log/index-rebuild/compile.log.0 was left behind mid-compile and must be pruned during
    recovery rather than handed to the next rotation. The live compile.log is not a leftover and
    must remain in place.
    """
    assert not Path("/var/log/index-rebuild/compile.log.0").exists(), "rollout leftover not pruned"
    assert Path("/var/log/index-rebuild/compile.log").exists(), "live compile log was removed"


def test_logrotate_dropin_installed():
    """Rotation is configured to run as the system account, not as root.

    The drop-in at /etc/logrotate.d/index-rebuild must exist at mode 0644 covering the compile
    log glob, and must carry the su/create directives that keep rotated files owned by
    svc-indexer along with the documented retention and safety directives.
    """
    dropin = Path("/etc/logrotate.d/index-rebuild")
    assert dropin.exists(), "logrotate drop-in was never installed"
    assert (dropin.stat().st_mode & 0o777) == 0o644, "logrotate drop-in must be mode 0644"
    text = dropin.read_text(encoding="utf-8")
    assert "/var/log/index-rebuild/*.log" in text, "drop-in does not cover the compile log glob"
    for directive in ("daily", "rotate 14", "compress", "missingok", "notifempty",
                      "su svc-indexer svc-indexer", "create 0640 svc-indexer svc-indexer"):
        assert directive in text, f"logrotate drop-in missing required directive: {directive}"


def test_shadow_module_under_app_cannot_bypass_verifier(tmp_path):
    """Regression: a module planted in the agent-writable /app must never shadow the pytest
    framework (or any verifier helper) when the grader resolves imports.

    The agent runs as root in /app during the solve phase and could drop a `pytest.py` file (or a
    `pytest/` package) there; a runner that did `python3 -m pytest` from WORKDIR /app would put the
    cwd on sys.path, so such a shadow could replace the real framework, exit 0, and score reward 1
    without ever running this suite. This proves the hardened launcher in tests/test.sh -- a clean
    temp cwd, unset PYTHONPATH, absolute /usr/local/bin/python3 in isolated mode (`-I`) with
    PYTHONSAFEPATH=1 -- binds pytest only from the protected site-packages, and that the naive
    `cd /app; python3` form it replaced would indeed have been subverted (so the check discriminates
    rather than passing vacuously).
    """
    app = Path("/app")
    shadow = app / "pytest.py"
    sentinel = "SHADOW_PYTEST_a1b2c3d4"
    probe = (
        "import pytest, sys;"
        "sys.stdout.write(getattr(pytest, 'MARKER', '') + '|' + (getattr(pytest, '__file__', '') or ''))"
    )
    created = False
    try:
        try:
            shadow.write_text(f'MARKER = "{sentinel}"\n', encoding="utf-8")
            created = True
        except OSError:
            pytest.skip("/app is not writable here; the launcher isolation still applies")

        # (a) The unprotected /app resolution IS shadowed -- proves the attack vector is real and
        #     that this regression would actually catch a regression in the launcher. Strip
        #     PYTHONSAFEPATH from the inherited env (the grader exports it, which would otherwise
        #     shield even this child) so the cwd is genuinely prepended to sys.path.
        naive_env = {k: v for k, v in os.environ.items() if k not in ("PYTHONSAFEPATH", "PYTHONPATH")}
        naive = subprocess.run(  # noqa: PLW1510
            ["/usr/local/bin/python3", "-c", probe],
            cwd=str(app), env=naive_env, capture_output=True, text=True,
        )
        naive_marker = naive.stdout.split("|", 1)[0]
        assert naive_marker == sentinel, (
            "expected the naive /app invocation to import the /app shadow pytest; if it does not, "
            f"this test cannot prove the launcher defeats it (stdout={naive.stdout!r})"
        )

        # (b) The hardened launcher resolution must bind the REAL pytest, never the /app shadow.
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["PYTHONSAFEPATH"] = "1"
        hardened = subprocess.run(  # noqa: PLW1510
            ["/usr/local/bin/python3", "-I", "-B", "-c", probe],
            cwd=str(tmp_path), env=env, capture_output=True, text=True,
        )
        parts = hardened.stdout.split("|", 1)
        marker = parts[0]
        resolved = parts[1] if len(parts) > 1 else ""
        assert marker != sentinel, (
            f"hardened launcher imported the /app shadow pytest (marker={marker!r}); interpreter "
            "isolation is not protecting the grader"
        )
        assert resolved and not resolved.startswith("/app/"), (
            f"hardened launcher resolved pytest from an agent-writable path: {resolved!r}"
        )
    finally:
        if created:
            shadow.unlink(missing_ok=True)
