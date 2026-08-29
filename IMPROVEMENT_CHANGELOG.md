# Improvement Changelog

Every entry is one meaningful iteration: what was tried, why, the evidence it
produced, and the decision that evidence drove. Scores are the composite
primary metric defined in README section 5, measured on the same 16 cases with
the same scorer throughout.

## Summary

| Stage | What was tried and why | Evidence | Decision / learning |
|---|---|---|---|
| Baseline A | Schema validator — what teams run today | 0.419 | 9 of 14 defects invisible to schema checks |
| Baseline B | Direct prompt, both files in context | 0.925 | Strong at 200 rows; **rejected at 50k** |
| Pivot | Changed the measurement axis | — | No accuracy headroom; scale was the real problem |
| Iteration 1 | Streaming profiler | 0.775 | 806x compression, flat token cost |
| Iteration 1a | Added zero-fraction-rate statistic | 12/12 signals | Generic stats miss semantic drift |
| Iteration 1b | Added 4 adversarial cases | 0.775 on 16 | **Cross-column defects invisible to profiling** |
| Iteration 2 | Invariant discovery + verification | **0.944** | +22% score for +4% tokens |
| Iteration 2a | Root-cause classification instruction | 100% classification | Invariant breaks are symptoms, not diagnoses |
| Scale run | Agent v2 at 50,000 rows | **0.963** | Accuracy improves with scale |

---

## [0] Baseline A — schema validator

**Why:** establish what the user's existing tooling already catches, so the
comparison is against reality rather than nothing.

**What it is:** a genuine implementation (`eval/baseline_schema.py`) that
compares column sets and inferred dtypes between the two files — the same
checks a standard schema validation step performs. Deterministic, no LLM,
zero cost.

**Result**

| Metric | Value |
|---|---|
| Primary score | 0.419 |
| Recall on defects | 35.7% (5 of 14) |
| Recall on schema-invisible defects | 10.0% |
| False-positive rate | 0.0% |

Evidence: `results/schema_baseline_16.json`

**What this told us:** 9 of 14 defects pass a schema check silently. That is
the problem worth solving. One result was more interesting than the miss rate:
on the dollars-to-cents case the validator *did* fire, reporting
`amount dtype changed float -> int` — because removing the decimal point
changes the inferred type. An engineer acting on that alert would cast the
column back to float and move on, silently accepting values that are 100x
wrong. A technically correct alert that leads to the wrong fix.

---

## [1] Baseline B — direct prompt

**Why:** the challenge lists "one direct prompt with basic instructions" as an
acceptable baseline. Since the solution is LLM-based, an LLM baseline is the
fair comparison — it isolates what the agent *engineering* contributes rather
than what the model contributes.

**What it is:** both CSV files inline in a single prompt, same output schema,
same model (`claude-sonnet-5`), no tools, no iteration, no verification.

**Result**

| Metric | Value |
|---|---|
| Primary score | 0.925 |
| Detection accuracy | 100% |
| Localization (of detected) | 71.4% |
| Tokens per case | ~34,600 |
| Cost per case | ~$0.15 |

Evidence: `results/prompt_baseline_16.json`, `_raw/pb_*.json`

**What this told us:** the baseline is strong, not a strawman. On the original
12-case set it scored 0.975 and solved the dollars-to-cents case perfectly,
including the row-level arithmetic showing `2 x 483.94 = 967.88` against
`1 x 700.10 = 70010`.

**This finding forced a pivot** — see next entry.

---

## [2] Pivot — changing the measurement axis

**Observation that triggered it:** a baseline at 0.975 leaves at most 2.5%
accuracy headroom. Any amount of agent engineering layered on top would show a
negligible improvement, and reporting 0.975 -> 1.0 would be a meaningless
result no matter how good the underlying work was.

**Why the baseline scored so well:** 200-row files fit comfortably in context.
At that size there is no engineering problem to solve — the model reads both
files and reasons directly. The benchmark was too small to discriminate.

**Measured the actual constraint:**

| Rows | Both files | vs 1M context |
|---|---|---|
| 200 | ~8K tokens | 0.8% |
| 5,000 | ~199K tokens | fits, ~25x cost |
| 50,000 | ~2.0M tokens | **exceeds context** |
| 500,000 | ~20.3M tokens | 20x over |

**Decision:** keep the problem, the corpus and the scorer; change the axis
from accuracy alone to accuracy-under-scale. Generate the corpus at three
scales (S=200, M=5,000, L=50,000) and report accuracy, tokens, and whether the
run completes at all.

**Learning:** a benchmark that every approach passes is not measuring the thing
that matters. Scale was a hidden confound in our own evaluation, and it took a
baseline that was *too good* to expose it.

---

## [3] Iteration 1 — streaming profiler

**Why:** if raw rows cannot enter context at scale, the agent needs a
representation whose size is independent of row count.

**What was built:** `src/tools/profile.py`. Streams the file row by row holding
only counters, emitting a fixed-size statistical summary per column.

**Result**

| File size | Profile size | Ratio | Time |
|---|---|---|---|
| 16 KB (200 rows) | 5.0 KB | 3x | <1s |
| 4.26 MB (50,000 rows) | 5.3 KB | **806x** | 1s |

Profile size is a function of column count, not row count.

**Score on the original 12-case set: 0.950** at both S and L tier, versus the
baseline's 0.975 at S and outright failure at L. Tokens dropped from ~35,000 to
~19,300 per case, and stayed flat at ~19,400 at 250x the data.

Evidence: `results/agent_S.json`, `results/agent_L.json`

---

## [4] Iteration 1a — the profiler missed a defect

**Observation:** a signal-presence check across all 12 defect types found
**11 of 12** visible in the profile. `precision_loss` produced no signal at all.

**Root cause:** the injector rounds `967.88` to `968.00`. The decimal-place
histogram counts *digits after the point*, which is unchanged at 2. The real
signal is that the fractional part is now always zero, and nothing measured
that.

**Change:** added a `zero_fraction_rate` statistic — the proportion of numeric
values whose fractional part is zero.

**Result**

| Column | day1 | day2 |
|---|---|---|
| `amount` decimal_places | `{2: 50000}` | `{2: 50000}` (unchanged) |
| `amount` zero_fraction_rate | 0.0233 | **1.0** |

Signal check: 11/12 -> **12/12**.

**Learning:** profile statistics must be designed against the specific failure
modes you care about. Generic summary statistics silently miss semantic drift,
and the miss is invisible unless you test for signal presence explicitly.

---

## [5] Iteration 1b — adversarial cases exposed a structural blind spot

**Why:** the profiler is per-column by construction. That raises an obvious
question: what about a defect that breaks a relationship *between* columns
while leaving every individual column's statistics normal?

**What was added:** 4 cases (13–16). Three break a cross-column invariant; one
is a second clean control. Two are built by **shuffling** a column rather than
transforming it, which preserves its distribution exactly — same min, max,
mean, null rate, value set.

The corpus satisfies two invariants:
- `amount == quantity * unit_price`
- `email` prefix corresponds to `customer_name`

**Result — the defects are real:**

| Case | Rows violating the invariant |
|---|---|
| 13 amount_decoupled | 197/200 |
| 15 partial_arithmetic | 16/200 (8%) |
| 14 email_name_mismatch | 178/197 |
| 16 clean control | **0/200** on both |

**And invisible to marginal statistics:** the clean control showed marginal
differences of the *same magnitude* as the defective cases (natural sampling
variation between two independent draws). Marginals cannot separate them.

**Score on the extended 16-case set: 0.775** (down from 0.950 on 12). Cases 13,
14 and 15 all scored 0.0 — the agent reported "clean feed" on a file where 197
of 200 rows violated the arithmetic. Both controls were correctly clean, so the
system was not blind to everything, only to this specific class.

Evidence: `results/agent_S_extended.json`

**Learning:** our evaluation could not see what our instrumentation could not
see. The corpus only contained defects the profiler was designed to catch, so
the 0.950 was partly an artifact of the test set.

---

## [6] Iteration 2 — invariant discovery and verification

**Why:** cross-column defects need evidence about relationships, and that
evidence has to be obtainable without loading the whole file.

**What was built:** `src/tools/invariants.py`. Samples 300 rows via reservoir
sampling (bounded regardless of file size), **discovers** relationships holding
in the reference file, then re-tests those relationships on the candidate file.

Design decision: it discovers rather than being handed the invariants. On this
corpus it independently finds both — `amount == quantity * unit_price` and
`email contains a token from customer_name`, each at hold rate 1.0 — without
being told they exist.

**Result**

| Metric | Iteration 1 | Iteration 2 | Change |
|---|---|---|---|
| Primary score | 0.775 | **0.944** | **+21.8%** |
| Detection accuracy | 81.2% | **100%** | +18.8pp |
| Classification | 100% | 100% | — |
| False-positive rate | 0% | 0% | — |
| Tokens per case | ~19,300 | ~20,100 | **+4.1%** |

Evidence: `results/agentv2_S.json`, `_raw/agentv2_S_*.json`

**Unexpected corroboration:** the checker also fires on three cases it was not
built for — 07 (unit change breaks the arithmetic), 09 (precision loss breaks
it) and 10 (mojibake breaks the name-to-email link). Zero false positives on
either control.

---

## [7] Iteration 2a — root-cause classification

**Observation from the previous entry:** if broken invariants are reported for
cases 07, 09 and 10, the agent might classify those as
`cross_column_invariant_broken` and lose the more specific — and more
actionable — diagnosis.

**Change:** the prompt states that a broken invariant is often a *symptom* of a
more specific defect, and that `cross_column_invariant_broken` should be used
only when per-column profiles look normal and the relationship is the sole
change.

**Result:** cases 07, 09 and 10 were classified as `unit_change`,
`precision_loss` and `encoding_change` respectively, despite broken invariants
being in front of the agent. Classification accuracy 100%.

**Learning:** giving an agent more evidence can degrade its output if the
evidence is more salient than it is diagnostic. The instruction that ranks
evidence mattered as much as the tool that produced it.

---

## [8] Scale run — agent v2 at 50,000 rows

**Why:** verify that adding invariant checking did not break the scale property
that motivated the whole design.

**Result**

| Metric | S (200 rows) | L (50,000 rows) |
|---|---|---|
| Primary score | 0.944 | **0.963** |
| Detection accuracy | 100% | 100% |
| Localization (of detected) | 78.6% | **85.7%** |
| Tokens per case | ~20,100 | ~19,850 |

Evidence: `results/agentv2_L.json`

**Unexpected:** accuracy went *up* at scale. Larger samples make the profile
statistics more stable and the invariant hold rates more precise, so the
evidence the agent reasons over is cleaner. The baseline is rejected at this
size; the agent improves.

---

## Experiments considered and removed

| Experiment | Why tried | Why removed | What it taught |
|---|---|---|---|
| Memory of historical contracts across runs | Would let the agent know a column "was always float" | No measured failure required it. Two-file comparison already carries the reference state | Component count is not the goal; every added part should close a measured gap |
| Multi-agent orchestration | Separate profiler / diagnoser / verifier agents | Would have multiplied the ~27K fixed per-invocation overhead with no evidence of accuracy gain | Orchestration has a real token cost that must be justified by a measured benefit |
| Retry loop on low-confidence verdicts | Standard reliability pattern | Detection was already 100% after iteration 2; nothing to retry | A reliability mechanism with no failures to catch is dead weight |
| Loosening the scorer on 3 ambiguous cases | Would have lifted the score ~0.05 | Changing the metric after seeing results invalidates the comparison | Documented them as an eval limitation instead |

The last row is the one worth stating plainly: cases 01, 11 and 15 have
localization disagreements where the agent's answer is arguably as defensible
as the ground truth. Correcting the labels post hoc would have been rigging the
measurement, so the score stands at 0.944 with the ambiguity disclosed in
README section 7.
