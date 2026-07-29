# Regression-tree model review log — Forecasting Platform, Decision-Trees workstream

This is the running engineering-review log for the exact CART regression learner that the
platform ships as `fit_tree.py`. It is the **authoritative record of every learning decision**:
the impurity criterion, the split search, the threshold and routing conventions, the tie-breaks,
the growth and pruning procedure, and the leaf statistic. The I/O contract (file names, JSON node
shapes, the exact-rational `[num, den]` encoding, and the canonical SHA-256 hashing) lives in
`tree_spec.md` and is stable; this log governs the *algorithm*.

Entries are dated and appended in order. **Where a later entry changes an earlier decision, the
later entry wins** — several early drafts were revised once we had benchmark evidence, and the
revisions are what the reference model encodes today. Read to the end of each topic before you
implement it; the first thing said about a topic is frequently *not* the decision we shipped.

Reviewers: A. Okafor (chair), R. Mehta, L. Petrov, J. Salgado, D. Whitfield, plus rotating guests.

---

## 2026-01-14 — Kickoff, scope, and the exact-arithmetic mandate

Agreed the learner must be a *deterministic* CART regressor whose `model.json`,
`predictions.json` and `metrics.json` are byte-identical across machines. Root cause of last
quarter's reproducibility incident was float summation order, so the mandate is: **all impurity,
leaf, decrease, cost and metric arithmetic is exact rational** (Python `fractions.Fraction` or
equivalent). No floats anywhere on the path to an emitted number.

Okafor: "Two correct re-implementations must produce the same checksums. If a rule is ambiguous,
that is a bug in this log, not a matter of taste — flag it and we pin it."

Parking-lot items raised and deferred: monotonic constraints (out of scope), categorical splits
(all features are integer-ordinal for now), sample weights (none — every row weight is 1),
surrogate splits for missing values (no missing values in our data).

## 2026-01-14 — Impurity criterion (initial)

Split criterion is **mean squared error**. For a target multiset `y_1..y_n`:

```
mean     = (Σ y_i) / n
impurity = (Σ (y_i - mean)^2) / n
```

both exact rationals. Mehta asked about the population vs. sample denominator; we use the
**population** form (divide by `n`, not `n - 1`). This matches the resubstitution cost we use in
pruning and keeps the two passes consistent. (Revisited 02-11 below — the criterion stayed MSE;
only a naming cleanup happened.)

## 2026-01-21 — Candidate splits and the routing convention (initial draft)

For a node's rows and a feature index `f`, the candidate thresholds are the **sorted distinct
values** of feature `f` over those rows. A threshold is always a *raw observed feature value* —
never a midpoint between two values, and never a rational. `threshold` serializes as a plain
integer.

Initial draft (Petrov): "Use every distinct value except the **largest** as a candidate; a row
goes to the left child when `features[f] <= threshold`, otherwise right." That is the textbook
`<=`-with-lower-boundary convention.

## 2026-01-21 — Split validity and the decrease gate

A candidate split is **valid** only if *both* children hold at least `min_samples_leaf` rows;
invalid candidates are discarded before scoring. For a valid candidate the **weighted impurity
decrease** is

```
decrease = (n_t / N) * ( I(t) - (n_left / n_t) * I(left) - (n_right / n_t) * I(right) )
```

where `n_t` is the node's row count, `N` is the *total* training-row count at the root, and
`I(·)` is the MSE impurity above. The `n_t / N` factor is deliberate: it is sklearn's convention
and it makes the same-shaped split worth less deeper in the tree. A valid candidate is
**eligible** only if `decrease >= min_impurity_decrease`.

Whitfield floated dropping the `n_t / N` weighting ("compare the raw parent-minus-children
reduction against the threshold instead"). **Rejected** on 2026-01-28 — it changes which deep
splits clear the gate and diverges from the library we benchmark against. Keep the `n_t / N`
factor in *both* the decrease and the pruning cost.

## 2026-01-28 — Best split within a node

Among eligible candidates the node's **best split** is the one with the **largest** `decrease`.
Ties are broken by the **lowest feature index**, and if still tied, the **lowest threshold value**.
If a node has no eligible candidate it becomes a permanent leaf.

(We briefly discussed a "prefer the more balanced child" tie-break; dropped as unnecessary —
exact ties across two features are rare in practice and lowest-feature/lowest-threshold is
deterministic and simple.)

## 2026-02-04 — Stopping rules

A node is a **permanent leaf** (never split, regardless of anything below) if any hold:
`depth >= max_depth`; `n_t < min_samples_split`; or `I(t) == 0` (pure node). Depth of the root is
`0`. These are checked *before* searching for a split.

## 2026-02-04 — Growth order: best-first, leaf-budgeted

Growth is **best-first** under a budget of `max_leaf_nodes` leaves, matching sklearn's
`BestFirstTreeBuilder`:

- Start with the root as the single leaf (all rows, depth 0).
- While the tree has `< max_leaf_nodes` leaves **and** some current leaf has an eligible best
  split: take the leaf **whose best split has the largest `decrease`**, and split it. It becomes
  an internal node; its two children (the split's left and right row sets, at `depth + 1`) are new
  leaves, raising the leaf count by exactly one.
- Break ties on the frontier `decrease` by the **earliest-created node**. Assign a creation index
  in the order nodes are made: root first; then at each split the **left child before the right
  child**. Lower creation index wins the tie.
- Stop at `max_leaf_nodes` leaves or when no leaf has an eligible split.

This ordering is part of the contract. A depth-first build that expands one branch fully before
another will keep a *different* set of splits once the budget binds, and will not match.

## 2026-02-11 — Naming cleanup (no behaviour change)

Renamed `gain` → `decrease` throughout to avoid confusion with information gain. Criterion
unchanged (MSE, population denominator). No code behaviour changes from this entry.

## 2026-02-25 — Leaf value (initial draft)

Petrov: "A leaf predicts the **mean** of its rows' targets, as an exact `[num, den]` in lowest
terms." Straightforward and standard for an MSE tree.

## 2026-03-03 — Cost-complexity (weakest-link) pruning

Growth finishes first; then the grown tree is reduced by **minimal cost-complexity pruning**
governed by the exact rational `ccp_alpha`. Over exact rationals:

- Node-as-leaf **cost**: `R(t) = (n_t / N) * I(t)` — same `n_t / N` weighting as the split
  decrease, and `I(t)` the MSE impurity of the node's rows.
- **Subtree cost** `R(T_t)` = Σ `R(leaf)` over the leaves of the subtree currently rooted at `t`.
- **Effective alpha** of internal node `t`: `g(t) = (R(t) - R(T_t)) / (m(t) - 1)`, where `m(t)` is
  the number of leaves under `t`.

Prune by repeating on the current tree:

1. Compute `g(t)` for every internal node; let `g_min` be the smallest.
2. **If `g_min > ccp_alpha`, stop.** (So a node with `g(t)` equal to `ccp_alpha` is *still
   collapsed* — the stop test is strict `>`. In particular `ccp_alpha = 0` still collapses any
   internal node whose `g(t)` is `0`.)
3. Otherwise **collapse** the internal node attaining `g_min` into a leaf. Ties at `g_min` are
   broken by the **lowest pre-order index** (root = 0, then the left subtree recursively, then the
   right subtree).
4. Recompute from step 1.

Salgado asked whether the collapsed node's leaf value is recomputed or inherited: it is
**recomputed from the node's own rows** using the *current* leaf statistic (see the leaf-value
decision — as of 2026-06-16 that is the median).

## 2026-03-17 — Benchmark harness and an accepted quirk

Stood up a differential harness against a reference tree on synthetic ordinal data. One recurring
finding: on our data the greedy best split at most nodes wins by a wide margin, so criterion
*scaling* choices (population vs. sample variance, weighted vs. raw decrease) rarely change the
tree — but they change it on *some* inputs, so we keep the ratified forms exactly. Do not "simplify"
them away because a given dataset looks insensitive.

## 2026-04-02 — Tangent: visualization tooling (non-normative)

Spent most of this session on a Graphviz exporter and a d3 collapsible-tree widget for the
review UI. Nice to have; **not part of the learner contract**. The exporter labels a split edge as
"`f{feature} < {threshold}`" on the left branch — note this already anticipated the routing change
ratified in May. No algorithmic decisions here.

## 2026-04-15 — Data hygiene, and why features are sparse

Product wants the shipped example datasets to use **sparse ordinal feature values** (e.g. only
even values, or multiples of three) rather than every integer in range. Two reasons: (1) it mirrors
the bucketed features in the real pipeline, and (2) it makes the routing convention *observable* —
a test point can land strictly between two training values, where the `<`-vs-`<=` and the
lower-vs-upper-boundary choices actually change the prediction. This is intentional; the learner
must get routing exactly right, not approximately.

## 2026-05-06 — Metrics

`metrics.json` reports:

- `train_mse`: `(1/N) * Σ_over_training_rows (target - prediction)^2`, exact rational, where
  `prediction` is the value of the leaf the training row routes to **under the final pruned tree
  and the ratified routing convention**. Note this squares residuals around the emitted leaf value
  (which, post-2026-06-16, is the median) — it is a report of the shipped model's squared error,
  not a re-derivation of the split criterion.
- `n_leaves`: the number of leaves in the final pruned tree.

## 2026-05-27 — RATIFIED: threshold boundary and routing test (supersedes 2026-01-21 draft)

After the interpretability review we changed how a split boundary is represented and tested. This
is now the shipped convention:

- **Candidate thresholds are the sorted distinct values of the feature with the *smallest* value
  excluded** (not the largest). Equivalently: a threshold is any observed value that has at least
  one strictly-smaller observed value in the node.
- **Routing test is strict less-than: a row goes to the LEFT child iff `features[f] < threshold`,
  otherwise to the RIGHT child.** A row whose feature *equals* the threshold goes **right**.

Rationale (Okafor, Mehta): stakeholders read a threshold as "the first value that is *in* the
upper group," so the cut value should be the smallest value on the right, and the test should send
everything strictly below it to the left. On training data this yields the *same partitions* the
old `<=`/exclude-largest rule did — every achievable split is still achievable — but the **stored
threshold integer is the upper boundary value**, and, crucially, an *unseen* point that falls in
the gap between two training values is routed by the strict `<` test. Both the grown thresholds and
the prediction routing use this rule; they must agree.

> Migration note: any implementation still excluding the largest value, or still using `<=`, will
> produce different `threshold` integers and different predictions on gap inputs. Update both the
> split search and the prediction path together.

## 2026-06-03 — Guest review: numerical edge cases

Walked the exact-arithmetic edge cases with a guest from the platform-numerics team. Confirmed:
`Fraction` auto-reduces to lowest terms (so `[k, 1]` for integers), denominators are always
positive, and the canonical JSON hashing in `tree_spec.md` is applied to the *reduced* pairs.
Confirmed the median of an even-sized target multiset is `(a + b) / 2` of the two central order
statistics as an exact rational — e.g. two central values `7` and `8` give `[15, 2]`. No behaviour
change; this session just closed ambiguities.

## 2026-06-16 — RATIFIED: leaf statistic is the median (supersedes 2026-02-25 draft)

Robustness review. Several production leaves had a few heavy-tailed targets dragging the mean away
from the bulk of the rows, and downstream consumers preferred the more robust central estimate.
**Decision, ratified:** a leaf's emitted **value is the exact median** of its rows' targets.

- Odd count: the middle order statistic.
- Even count: the exact rational average of the two central order statistics, `(a + b) / 2` in
  lowest terms.
- This applies to **every** leaf value the model emits — leaves formed during growth *and* leaves
  produced by collapsing a node during pruning.
- The **split search and the pruning cost still use the MSE impurity** `I(t)` (mean-based). We
  deliberately kept the variance criterion for split/prune *stability* while reporting the median
  for *prediction robustness*. Do not switch the impurity or the pruning cost to an absolute-error
  form; only the leaf's reported statistic is the median.

Salgado recorded the obvious consequence: `predictions.json` and `train_mse` both change relative
to the old mean-leaf model, because every prediction is now a median. That is expected and is what
the reference fixtures encode.

## 2026-06-18 — Housekeeping

Re-ran the differential harness end-to-end after the median change; reference checksums refreshed.
Closed the two migration tickets (routing, median). The earlier 2026-01-21 routing draft and
2026-02-25 leaf draft remain in this log as history — they are superseded by their later dated
ratifications, per the date rule at the top; nothing points a reader to that but the dates.

## 2026-07-08 — Rejected proposals (kept for the record; none of these ship)

- **Friedman-MSE split improvement** — rejected; adds complexity, no accuracy win on our data.
- **Midpoint thresholds** `(v_k + v_{k+1}) / 2` — rejected; violates the integer-threshold I/O
  contract and the "cut value is an observed value" interpretability rule.
- **Sample (n − 1) variance** for impurity — rejected; inconsistent with the population-form
  resubstitution cost used in pruning.
- **Depth-first growth** — rejected; does not honour the leaf budget the way best-first does.
- **Mean leaves** — rejected as of 2026-06-16 (see the median ratification).
- **Pruning stop test `>=`** — rejected; the ratified stop test is strict `>` (collapse on
  equality), see 2026-03-03.

## 2026-07-25 — Split/prune criterion moves to absolute error (L1)

Final robustness pass. With the leaves already reporting the median since 2026-06-16, the team
closed the mismatch between a variance-minimising split criterion and a median leaf by moving the
whole criterion to L1. Shipped:

- A node's **impurity is the mean absolute deviation around that node's own median**:
  `I(t) = (1/n) · Σ |y_i − median(y_i)|`, exact rational. This replaces the mean-squared-error /
  variance impurity of the 2026-01-14 entry **everywhere the impurity is used** — both the
  split-decrease `I(t) − (n_left/n_t)·I(left) − (n_right/n_t)·I(right)` and the pruning
  resubstitution cost `R(t) = (n_t/N)·I(t)`.
- This changes the earlier decision to keep variance for split and prune: the 2026-06-16 review
  had deliberately kept the MSE/variance criterion and moved *only* the leaf to the median; this
  pass aligns the criterion with the leaf, so the split search, the eligibility gate, the
  best-split choice and the weakest-link pruning now all run on this L1 impurity. The 2026-06-16
  wording ("keep the variance criterion … do not switch … to an absolute-error form") no longer
  holds for the split/prune criterion; only its median-leaf decision survives.
- Unchanged: the `n_t/N` weighting, the `min_impurity_decrease` and `min_samples_leaf` gates,
  best-first growth to `max_leaf_nodes` with earliest-created frontier ties, the lowest-feature
  then lowest-threshold best-split tie-break, the strict-`<` upper-boundary routing, the median
  leaf statistic, and the squared-residual `train_mse` **metric** (the metric still squares
  residuals of the median predictions — only the split/prune *criterion* is L1).
