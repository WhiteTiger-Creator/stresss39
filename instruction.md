# Fit an exact CART regression tree

Implement `/app/fit_tree.py`, a command-line program that trains a CART regression tree on the
dataset under `/app/data` and writes the fitted model, its test-set predictions, and training
metrics to an output directory.

The program takes two optional flags, `--data-dir` (default `/app/data`) and `--output-dir`
(default `/app/output`). It reads `train.json`, `test.json` and `config.json` from the data
directory and writes `model.json`, `predictions.json` and `metrics.json` to the output directory.

Two documents under `/app/docs` govern the task, and you must reconcile them:

- `/app/docs/tree_spec.md` is the **I/O contract**: the files, the JSON node shapes, the
  exact-rational `[numerator, denominator]` encoding, the canonical SHA-256 hashing, and the
  determinism requirement. It is stable.
- `/app/docs/model_review_log.md` is the **authoritative record of the learning algorithm**: the
  impurity criterion, the candidate-split and threshold rules, the routing test, the
  validity/eligibility gates, the tie-breaks, the best-first leaf-budgeted growth, the minimal
  cost-complexity (weakest-link) pruning, and the leaf statistic. It is a dated engineering log in
  which **several early decisions were later revised, and where entries conflict the later-dated
  ratified entry is the one the reference model encodes.** Do not assume textbook CART defaults:
  read the log to the end of each topic — at least two of the shipped conventions differ from the
  usual ones, and an implementation that follows the first draft it sees will not match.

The tree is grown first and then pruned; both passes feed the final `model.json`,
`predictions.json` and `metrics.json`.

Every quantity the model reports (leaf values, predictions, and the training MSE) is an **exact
rational number** emitted as `[numerator, denominator]` in lowest terms, so your arithmetic must be
exact rather than floating point. Two correct implementations produce byte-identical output,
including the embedded checksums. The program must be deterministic (a rerun reproduces the same
files) and must work on any dataset of the same shape, not just the shipped one — derive everything
from the data, the config and the ratified decisions in the review log, and do not hardcode outputs.
