# Silent Data Contract Drift Detector

An agentic workflow that catches the feed changes your schema validator says
are fine.

**Headline result:** a direct-prompt baseline scores 0.925 on 200-row files and
is rejected outright at 50,000 rows. This system scores 0.944 at 200 rows and
**0.963 at 50,000 rows**, using 42% fewer tokens.

---

## 1. The user and the bottleneck

This is for the data engineer at a growing company who gets bludgeoned on
Monday mornings because an external API or partner feed quietly changed a
column name or format over the weekend. They spend the first half of their
morning putting out fires, fixing bad downstream syncs, and explaining to
non-technical leads why the weekend revenue reports look completely broken.

The reason this keeps happening is that the tooling is watching the wrong
thing. Schema validation checks that the file still *parses*: right columns,
right types, no nulls where nulls are forbidden. It cannot see a feed where
`amount` silently switched from dollars to cents, because integers are still
integers. Every downstream number is 100x wrong and every check is green.

Measured on this project's 16-case corpus, a conventional schema validator
catches **5 of 14** defects. The other 9 pass silently.

**What "solved" looks like:** by the time the engineer opens their laptop,
they already have a report saying which column changed, what kind of change it
was, how severe it is, and the evidence behind it — for feeds of any size.

---

## 2. What the system does

Two daily files go in — yesterday's feed and today's. A drift report comes out:
whether the feed drifted, which columns are affected, the kind of drift, its
severity, and the reasoning.

The core constraint that shapes everything: **raw rows never enter the model's
context.** Two deterministic tools compress the files into evidence, and the
agent reasons over that evidence. This is what makes the system independent of
file size.

---

## 3. Agent architecture and design decisions

### Why not just show the model the data?

That was the baseline, and at small scale it works well — 0.925. It stops
working at 50,000 rows per file:

```
input: 4,258,094 bytes + 4,267,789 bytes  (~2.1M tokens)
model: claude-sonnet-5 (1M token context)
result: {"is_error": true, "result": "Prompt is too long",
         "terminal_reason": "blocking_limit"}
exit code 1, 116ms, $0.00
```

Captured verbatim in `results/evidence/baseline_L_attempt.json`. Not slower —
refused. 50,000 rows is a mid-size B2B partner feed, not an extreme case.

### Design choice 1 — a streaming profiler (`src/tools/profile.py`)

Reads the file row by row, holding only counters. Emits a fixed-size
statistical summary: dtype, null rate, distinct count, numeric min/max/mean,
a decimal-place histogram, a zero-fraction rate, top-k values, date-format
counts, non-ASCII rate, and duplicate-row count.

| File | Profile | Ratio |
|---|---|---|
| 16 KB (200 rows) | 5.0 KB | 3x |
| 4.26 MB (50,000 rows) | 5.3 KB | **806x** |

Profile size is a function of column count, not row count. That single
property is why token cost stays flat at ~20k regardless of scale.

**The statistics are not generic.** Each one targets a specific failure mode —
numeric magnitude catches unit changes, zero-fraction rate catches precision
loss, top-k values catch enum drift. A generic "describe the columns" summary
does not surface semantic drift. This is disclosed deliberately: the profile
was designed against a known defect taxonomy, and section 7 covers what that
means for generalization.

### Design choice 2 — invariant discovery and verification (`src/tools/invariants.py`)

Profiles are per-column and therefore blind to relationships *between*
columns. This tool samples 300 rows (bounded, regardless of file size),
**discovers** relationships that hold in yesterday's file, then re-tests those
same relationships against today's.

It is not told which relationships to expect. On this corpus it independently
finds:

```
amount == quantity * unit_price          ref_hold_rate 1.0
email contains a token from customer_name ref_hold_rate 1.0
```

### Design choice 3 — root-cause instruction

Broken invariants are often a *symptom* of a more specific defect. A unit
change from dollars to cents also breaks `amount = quantity × unit_price`.
Without guidance the agent would classify these as invariant breaks and lose
the real diagnosis.

The prompt instructs it to use invariant evidence as corroboration and
classify by root cause. **This was tested, not assumed:** cases 07
(unit_change), 09 (precision_loss) and 10 (encoding_change) all report broken
invariants, and the agent classified all three by their root cause instead.
Classification accuracy is 100%.

### Design choice 4 — bounded, controlled execution

The agent runs with all file, shell and network tools explicitly denied
(`--disallowedTools "Bash Read Write Edit Glob Grep WebSearch WebFetch Task"`).
It receives evidence and returns a verdict. It cannot touch the feed files, the
evaluation corpus, or anything else. Data access happens only through the two
deterministic tools, in a container, read-only in effect.

Output is constrained by a JSON schema passed to the CLI, so a malformed
verdict is impossible rather than merely unlikely.

### What was deliberately not built

Memory across runs, multi-agent orchestration, and a retry loop were all
considered and dropped. The PDF is explicit that purposeful choices matter more
than component count, and none of these addressed a measured failure. Adding
them would have produced a more elaborate diagram and no better numbers.

---

## 4. Baseline comparison

All systems evaluated on the same 16 cases with the same scorer.

| System | Score | Detection | Tokens/case | Cost/case | At 50k rows |
|---|---|---|---|---|---|
| Schema validator (no LLM) | 0.419 | 43.8% | 0 | $0.00 | works, 0.419 |
| Direct prompt (baseline) | 0.925 | 100% | ~34,600 | ~$0.15 | **rejected** |
| Agent v1 — profiling | 0.775 | 81.2% | ~19,300 | ~$0.06 | works |
| Agent v2 — + invariants | 0.944 | 100% | ~20,100 | ~$0.06 | works |
| **Agent v2 at 50k rows** | **0.963** | **100%** | **~19,850** | **~$0.065** | — |

**On baseline fairness.** The primary baseline is a direct prompt with the full
contents of both files and the same output schema, per the challenge's own
list of acceptable baselines. It is not a strawman: it scores 0.925 and beats
agent v1. The schema validator is included as a second reference because it
represents what teams actually run in production today.

**The honest summary:** at small scale the direct prompt is a real competitor.
The system wins on cost (42% fewer tokens), wins narrowly on accuracy, and is
the only one of the two that runs at realistic feed sizes.

### Where the accuracy difference comes from

Both reach 100% detection and 100% classification. The entire gap is
localization — 78.6% vs 71.4% — because the invariant checker names the exact
columns in a broken relationship, while the baseline is inferring from raw rows.

### Accuracy improves with scale

0.944 at 200 rows, **0.963 at 50,000 rows**. Larger samples make the statistics
more stable and the invariant hold-rates more precise, so the evidence gets
cleaner. The two approaches scale in opposite directions.

---

## 5. Primary metric

**Composite score per case**, averaged over all 16:

- 0.0 — detection wrong (missed a defect, or false-alarmed on a clean control)
- 1.0 — correctly identified a clean control
- 0.4 + 0.3 x (columns correct) + 0.3 x (defect type correct) — detected defect

Detection is weighted heaviest because for this user a missed defect means
corrupted reporting, while an imprecise-but-flagged defect still triggers
investigation.

Reported alongside: recall on defects, recall on schema-invisible defects,
**false-positive rate on clean controls**, localization, classification.

Two of the 16 cases are clean controls. Without them, a system that flagged
everything would score 100% on recall. Both baselines and both agent versions
hold a 0% false-positive rate.

---

## 6. Improvement changelog

See [`IMPROVEMENT_CHANGELOG.md`](IMPROVEMENT_CHANGELOG.md) for the full record.
Summary of the arc:

| Stage | What changed | Score | Learning |
|---|---|---|---|
| Baseline | Schema validator | 0.419 | 9 of 14 defects are invisible to schema checks |
| Baseline | Direct prompt, full files | 0.925 | Strong at 200 rows; **fails outright at 50k** |
| Pivot | Changed the measurement axis | — | Accuracy alone had no headroom; scale was the real problem |
| Iter 1 | Streaming profiler | 0.775 | 806x compression; flat cost at any scale |
| Iter 1a | Added zero-fraction-rate stat | — | Precision loss was invisible: 968.00 still has 2 decimal places |
| Iter 1b | Added 4 adversarial cases | 0.775 | **Cross-column defects are completely invisible to profiling** |
| Iter 2 | Invariant discovery + verification | **0.944** | +22% score for +4% tokens |
| Scale | Agent v2 at 50,000 rows | **0.963** | Accuracy improves with scale |

---

## 7. Main failure mode and limitations

**The profile is designed against a known defect taxonomy.** Every statistic
targets a failure mode in this corpus. A defect class that maps to none of them
would be invisible, exactly as cross-column breaks were until they were added.
The invariant checker mitigates this — it discovers relationships rather than
being handed them — but the honest position is that this system's coverage is
bounded by its instrumentation, and its instrumentation was designed with
knowledge of the test set.

**Three ground-truth ambiguities.** Cases 01, 11 and 15 have localization
disagreements where the agent's answer is arguably as defensible as the label.
Case 01 names the *new* column after a rename; ground truth names the old one.
Case 11 attributes duplicates to whole rows rather than the key column. These
were **not** corrected after seeing results — loosening the scorer post hoc
would invalidate the comparison. They are reported as an eval limitation and
cost the system roughly 0.05.

**Invariant discovery is limited to three arithmetic forms and one referential
form.** Richer relationships — conditional invariants, time-series continuity,
referential integrity across files — are not detected.

**Sampling is probabilistic.** 300 rows detects the 8%-prevalence case
reliably, but a defect affecting well under 1% of rows could be missed.

**Agent runs are non-deterministic.** Committed predictions and their raw API
responses are the record; a live re-run will land near, not exactly on, the
reported scores.

---

## 8. Hot take

The shuffled columns being invisible to statistical profiling was the real
eye-opener. Standard tools look at columns in isolation — if the data types,
null counts and averages match, they mark it green even when the row-level
logic is completely ruined.

What I didn't expect was that adding an LLM on top didn't help either. My
profiling agent read those same statistics and confidently reported a clean
feed, on a file where 197 of 200 rows violated `amount = quantity × unit_price`.
The model wasn't reasoning badly — it was reasoning correctly about evidence
that didn't contain the answer.

The fix wasn't a smarter model or a better prompt. It was deterministic code
that sampled 300 rows and tested whether yesterday's relationships still held.
That took the score from 0.775 to 0.944 for a 4% increase in tokens.

What I'd take into the next agent I build: when an agent is confidently wrong,
check what you're feeding it before you touch the prompt. Most of my instinct
was to rewrite instructions. The actual problem was that the evidence was
blind, so the agent was too.

---

## 9. Running it

Full instructions: [`REPRODUCTION.md`](REPRODUCTION.md)

```bash
bash run.sh verify          # reproduces every number above. Docker only, $0.00
./run.sh agent-v2 S         # live agent run (needs Claude Code, ~$1)
```

The verification path needs no API key and no subscription.

---

## 10. Coding agents used

| Tool | Version | Used for |
|---|---|---|
| Claude Code | 2.1.250 | The workflow under evaluation (`--model sonnet`, tools denied, JSON-schema-constrained) |
| Claude Code | 2.1.250 | Development assistance during the build |

Representative trajectories: [`traces/`](traces/). Raw unedited API responses
for every evaluation run: [`_raw/`](_raw/) — 77 files with token counts, costs
and timings, so the results table can be audited without re-running anything.

---

## 11. Background IP

All code in this submission was written during the hackathon window
(Aug 28–31, 2026). No pre-existing personal or third-party code was
incorporated.

Data is fully synthetic, generated from a fixed seed by `eval/gen_cases.py`.
No real, scraped, or third-party data. Email addresses use the reserved
`example.com` domain.

Third-party components: see [`LICENSES.md`](LICENSES.md).

---

## 12. Evidence index

| Claim | Evidence |
|---|---|
| Schema validator scores 0.419 | `results/schema_baseline_16.json` |
| Direct prompt scores 0.925 | `results/prompt_baseline_16.json` |
| Agent v1 scores 0.775 | `results/agent_S_extended.json` |
| Agent v2 scores 0.944 | `results/agentv2_S.json` |
| Agent v2 scores 0.963 at 50k rows | `results/agentv2_L.json` |
| Baseline is rejected at 50k rows | `results/evidence/baseline_L_attempt.json` |
| Per-run token counts and costs | `_raw/*.json` (77 files) |
| Corpus is deterministic | `bash run.sh verify` prints `csv sha256: 931dfa2524951ebb` |
| Profiler compresses 806x | `src/tools/profile.py`; sizes in section 3 |
| Invariants are discovered, not hardcoded | `src/tools/invariants.py`, `discover()` |
