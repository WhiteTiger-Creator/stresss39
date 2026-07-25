"""Reference CART regression-tree learner with exact rational arithmetic.

Implements the algorithm pinned in /app/docs/tree_spec.md. All impurity and leaf
arithmetic uses fractions.Fraction so the model, predictions and metrics are
bit-exact and independent of floating-point order of operations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path


def _frac_pair(value: Fraction) -> list[int]:
    value = Fraction(value)  # already normalized to lowest terms
    return [value.numerator, value.denominator]


def _mean(targets: list[int]) -> Fraction:
    return Fraction(sum(targets), len(targets))


def _impurity(targets: list[int]) -> Fraction:
    # Mean squared error criterion: (1/n) * sum((y - mean)^2), exact.
    n = len(targets)
    mean = _mean(targets)
    total = sum((Fraction(y) - mean) ** 2 for y in targets)
    return total / n


def _canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha(obj: object) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


class Builder:
    def __init__(self, rows: list[dict], config: dict) -> None:
        self.rows = rows
        self.n_total = len(rows)
        self.n_features = len(rows[0]["features"])
        self.max_depth = int(config["max_depth"])
        self.min_samples_split = int(config["min_samples_split"])
        self.min_samples_leaf = int(config["min_samples_leaf"])
        mid = config["min_impurity_decrease"]
        self.min_impurity_decrease = Fraction(int(mid[0]), int(mid[1]))

    def _best_split(self, idx: list[int], impurity: Fraction):
        n_t = len(idx)
        # Weighting per the spec / sklearn: the decrease is scaled by N_t / N_total.
        weight = Fraction(n_t, self.n_total)
        best = None  # (decrease, feature, threshold, left_idx, right_idx)
        for feature in range(self.n_features):
            values = sorted({self.rows[i]["features"][feature] for i in idx})
            for threshold in values[:-1]:
                left, right = [], []
                for i in idx:
                    (left if self.rows[i]["features"][feature] <= threshold else right).append(i)
                if len(left) < self.min_samples_leaf or len(right) < self.min_samples_leaf:
                    continue
                left_imp = _impurity([self.rows[i]["target"] for i in left])
                right_imp = _impurity([self.rows[i]["target"] for i in right])
                child = (Fraction(len(left), n_t) * left_imp
                         + Fraction(len(right), n_t) * right_imp)
                decrease = weight * (impurity - child)
                if decrease < self.min_impurity_decrease:
                    continue
                cand = (decrease, feature, threshold, left, right)
                # Maximize decrease; tie-break by lowest feature then lowest threshold.
                if best is None or (decrease > best[0]) or (
                    decrease == best[0]
                    and (feature, threshold) < (best[1], best[2])
                ):
                    best = cand
        return best

    def build(self, idx: list[int], depth: int) -> dict:
        targets = [self.rows[i]["target"] for i in idx]
        impurity = _impurity(targets)
        node_n = len(idx)
        leaf = {
            "type": "leaf",
            "value": _frac_pair(_mean(targets)),
            "n_samples": node_n,
        }
        if (
            depth >= self.max_depth
            or node_n < self.min_samples_split
            or impurity == 0
        ):
            return leaf
        best = self._best_split(idx, impurity)
        if best is None:
            return leaf
        _, feature, threshold, left, right = best
        return {
            "type": "split",
            "feature": feature,
            "threshold": threshold,
            "n_samples": node_n,
            "left": self.build(left, depth + 1),
            "right": self.build(right, depth + 1),
        }


def _predict(tree: dict, features: list[int]) -> Fraction:
    node = tree
    while node["type"] == "split":
        node = node["left"] if features[node["feature"]] <= node["threshold"] else node["right"]
    return Fraction(node["value"][0], node["value"][1])


def main() -> None:
    parser = argparse.ArgumentParser(description="Exact CART regression-tree learner")
    parser.add_argument("--data-dir", type=Path, default=Path("/app/data"))
    parser.add_argument("--output-dir", type=Path, default=Path("/app/output"))
    args = parser.parse_args()
    data, output = args.data_dir, args.output_dir

    train = json.loads((data / "train.json").read_text())
    test = json.loads((data / "test.json").read_text())
    config = json.loads((data / "config.json").read_text())

    tree = Builder(train, config).build(list(range(len(train))), 0)
    model = {"tree": tree, "tree_sha256": _sha(tree)}

    preds = [_predict(tree, row["features"]) for row in test]
    predictions = {
        "predictions": [_frac_pair(p) for p in preds],
        "predictions_sha256": _sha([_frac_pair(p) for p in preds]),
    }

    residuals = [Fraction(row["target"]) - _predict(tree, row["features"]) for row in train]
    mse = sum(r * r for r in residuals) / len(train)
    metrics = {"train_mse": _frac_pair(mse), "n_leaves": _count_leaves(tree)}

    output.mkdir(parents=True, exist_ok=True)
    (output / "model.json").write_text(json.dumps(model, indent=2) + "\n")
    (output / "predictions.json").write_text(json.dumps(predictions, indent=2) + "\n")
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(f"fit tree with {metrics['n_leaves']} leaves")


def _count_leaves(tree: dict) -> int:
    if tree["type"] == "leaf":
        return 1
    return _count_leaves(tree["left"]) + _count_leaves(tree["right"])


if __name__ == "__main__":
    main()
