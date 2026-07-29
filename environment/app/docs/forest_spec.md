# Exact-seeded random-forest regressor — full specification

Implement a deterministic random-forest regressor whose `model.json`, `predictions.json` and
`metrics.json` are **byte-identical** to this reference. Every emitted number is an **exact
rational** written as `[numerator, denominator]` in lowest terms (an integer `k` is `[k, 1]`;
denominators are positive), so all impurity, mean and aggregation arithmetic must be exact
fractions — a floating-point implementation will not match. Two correct implementations produce
identical output including the SHA-256 checksums.

The whole model is a deterministic function of the inputs and the seeded generator below. **There
is exactly one source of randomness — a single LCG stream — and reproducing the exact order in
which it is consumed is the core of the task.** A standard library forest (numpy/sklearn RNG,
per-tree seeding) will not reproduce this stream and will not match.

## Inputs (read from `--data-dir`, default `/app/data`)

- `train.json`, `test.json` — JSON arrays of rows `{"features": [int, ...], "target": int}`; every
  row has the same number of features `F`. `N` is the number of training rows.
- `config.json` — `{"n_estimators": int, "max_depth": int, "min_samples_split": int,
  "min_samples_leaf": int, "max_features": int, "seed": int, "lcg": {"a": int, "c": int, "m": int}}`.

## The generator (LCG)

A single generator is created once, at the start of the whole build, with state `seed`.

- A **roll** advances the state and returns the new value: `state = (a * state + c) mod m`; the
  roll's value is the new `state`.
- `below(n)` performs one roll and returns `roll mod n`, an index in `[0, n)`.

This one generator's stream is threaded through the **entire** forest build in the exact order
described below. It is **never reset, reseeded or forked** between trees or nodes — tree 1 keeps
rolling the same stream where tree 0 left off.

## Building the forest

For `t = 0, 1, …, n_estimators − 1`, in order, build tree `t`:

1. **Bootstrap sample (consumes `N` rolls).** Draw `N` training-row indices **with replacement**:
   `indices = [below(N) for _ in range(N)]`, i.e. `N` rolls in order, each taken `mod N`. Tree `t`
   is grown on exactly those rows, **including duplicates** (a row drawn three times counts three
   times in every impurity, mean and sample-count). Draw the bootstrap for tree `t` *before*
   growing tree `t`, and before drawing tree `t+1`'s bootstrap.

2. **Grow the tree on the bootstrap sample** by recursive binary splitting, visiting nodes in
   **pre-order** (make the node, then its left subtree fully, then its right subtree). The
   generator is consumed during this pre-order walk exactly as step 3 specifies.

Growth uses the standard mean-squared-error criterion with **feature subsampling**:

3. At a node holding a row multiset `S` (bootstrap rows, with duplicates) at `depth`:
   - Its **impurity** is the population MSE of its targets: `mean = (Σ y)/|S|`,
     `impurity = (Σ (y − mean)^2)/|S|`, exact.
   - The node is a **leaf** (consuming **no** roll) if any hold: `depth >= max_depth`;
     `|S| < min_samples_split`; or `impurity == 0`.
   - Otherwise it is a **candidate split node**, and it FIRST draws its **feature subsample**
     (this is where a node consumes the generator). Select `k = min(max_features, F)` distinct
     feature indices by a **partial Fisher–Yates shuffle that consumes exactly `k` rolls**: start
     with `order = [0, 1, …, F−1]`; for `i = 0 … k−1`, let `j = i + below(F − i)` and swap
     `order[i]` and `order[j]`. The subsample is `order[0 … k−1]`. (If `k >= F`, every feature is
     eligible and **no roll is consumed**.) Search for the best split **only among these features**;
     evaluate them in ascending feature-index order.
   - **Candidate thresholds** for a feature are the sorted distinct values of that feature over `S`
     with the **largest excluded**; a threshold `θ` is a raw feature value and sends rows with
     `features[f] <= θ` left, the rest right. A split is **valid** only if both children have at
     least `min_samples_leaf` rows. The **impurity decrease** is
     `impurity − (|L|/|S|)·impurity(L) − (|R|/|S|)·impurity(R)`, exact.
   - The **best split** is the valid candidate with the largest decrease, ties broken by lowest
     feature index then lowest threshold. If there is no valid split the node is a leaf (the
     feature-subsample rolls were still consumed).
   - Having split, recurse into the **left child first, then the right child** (pre-order), so all
     of the left subtree's rolls are consumed before any of the right subtree's.
   - A **leaf's value** is the exact mean of its rows' targets.

## Prediction and aggregation

Route a test row through each of the `n_estimators` trees (left when `features[f] <= threshold`)
to a leaf value; the **forest prediction** is the exact **arithmetic mean** of the per-tree leaf
values: `(Σ tree_value) / n_estimators`, as an exact rational in lowest terms.

## Node serialization

- Leaf: `{"type": "leaf", "value": [num, den], "n_samples": n}`
- Split: `{"type": "split", "feature": f, "threshold": t, "n_samples": n, "left": <node>, "right": <node>}`

`feature`, `threshold` and `n_samples` are plain integers (`n_samples` is the node's bootstrap-row
count, duplicates included, and equals the sum of its children's). Only leaf `value`s, the
`predictions`, and `train_mse` are `[num, den]` rationals.

## Canonical hashing

For any object, its canonical form is `json.dumps(obj, sort_keys=True, separators=(",", ":"))`
encoded UTF-8, hashed with SHA-256 (lowercase hex).

## Outputs (write to `--output-dir`, default `/app/output`)

- `model.json`: `{"trees": [<root node>, …], "n_trees": int, "forest_sha256": <hash of the trees array>}`.
- `predictions.json`: `{"predictions": [[num, den], …], "predictions_sha256": <hash of the
  predictions array>}` — one aggregated prediction per `test.json` row, in order.
- `metrics.json`: `{"train_mse": [num, den], "n_trees": int, "total_leaves": int}`, where
  `train_mse` is `(1/N)·Σ (target − forest_prediction)^2` over the training rows (each prediction
  the aggregated forest prediction), and `total_leaves` is the summed leaf count over all trees.

## Determinism

A rerun on the same inputs reproduces byte-identical output. There is no randomness beyond the one
seeded LCG stream, consumed in exactly the order above.
