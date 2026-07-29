"""Reference exact-seeded random-forest regressor with exact rational arithmetic.

Every quantity (impurity, leaf means, per-tree predictions, the forest aggregate and the
metrics) is an exact rational number emitted as [numerator, denominator] in lowest terms, so a
correct implementation reproduces model.json, predictions.json and metrics.json bit-for-bit. The
only randomness is a single seeded linear congruential generator (LCG) whose stream is consumed
in one exact, fully specified order across the whole forest build; reproducing that order is the
crux of the task. See /app/docs/forest_spec.md for the pinned algorithm.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path


def _frac_pair(value: Fraction) -> list[int]:
    value = Fraction(value)
    return [value.numerator, value.denominator]


def _mean(targets: list[int]) -> Fraction:
    return Fraction(sum(targets), len(targets))


def _impurity(targets: list[int]) -> Fraction:
    # Population mean-squared-error: (1/n) * sum((y - mean)^2), exact.
    n = len(targets)
    mean = _mean(targets)
    return sum((Fraction(y) - mean) ** 2 for y in targets) / n


def _canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha(obj: object) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


class LCG:
    """Seeded linear congruential generator. A `roll` advances the state and returns it."""

    def __init__(self, seed: int, a: int, c: int, m: int) -> None:
        self.state = seed % m
        self.a, self.c, self.m = a, c, m

    def roll(self) -> int:
        self.state = (self.a * self.state + self.c) % self.m
        return self.state

    def below(self, n: int) -> int:
        """An index in [0, n): one roll, taken modulo n."""
        return self.roll() % n


def _bootstrap_indices(rng: LCG, n: int) -> list[int]:
    """n draws WITH REPLACEMENT from [0, n), in order — n rolls, each taken modulo n."""
    return [rng.below(n) for _ in range(n)]


def _choose_features(rng: LCG, n_features: int, k: int) -> list[int]:
    """Select k distinct feature indices by a partial Fisher-Yates shuffle consuming exactly k
    rolls: for position i in 0..k-1, swap slot i with slot (i + roll % (n_features - i)). The
    chosen features are the first k slots AFTER the swaps, returned sorted ascending for the split
    search. If k >= n_features every feature is eligible and NO roll is consumed."""
    if k >= n_features:
        return list(range(n_features))
    order = list(range(n_features))
    for i in range(k):
        j = i + rng.below(n_features - i)
        order[i], order[j] = order[j], order[i]
    return sorted(order[:k])


class Builder:
    def __init__(self, rows: list[dict], config: dict) -> None:
        self.rows = rows
        self.n_features = len(rows[0]["features"])
        self.max_depth = int(config["max_depth"])
        self.min_samples_split = int(config["min_samples_split"])
        self.min_samples_leaf = int(config["min_samples_leaf"])
        self.max_features = int(config["max_features"])

    def _best_split(self, idx: list[int], impurity: Fraction, features: list[int]):
        n_t = len(idx)
        best = None  # (decrease, feature, threshold, left, right)
        for feature in features:
            values = sorted({self.rows[i]["features"][feature] for i in idx})
            for threshold in values[:-1]:  # raw value, largest excluded; route x <= t left
                left, right = [], []
                for i in idx:
                    (left if self.rows[i]["features"][feature] <= threshold else right).append(i)
                if len(left) < self.min_samples_leaf or len(right) < self.min_samples_leaf:
                    continue
                left_imp = _impurity([self.rows[i]["target"] for i in left])
                right_imp = _impurity([self.rows[i]["target"] for i in right])
                child = Fraction(len(left), n_t) * left_imp + Fraction(len(right), n_t) * right_imp
                decrease = impurity - child
                cand = (decrease, feature, threshold, left, right)
                if best is None or decrease > best[0] or (
                    decrease == best[0] and (feature, threshold) < (best[1], best[2])
                ):
                    best = cand
        return best

    def build(self, rng: LCG, idx: list[int], depth: int) -> dict:
        """Grow one node in pre-order (root, then left subtree, then right subtree). The RNG is
        consumed here, in that pre-order, only at nodes that are actually split: a splittable node
        draws its feature subsample BEFORE searching for the best split."""
        targets = [self.rows[i]["target"] for i in idx]
        impurity = _impurity(targets)
        leaf = {"type": "leaf", "value": _frac_pair(_mean(targets)), "n_samples": len(idx)}
        if depth >= self.max_depth or len(idx) < self.min_samples_split or impurity == 0:
            return leaf
        features = _choose_features(rng, self.n_features, self.max_features)
        best = self._best_split(idx, impurity, features)
        if best is None:
            return leaf
        _, feature, threshold, left, right = best
        left_node = self.build(rng, left, depth + 1)   # pre-order: left before right
        right_node = self.build(rng, right, depth + 1)
        return {
            "type": "split", "feature": feature, "threshold": threshold,
            "n_samples": len(idx), "left": left_node, "right": right_node,
        }


def _predict_tree(tree: dict, features: list[int]) -> Fraction:
    node = tree
    while node["type"] == "split":
        node = node["left"] if features[node["feature"]] <= node["threshold"] else node["right"]
    return Fraction(node["value"][0], node["value"][1])


def _count_leaves(tree: dict) -> int:
    if tree["type"] == "leaf":
        return 1
    return _count_leaves(tree["left"]) + _count_leaves(tree["right"])


def build_forest(train: list[dict], config: dict) -> list[dict]:
    lcg = config["lcg"]
    rng = LCG(int(config["seed"]), int(lcg["a"]), int(lcg["c"]), int(lcg["m"]))
    builder = Builder(train, config)
    n = len(train)
    trees = []
    # ONE global stream: for each tree in order, first the bootstrap draw (n rolls), then the
    # tree's nodes in pre-order (feature-subsample rolls). Nothing resets the stream between trees.
    for _ in range(int(config["n_estimators"])):
        boot = _bootstrap_indices(rng, n)
        trees.append(builder.build(rng, boot, 0))
    return trees


def _forest_predict(trees: list[dict], features: list[int]) -> Fraction:
    # Exact aggregate: the arithmetic mean of the per-tree leaf values.
    total = sum((_predict_tree(t, features) for t in trees), Fraction(0))
    return total / len(trees)


def main() -> None:
    parser = argparse.ArgumentParser(description="Exact-seeded random-forest regressor")
    parser.add_argument("--data-dir", type=Path, default=Path("/app/data"))
    parser.add_argument("--output-dir", type=Path, default=Path("/app/output"))
    args = parser.parse_args()

    train = json.loads((args.data_dir / "train.json").read_text())
    test = json.loads((args.data_dir / "test.json").read_text())
    config = json.loads((args.data_dir / "config.json").read_text())

    trees = build_forest(train, config)
    model = {"trees": trees, "n_trees": len(trees), "forest_sha256": _sha(trees)}

    preds = [_forest_predict(trees, row["features"]) for row in test]
    predictions = {
        "predictions": [_frac_pair(p) for p in preds],
        "predictions_sha256": _sha([_frac_pair(p) for p in preds]),
    }

    residuals = [Fraction(row["target"]) - _forest_predict(trees, row["features"]) for row in train]
    mse = sum(r * r for r in residuals) / len(train)
    metrics = {
        "train_mse": _frac_pair(mse),
        "n_trees": len(trees),
        "total_leaves": sum(_count_leaves(t) for t in trees),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "model.json").write_text(json.dumps(model, indent=2) + "\n")
    (args.output_dir / "predictions.json").write_text(json.dumps(predictions, indent=2) + "\n")
    (args.output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(f"fit forest of {len(trees)} trees, {metrics['total_leaves']} leaves total")


if __name__ == "__main__":
    main()
