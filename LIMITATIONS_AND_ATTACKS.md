# Limitations and Anticipated Objections

Written before submission, not in response to feedback. Every objection below
is one I raised against my own work. Where the honest answer is "yes, that is a
real limitation," it says so rather than reframing it.

---

## 1. "Tools like Great Expectations and Soda already do this."

**Partly true, and the difference is the point.**

Great Expectations, Soda, Deequ and Anomalo are mature and in many ways more
capable than this. But they check rules **you wrote in advance**:

    expect_column_values_to_be_between("amount", 0, 10000)
    expect_column_values_to_not_be_null("email")

That works for the failure modes you anticipated. The Monday-morning problem is
the one you did not anticipate. Nobody writes
`expect_amount_to_equal_quantity_times_unit_price` before the day it breaks.

This system **discovers** the invariant from yesterday's file and re-tests it
against today's. No rule is authored in advance. On this corpus it independently
finds `amount == quantity * unit_price` and `email contains a token from
customer_name` without being told either exists.

The honest scope: rule-based tools are better where you know what to check. This
is aimed at the gap where you do not.

---

## 2. "Your agent isn't really agentic — it's a preprocessor plus a classifier."

**Fair, and it is a deliberate choice rather than an oversight.**

The pipeline is: deterministic tools produce evidence, the agent reasons over it
and emits a schema-constrained verdict. The agent does not decide when to call
the profiler.

Why it was built that way: profiling always has to happen, for every file, on
every run. Letting the agent choose whether to profile adds round trips and
tokens without adding information — every case needs the same evidence. Fixed
preprocessing is precisely what makes token cost flat at any scale, which is the
project's central claim.

What that costs: the trajectories show reasoning rather than tool orchestration.
A reactive loop — agent forms a hypothesis, requests targeted inspection,
revises — would produce richer traces and is the obvious next iteration. It is
not in this submission because it was not measured, and shipping an unmeasured
architecture change would undermine every number in the results table.

---

## 3. "Your benchmark is synthetic."

**True.** Synthetic data is used because it gives exact ground truth — the
defect type, affected columns and severity are known by construction, so scoring
requires no human judgment.

The cost is realism. Real feeds are messier, and defect prevalence in production
is unknown. This corpus measures whether the system detects defects it is shown;
it does not measure how often those defects occur in the wild.

---

## 4. "The profile statistics were designed against your own defect taxonomy."

**True, and stated in README section 7.**

`zero_fraction_rate` was added specifically because `precision_loss` was
invisible to the original statistics. That is instrumentation designed against a
known failure mode.

The mitigation is partial, not complete: the invariant checker *discovers*
relationships rather than being handed them, so it generalises beyond the
specific invariants in this corpus. The per-column profile does not. A defect
class mapping to none of the collected statistics would be invisible — exactly
as cross-column breaks were until they were added.

---

## 5. "The direct prompt is more accurate at small scale."

**True: 0.925 vs 0.944 overall, but the baseline was ahead of agent v1 (0.775)
and remains competitive.**

The claim made here is not "the agent is smarter." It is comparable-to-better
accuracy at 42% fewer tokens, and the only one of the two that runs at
realistic feed size.

---

## 6. "42% fewer tokens is misleading."

**Worth unpacking, because the raw figure hides a fixed cost.**

Each Claude Code invocation carries roughly 27,000 tokens of fixed overhead —
system prompt, tool definitions, skill listings — before any content. That
overhead applies to both systems equally, which compresses the apparent
difference.

Three separate numbers, rather than one:

| Measure | Baseline | This system |
|---|---|---|
| Data representation sent to the model | full CSV (4.26 MB at L tier) | ~5 KB profile |
| Data compression | none | 806x |
| End-to-end tokens per case | ~34,600 | ~20,100 |

The end-to-end figure (42%) is the honest headline because it is what a user
pays. The 806x is the architectural claim. The scaling behaviour matters more
than either: the baseline grows with row count and hits a wall; this stays flat.

---

## 7. "Your localization ground truth is ambiguous."

**True for three of sixteen cases, and the scorer was not adjusted.**

- Case 01: the agent names the *new* column after a rename; ground truth names
  the old one. Both defensible.
- Case 11: duplicates attributed to whole rows rather than the key column.
- Case 15: partial arithmetic drift, disputed column set.

Loosening the definition after seeing results would have gained roughly 0.05.
It was not done, because changing a metric after observing outcomes invalidates
every comparison made with it. The score stands at 0.944 with the ambiguity
disclosed.

---

## 8. "The agent could be hallucinating a plausible story from the profiles."

**Tested, and this is what the adversarial cases exist for.**

Cases 13–15 have per-column statistics indistinguishable from the clean
controls. Agent v1, working from profiles alone, reported a clean feed on a file
where 197 of 200 rows violated the arithmetic — correct reasoning over evidence
that did not contain the answer.

Both clean controls stayed clean across every configuration, so the system is
not simply pattern-matching toward "something must be wrong." The false positive
rate is 0% throughout.

---

## 9. "Only CSV. Only two files. Only 50,000 rows."

**All true.**

No Parquet, JSON, or streaming sources. Comparison is pairwise
(reference vs candidate), not a rolling history. Scale was tested to 50,000 rows
per file; behaviour beyond that is extrapolation, not measurement. The claim
made is "constant on our 50,000-row evaluation," not "works at any size."

---

## 10. "Agent runs are not deterministic, so your score is not reproducible."

**True, and disclosed in REPRODUCTION.md section 9.**

A live re-run will land near 0.944, not exactly on it. This was observed
directly: re-running case 13 produced a different column set and would have
scored 0.7 instead of 1.0.

Everything else *is* deterministic — corpus generation, the schema baseline,
the profiler, the invariant checker, and scoring. The committed predictions and
their raw API responses are the record of what was measured, which is why all 77
unedited responses are in the repo.

---

## What would change my mind about this design

If the reactive-loop version measurably beat this one, the fixed-preprocessing
argument in section 2 would be wrong and I would say so. That experiment has not
been run, so the claim here is bounded: fixed preprocessing is what makes the
cost flat, not that agent-controlled acquisition could not do better.
