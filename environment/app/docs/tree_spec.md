# CART regression-tree — I/O contract

This document is the **stable input/output contract** for the learner: the files it reads and
writes, the JSON node shapes, the exact-rational number encoding, the canonical hashing, and the
determinism requirement. It does **not** define the learning algorithm.

> The learning algorithm — the impurity criterion, the candidate-split and threshold rules, the
> routing test, the validity/eligibility gates, the tie-breaks, the best-first growth, the
> cost-complexity pruning, and the leaf statistic — is governed **entirely** by the ratified
> decisions in [`model_review_log.md`](./model_review_log.md). Several of those decisions were
> revised after an initial draft; **where entries conflict, the later-dated ratified entry wins**.
> Reconstruct the procedure from that log. Do not assume textbook CART defaults — two of the
> shipped conventions differ from the usual ones.

## Exact rational arithmetic

Every value in the model, the predictions and the metrics is an **exact rational number**, emitted
as `[numerator, denominator]` in lowest terms (an integer `k` is `[k, 1]`; denominators are always
positive). Represent all impurity, leaf, decrease, cost and metric arithmetic with exact fractions
(for example Python's `fractions.Fraction`); a floating-point implementation will not reproduce the
required output. Two correct implementations produce byte-identical `model.json`,
`predictions.json` and `metrics.json`, including the embedded checksums.

## Inputs (read from `--data-dir`, default `/app/data`)

- `train.json` — a JSON array of rows `{"features": [int, ...], "target": int}`. Every row has the
  same number of features `F`. `N` denotes the number of training rows (the sample count at the
  root).
- `test.json` — the same shape; `target` is present but is not used to make predictions.
- `config.json` — `{"max_depth": int, "min_samples_split": int, "min_samples_leaf": int,
  "max_leaf_nodes": int, "min_impurity_decrease": [num, den], "ccp_alpha": [num, den]}`.
  `max_leaf_nodes` caps the number of leaves during growth, `min_impurity_decrease` gates each
  split, and `ccp_alpha` governs pruning; the last two are exact rationals `num/den`. The learner
  must work on **any** dataset of this shape, not just the shipped one.

## Node serialization

- Leaf: `{"type": "leaf", "value": [num, den], "n_samples": n_t}`
- Split: `{"type": "split", "feature": f, "threshold": t, "n_samples": n_t, "left": <node>, "right": <node>}`

`threshold` `t` is a plain **integer scalar** (an observed feature value) — **not** a rational
pair. The only rational-valued numbers anywhere are leaf `value`s and the `predictions` and
`train_mse` entries; `feature`, `threshold` and `n_samples` are plain integers. `n_samples` is the
node's training-row count, and each split's `n_samples` equals the sum of its children's.

## Canonical hashing

For any object, its canonical form is `json.dumps(obj, sort_keys=True, separators=(",", ":"))`
encoded as UTF-8, and its hash is the lowercase SHA-256 hex digest of that string.

## Outputs (write to `--output-dir`, default `/app/output`)

- `model.json`: `{"tree": <root node>, "tree_sha256": <hash of the tree object>}`, describing the
  final tree the log's procedure produces (grown, then pruned).
- `predictions.json`: `{"predictions": [[num, den], ...], "predictions_sha256": <hash of the
  predictions array>}`. One prediction per `test.json` row, in order: route the row's features from
  the root to a leaf **using the routing convention ratified in the review log**, then emit that
  leaf's value.
- `metrics.json`: `{"train_mse": [num, den], "n_leaves": int}`, where `train_mse` is
  `(1/N) * Σ (target - prediction)^2` over the training rows as an exact rational (each
  `prediction` being the leaf value that training row routes to under the final tree), and
  `n_leaves` is the number of leaves in the final tree.

## Determinism

A rerun on the same inputs reproduces byte-identical outputs. There is no randomness in the
procedure; every tie is broken by an explicit rule stated in the review log.
