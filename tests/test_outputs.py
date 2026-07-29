"""Verify the exact-seeded random-forest regressor at /app/fit_forest.py."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from fractions import Fraction
from math import gcd
from pathlib import Path

import pytest

CANDIDATE_USER = os.environ.get("CANDIDATE_USER", "tree-candidate")


def _candidate_enabled() -> bool:
    """True when we are root and can drop privileges to the unprivileged candidate."""
    if os.geteuid() != 0:
        return False
    if shutil.which("runuser") is None:
        return False
    return (
        subprocess.run(["id", CANDIDATE_USER], capture_output=True, check=False).returncode
        == 0
    )


def _grant_traversal(path: Path) -> None:
    for parent in Path(path).resolve().parents:
        sp = str(parent)
        if sp in ("/", "/tmp"):
            break
        if sp.startswith("/tests"):
            continue
        try:
            os.chmod(parent, (os.stat(parent).st_mode & 0o777) | 0o055)
        except OSError:
            pass


def _stage_dir(path: Path) -> Path:
    """Return a candidate-readable data dir; dirs under the locked /tests are copied out."""
    p = Path(path)
    if not str(p).startswith("/tests"):
        return p
    dst = Path(tempfile.mkdtemp(prefix="cand_data_"))
    for f in p.iterdir():
        shutil.copy(f, dst / f.name)
        os.chmod(dst / f.name, 0o644)
    os.chmod(dst, 0o755)
    return dst


CLI = Path("/app/fit_forest.py")
DATA = Path("/app/data")
OUTPUT = Path("/app/output")
FIX = Path("/tests/fixtures")
EXPECTED = json.loads((FIX / "expected.json").read_text())
ALT_EXPECTED = json.loads((FIX / "alt_expected.json").read_text())


def _canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha(obj: object) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def _run(data_dir: Path, out_dir: Path) -> subprocess.CompletedProcess[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    argv = [
        "python3", str(CLI),
        "--data-dir", str(_stage_dir(data_dir)),
        "--output-dir", str(out_dir),
    ]
    if _candidate_enabled():
        os.chmod(out_dir, 0o777)
        _grant_traversal(out_dir)
        argv = ["runuser", "-u", CANDIDATE_USER, "--", *argv]
    return subprocess.run(  # noqa: PLW1510
        argv, capture_output=True, text=True, timeout=120
    )


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _leaves(tree: dict) -> list[dict]:
    if tree["type"] == "leaf":
        return [tree]
    return _leaves(tree["left"]) + _leaves(tree["right"])


def _route(tree: dict, features: list[int]) -> Fraction:
    node = tree
    while node["type"] == "split":
        node = node["left"] if features[node["feature"]] <= node["threshold"] else node["right"]
    return Fraction(node["value"][0], node["value"][1])


def _forest_predict(trees: list[dict], features: list[int]) -> Fraction:
    return sum((_route(t, features) for t in trees), Fraction(0)) / len(trees)


@pytest.fixture(scope="module")
def model() -> dict:
    return _load(OUTPUT / "model.json")


@pytest.fixture(scope="module")
def predictions() -> dict:
    return _load(OUTPUT / "predictions.json")


@pytest.fixture(scope="module")
def metrics() -> dict:
    return _load(OUTPUT / "metrics.json")


def test_cli_exists():
    """The learner program exists at /app/fit_forest.py."""
    assert CLI.exists(), "/app/fit_forest.py was not created"


def test_required_outputs_present():
    """The learner writes the three required output files."""
    for name in ("model.json", "predictions.json", "metrics.json"):
        assert (OUTPUT / name).exists(), f"missing output {name}"


def test_model_matches_reference(model: dict):
    """The fitted forest and its checksum match the exact reference model."""
    assert model == EXPECTED["model"]


def test_predictions_match_reference(predictions: dict):
    """The aggregated test-set predictions and their checksum match the exact reference."""
    assert predictions == EXPECTED["predictions"]


def test_metrics_match_reference(metrics: dict):
    """train_mse, n_trees and total_leaves match the exact reference metrics."""
    assert metrics == EXPECTED["metrics"]


def test_forest_checksum_self_consistent(model: dict):
    """model.forest_sha256 is the canonical SHA-256 of the emitted trees array."""
    assert model["forest_sha256"] == _sha(model["trees"])


def test_predictions_checksum_self_consistent(predictions: dict):
    """predictions_sha256 is the canonical SHA-256 of the predictions array."""
    assert predictions["predictions_sha256"] == _sha(predictions["predictions"])


def test_n_trees_consistent(model: dict, metrics: dict):
    """n_trees agrees across model and metrics and equals the number of emitted trees."""
    assert model["n_trees"] == len(model["trees"]) == metrics["n_trees"]


def test_leaf_values_are_lowest_terms(model: dict):
    """Every leaf value across every tree is an exact rational [num, den] in lowest terms."""
    for tree in model["trees"]:
        for leaf in _leaves(tree):
            num, den = leaf["value"]
            assert den > 0
            assert gcd(abs(num), den) == 1


def test_node_sample_counts_consistent(model: dict):
    """Within each tree every split's n_samples equals the sum of its children, and each tree's
    root covers exactly N bootstrap rows (duplicates included)."""
    n = len(_load(DATA / "train.json"))

    def check(node: dict) -> int:
        if node["type"] == "leaf":
            return node["n_samples"]
        total = check(node["left"]) + check(node["right"])
        assert node["n_samples"] == total
        return total

    for tree in model["trees"]:
        assert check(tree) == n


def test_predictions_follow_the_forest(model: dict, predictions: dict):
    """Each prediction is exactly the mean of the per-tree leaf values the test row routes to."""
    test = _load(DATA / "test.json")
    routed = []
    for row in test:
        p = _forest_predict(model["trees"], row["features"])
        routed.append([p.numerator, p.denominator])
    assert routed == predictions["predictions"]


def test_total_leaves_matches(model: dict, metrics: dict):
    """metrics.total_leaves equals the summed leaf count across all trees."""
    assert metrics["total_leaves"] == sum(len(_leaves(t)) for t in model["trees"])


def test_train_mse_recomputed(model: dict, metrics: dict):
    """train_mse equals the exact mean squared training residual of the aggregated forest."""
    train = _load(DATA / "train.json")
    total = Fraction(0)
    for row in train:
        pred = _forest_predict(model["trees"], row["features"])
        total += (Fraction(row["target"]) - pred) ** 2
    mse = total / len(train)
    assert metrics["train_mse"] == [mse.numerator, mse.denominator]


def test_idempotent_rerun(tmp_path_factory):
    """Re-running the learner reproduces byte-identical outputs."""
    out = tmp_path_factory.mktemp("rerun")
    result = _run(DATA, out)
    assert result.returncode == 0, result.stderr
    for name in ("model.json", "predictions.json", "metrics.json"):
        assert _load(out / name) == _load(OUTPUT / name)


def test_generalizes_to_alternate_dataset(tmp_path_factory):
    """On an unseen dataset and config, the learner reproduces the exact reference outputs."""
    out = tmp_path_factory.mktemp("alt")
    result = _run(FIX / "alt", out)
    assert result.returncode == 0, result.stderr
    assert _load(out / "model.json") == ALT_EXPECTED["model"]
    assert _load(out / "predictions.json") == ALT_EXPECTED["predictions"]
    assert _load(out / "metrics.json") == ALT_EXPECTED["metrics"]


def test_learner_cannot_read_tests_tree():
    """Real OS-level isolation: the learner runs unprivileged and /tests is root-only,
    so it cannot read the reference fixtures (even via os.open) to copy expected output."""
    if not _candidate_enabled():
        pytest.skip("requires root plus the unprivileged candidate user to enforce OS isolation")
    assert oct(Path("/tests").stat().st_mode)[-3:] == "700", "/tests must be locked to 0700"
    probe = subprocess.run(  # noqa: PLW1510
        [
            "runuser", "-u", CANDIDATE_USER, "--", "python3", "-c",
            (
                "import os, sys\n"
                "try:\n"
                "    os.close(os.open('/tests/fixtures/expected.json', os.O_RDONLY))\n"
                "    print('READABLE'); sys.exit(2)\n"
                "except OSError:\n"
                "    sys.exit(0)\n"
            ),
        ],
        capture_output=True, text=True,
    )
    assert probe.returncode == 0, f"candidate could read /tests fixtures: {probe.stdout}{probe.stderr}"
