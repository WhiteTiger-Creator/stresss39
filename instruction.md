# Fit an exact-seeded random-forest regressor

Implement `/app/fit_forest.py`, a command-line program that trains a deterministic, exact-seeded
random-forest regressor on the dataset under `/app/data` and writes the fitted model, its test-set
predictions, and training metrics to an output directory.

The program takes two optional flags, `--data-dir` (default `/app/data`) and `--output-dir`
(default `/app/output`). It reads `train.json`, `test.json` and `config.json` from the data
directory and writes `model.json`, `predictions.json` and `metrics.json` to the output directory.

The complete algorithm — the single seeded LCG and the **exact order** in which its stream is
consumed (bootstrap sampling with replacement per tree, then the per-node feature subsample drawn
by a partial Fisher–Yates shuffle during a pre-order walk, all off one never-reset global stream),
the MSE split search over the subsampled features, the leaf means, the mean aggregation across
trees, the JSON node shapes, the exact-rational `[numerator, denominator]` encoding, and the
canonical SHA-256 hashing — is specified in full in `/app/docs/forest_spec.md`. Follow it exactly.

The heart of the task is reproducing the generator's consumption order bit-for-bit: which rolls
feed the bootstrap draw, which feed each node's feature subsample, and in what order nodes and
trees consume the one shared stream. A standard library random forest (numpy/sklearn seeding) will
**not** reproduce this stream and will not match.

Every quantity the model reports (leaf values, predictions, and the training MSE) is an **exact
rational number** emitted as `[numerator, denominator]` in lowest terms, so your arithmetic must be
exact rather than floating point. Two correct implementations produce byte-identical output,
including the embedded checksums. The program must be deterministic (a rerun reproduces the same
files) and must work on any dataset of the same shape, not just the shipped one — derive everything
from the data, the config and the specification, and do not hardcode outputs.
