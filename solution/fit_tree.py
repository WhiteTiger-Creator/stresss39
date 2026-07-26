"""Reference CART regression-tree learner with exact rational arithmetic.

Implements the algorithm pinned in /app/docs/tree_spec.md. All impurity, leaf and
pruning arithmetic uses fractions.Fraction so the model, predictions and metrics
are bit-exact and independent of floating-point order of operations. The tree is
grown by weighted-impurity-decrease CART and then reduced by minimal
cost-complexity (weakest-link) pruning.
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
        self.max_leaf_nodes = int(config["max_leaf_nodes"])

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

    def _make_node(self, idx: list[int], depth: int, cidx: int):
        """Create a leaf node plus its best eligible split (or None if it is a
        permanent leaf under the depth / min_samples / impurity / eligibility rules)."""
        targets = [self.rows[i]["target"] for i in idx]
        impurity = _impurity(targets)
        node = {
            "type": "leaf",
            "value": _frac_pair(_mean(targets)),
            "n_samples": len(idx),
            "_idx": idx,
            "_depth": depth,
            "_cidx": cidx,
        }
        split = None
        if not (depth >= self.max_depth or len(idx) < self.min_samples_split or impurity == 0):
            split = self._best_split(idx, impurity)
        return node, split

    def build_best_first(self, idx: list[int]) -> dict:
        """Best-first (leaf-budgeted) growth, matching sklearn's BestFirstTreeBuilder.

        The frontier of splittable leaves is expanded highest-impurity-decrease first
        until `max_leaf_nodes` leaves exist. Ties on the decrease are broken by the
        earliest-created node (lowest creation index; the left child is created before
        the right). A depth-first tree, which ignores this global ordering, keeps a
        different set of splits once the leaf budget binds.
        """
        counter = [0]
        root, root_split = self._make_node(idx, 0, counter[0])
        counter[0] += 1
        frontier: list[tuple[dict, tuple]] = []
        if root_split is not None:
            frontier.append((root, root_split))
        leaves = 1
        while leaves < self.max_leaf_nodes and frontier:
            best_i = max(
                range(len(frontier)),
                key=lambda i: (frontier[i][1][0], -frontier[i][0]["_cidx"]),
            )
            node, split = frontier.pop(best_i)
            _, feature, threshold, left, right = split
            node_idx, node_n, depth = node["_idx"], node["n_samples"], node["_depth"]
            left_node, left_split = self._make_node(left, depth + 1, counter[0])
            counter[0] += 1
            right_node, right_split = self._make_node(right, depth + 1, counter[0])
            counter[0] += 1
            node.clear()
            node.update({
                "type": "split",
                "feature": feature,
                "threshold": threshold,
                "n_samples": node_n,
                "left": left_node,
                "right": right_node,
                "_idx": node_idx,
            })
            leaves += 1
            if left_split is not None:
                frontier.append((left_node, left_split))
            if right_split is not None:
                frontier.append((right_node, right_split))
        return root

    def build(self, idx: list[int], depth: int) -> dict:
        # Every node carries its training-row indices ("_idx") so the pruning pass
        # can compute node cost and collapsed leaf values; indices are stripped
        # before serialization.
        targets = [self.rows[i]["target"] for i in idx]
        impurity = _impurity(targets)
        node_n = len(idx)
        leaf = {
            "type": "leaf",
            "value": _frac_pair(_mean(targets)),
            "n_samples": node_n,
            "_idx": idx,
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
            "_idx": idx,
        }


def _node_cost(rows: list[dict], n_total: int, node: dict) -> Fraction:
    """Weighted resubstitution cost of making this node a leaf: (n_t / N) * I(t)."""
    idx = node["_idx"]
    return Fraction(len(idx), n_total) * _impurity([rows[i]["target"] for i in idx])


def _subtree_cost(rows: list[dict], n_total: int, node: dict) -> Fraction:
    if node["type"] == "leaf":
        return _node_cost(rows, n_total, node)
    return (_subtree_cost(rows, n_total, node["left"])
            + _subtree_cost(rows, n_total, node["right"]))


def _subtree_leaves(node: dict) -> int:
    if node["type"] == "leaf":
        return 1
    return _subtree_leaves(node["left"]) + _subtree_leaves(node["right"])


def _internal_nodes_preorder(node: dict, counter: list[int]) -> list[tuple[int, dict]]:
    """Pre-order walk (root, then left subtree, then right subtree) collecting
    internal nodes paired with their pre-order index (used for the tie-break)."""
    idx = counter[0]
    counter[0] += 1
    if node["type"] == "leaf":
        return []
    found = [(idx, node)]
    found += _internal_nodes_preorder(node["left"], counter)
    found += _internal_nodes_preorder(node["right"], counter)
    return found


def _collapse(rows: list[dict], node: dict) -> None:
    """Turn an internal node into a leaf holding the exact mean of its rows."""
    idx = node["_idx"]
    targets = [rows[i]["target"] for i in idx]
    node.clear()
    node["type"] = "leaf"
    node["value"] = _frac_pair(_mean(targets))
    node["n_samples"] = len(idx)
    node["_idx"] = idx


def prune_ccp(rows: list[dict], n_total: int, root: dict, ccp_alpha: Fraction) -> dict:
    """Minimal cost-complexity (weakest-link) pruning. Repeatedly collapse the
    internal node with the smallest effective alpha g(t) = (R(t) - R(T_t)) /
    (leaves(T_t) - 1) while that minimum is <= ccp_alpha; ties are broken by the
    lowest pre-order index."""
    while True:
        internals = _internal_nodes_preorder(root, [0])
        if not internals:
            break
        scored = []  # (g, preorder_index, node)
        for pidx, node in internals:
            r_t = _node_cost(rows, n_total, node)
            r_subtree = _subtree_cost(rows, n_total, node)
            leaves = _subtree_leaves(node)
            g = (r_t - r_subtree) / (leaves - 1)
            scored.append((g, pidx, node))
        g_min = min(g for g, _, _ in scored)
        if g_min > ccp_alpha:
            break
        # Weakest link: collapse the min-g node, tie-broken by lowest pre-order index.
        _, _, victim = min(
            ((g, pidx, node) for g, pidx, node in scored if g == g_min),
            key=lambda t: t[1],
        )
        _collapse(rows, victim)
    return root


def _strip_idx(node: dict) -> dict:
    node.pop("_idx", None)
    node.pop("_depth", None)
    node.pop("_cidx", None)
    if node["type"] == "split":
        _strip_idx(node["left"])
        _strip_idx(node["right"])
    return node


def _predict(tree: dict, features: list[int]) -> Fraction:
    node = tree
    while node["type"] == "split":
        node = node["left"] if features[node["feature"]] <= node["threshold"] else node["right"]
    return Fraction(node["value"][0], node["value"][1])


def _count_leaves(tree: dict) -> int:
    if tree["type"] == "leaf":
        return 1
    return _count_leaves(tree["left"]) + _count_leaves(tree["right"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Exact CART regression-tree learner")
    parser.add_argument("--data-dir", type=Path, default=Path("/app/data"))
    parser.add_argument("--output-dir", type=Path, default=Path("/app/output"))
    args = parser.parse_args()
    data, output = args.data_dir, args.output_dir

    train = json.loads((data / "train.json").read_text())
    test = json.loads((data / "test.json").read_text())
    config = json.loads((data / "config.json").read_text())

    ccp = config["ccp_alpha"]
    ccp_alpha = Fraction(int(ccp[0]), int(ccp[1]))

    grown = Builder(train, config).build_best_first(list(range(len(train))))
    pruned = prune_ccp(train, len(train), grown, ccp_alpha)
    tree = _strip_idx(pruned)
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


if __name__ == "__main__":
    main()
