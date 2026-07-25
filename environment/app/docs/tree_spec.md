# CART regression-tree specification

You are implementing a deterministic CART (Classification And Regression Trees) regression
learner. Every value in the model, the predictions and the metrics is an **exact rational
number**, so a correct implementation reproduces byte-identical output regardless of the order
of floating-point operations. Represent all impurity and mean arithmetic with exact fractions
(for example Python's `fractions.Fraction`); a floating-point implementation will not match the
required `[numerator, denominator]` output.

## Inputs (read from the data directory)

- `train.json` — a JSON array of rows `{"features": [int, ...], "target": int}`. Every row has
  the same number of features `F`.
- `test.json` — the same shape; `target` is present but is not used to make predictions.
- `config.json` — `{"max_depth": int, "min_samples_split": int, "min_samples_leaf": int,
  "min_impurity_decrease": [num, den]}`. The last is an exact rational `num/den`.

`N` denotes the number of training rows (the sample count at the root).

## Impurity

The split criterion is mean squared error. For a set of target values `y_1..y_n`:

```
mean      = (sum of y_i) / n                      # exact rational
impurity  = (sum of (y_i - mean)^2) / n           # exact rational
```

## Growing the tree

Grow recursively starting from the root, which holds all training rows at depth 0. At a node
holding `n_t` rows with impurity `I`:

1. Make the node a **leaf** (see below) if any of these hold: `depth >= max_depth`;
   `n_t < min_samples_split`; or `I == 0`.
2. Otherwise consider every candidate split. For each feature index `f` in `0..F-1`, let the
   candidate thresholds be the sorted distinct values of feature `f` over the node's rows, **with
   the largest value excluded**. A split with threshold `t` sends every row whose `features[f] <= t`
   to the left child and all remaining rows to the right child.
3. A candidate is **valid** only if both children have at least `min_samples_leaf` rows.
4. For a valid candidate, compute the weighted impurity decrease:

   ```
   decrease = (n_t / N) * ( I - (n_left / n_t) * I_left - (n_right / n_t) * I_right )
   ```

   All terms are exact rationals. **Note the `n_t / N` factor**: the decrease is scaled by the
   node's share of the *whole* training set `N`, not just of the node — the same split shape is
   worth less deeper in the tree.
5. A candidate is **eligible** only if `decrease >= min_impurity_decrease`.
6. Among eligible candidates pick the one with the **largest** `decrease`. Break ties by the
   **lowest feature index**, then by the **lowest threshold**.
7. If there is no eligible candidate, make the node a leaf. Otherwise split on the chosen
   `(feature, threshold)` and recurse into the left and right children at `depth + 1`.

## Leaf value

A leaf's value is the exact mean of its rows' targets, written as `[numerator, denominator]` in
lowest terms (an integer `k` is `[k, 1]`).

## Node serialization

- Leaf: `{"type": "leaf", "value": [num, den], "n_samples": n_t}`
- Split: `{"type": "split", "feature": f, "threshold": t, "n_samples": n_t, "left": <node>, "right": <node>}`

## Canonical hashing

For any object, its canonical form is `json.dumps(obj, sort_keys=True, separators=(",", ":"))`
encoded as UTF-8, and its hash is the lowercase SHA-256 hex digest of that.

## Outputs (write to the output directory)

- `model.json`: `{"tree": <root node>, "tree_sha256": <hash of the tree object>}`.
- `predictions.json`: `{"predictions": [[num, den], ...], "predictions_sha256": <hash of the
  predictions array>}`. There is one prediction per `test.json` row, in order; a prediction is
  produced by routing the row's features from the root (left when `features[f] <= threshold`)
  until a leaf, then taking that leaf's value.
- `metrics.json`: `{"train_mse": [num, den], "n_leaves": int}`, where `train_mse` is
  `(1/N) * sum over training rows of (target - prediction)^2` as an exact rational, and `n_leaves`
  is the number of leaves in the tree.
