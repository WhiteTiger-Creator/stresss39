# Fit an exact CART regression tree

Implement `/app/fit_tree.py`, a command-line program that trains a CART regression tree on the
dataset under `/app/data` and writes the fitted model, its test-set predictions, and training
metrics to an output directory.

The program takes two optional flags, `--data-dir` (default `/app/data`) and `--output-dir`
(default `/app/output`). It reads `train.json`, `test.json` and `config.json` from the data
directory and writes `model.json`, `predictions.json` and `metrics.json` to the output directory.

The exact learning algorithm — the mean-squared-error impurity, the greedy split search and the
weighted impurity-decrease criterion that governs it, the validity and eligibility rules, the
tie-breaking order, the stopping conditions, the leaf values, the best-first, leaf-budgeted growth under `max_leaf_nodes`, the minimal cost-complexity
(weakest-link) pruning pass that reduces the grown tree under `ccp_alpha`, the JSON node shapes
(where `threshold` is a plain integer, not a rational pair), and the canonical SHA-256 hashing
used for the checksums — is defined in full in `/app/docs/tree_spec.md`. Follow it exactly; the
tree is grown first and then pruned, and both passes feed the final model, predictions and metrics.

Every quantity the model reports (leaf values, predictions, and the training MSE) is an **exact
rational number** emitted as `[numerator, denominator]` in lowest terms, so your arithmetic must
be exact rather than floating point. Two correct implementations produce byte-identical
`model.json`, `predictions.json` and `metrics.json`, including the embedded checksums. The
program must be deterministic (a rerun reproduces the same files) and must work on any dataset of
the same shape, not just the shipped one — derive everything from the data and the config, and do
not hardcode outputs.
