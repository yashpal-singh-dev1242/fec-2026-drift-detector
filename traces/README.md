# Agent Trajectories

Five representative session transcripts, in Claude Code's native JSONL format,
copied unedited from `~/.claude/projects/`. Each corresponds to a specific run
whose raw API response is committed in `_raw/`, so any trace can be matched to
the exact prediction and token count it produced.

## Architecture note — read this first

The workflow is **deterministic tools feeding an LLM reasoner**, not an agent
that decides when to call tools. `run_agent_v2.sh` invokes `profile.py` and
`invariants.py` inside Docker, and their JSON output becomes the evidence in
the agent's prompt. The agent reasons over that evidence and emits a verdict
constrained by a JSON schema.

This is a deliberate design decision, not a limitation. Deterministic
preprocessing is *why* the system is scale-independent: profiling always
happens exactly once per file and costs a fixed number of tokens. Letting the
agent decide when to profile would add round trips and tokens without adding
accuracy, since every case needs the same evidence.

The consequence for these traces: the only tool call you will see is
`StructuredOutput`, which enforces the verdict schema. Tool invocations for
profiling and invariant checking are in `run_agent_v2.sh`; their outputs appear
verbatim inside the prompt at the top of each trace, and are also written to
`_profiles/<SCALE>/<case>/`.

## What each trace contains

| Element | Where | Notes |
|---|---|---|
| Agent instructions | line 3, `user` message | Full prompt including both profiles and the invariant report |
| Agent reasoning | `assistant` / `text` block | Narrative diagnosis with an evidence table |
| Tool call | `assistant` / `tool_use` | `StructuredOutput` with the final verdict |
| Tool response | `user` / `tool_result` | Confirmation the structured output was accepted |
| Thinking block | `assistant` / `thinking` | **Present but empty** — the API returns a signature without content, so no interior reasoning is recoverable here. The visible `text` block carries the reasoning instead. |

There are no retries or human checkpoints in these traces. Each run is a single
non-interactive invocation (`claude -p`) that succeeded on the first attempt.
Human approval gates exist in the interactive development sessions, not in the
evaluation runs.

## The traces

### `01-v1-case13-blindspot.jsonl`
**Agent v1 (profiling only) on case 13 — the documented failure.**

The agent receives per-column profiles for a file where 197 of 200 rows violate
`amount = quantity × unit_price`, and reports a clean feed. This is not a
reasoning error: the profiles genuinely contain no evidence of the defect,
because a shuffled column has an identical distribution.

Backs: README section 7, changelog entry [5]. Scored 0.0.

### `02-v2-case13-invariant-catch.jsonl`
**Agent v2 on the same case — the fix.**

Same file, same model. The prompt now also carries the invariant report. The
agent's reasoning contains:

```
| amount == quantity * unit_price hold rate | 1.000 | 0.015 |
| email contains a token from customer_name | 1.000 | 1.000 (still holds) |
```

A 0.015 hold rate is 3 of 200 rows, matching the generator's 197/200 injected
violations exactly — the corpus and the detection agree independently. The
agent also argues why this is a root cause rather than a symptom: the
arithmetic collapsed while the second discovered invariant is untouched.

Backs: changelog entry [6], the 0.775 -> 0.944 improvement. Scored 1.0.

### `03-v2-case07-root-cause.jsonl`
**Root-cause classification under pressure.**

Case 07 is the dollars-to-cents change. Because it also breaks the arithmetic
invariant, the invariant report shows a broken relationship — the tempting
wrong answer. The agent classifies it as `unit_change`, using the invariant
break as corroboration rather than diagnosis.

Backs: README section 3, design choice 3; changelog entry [7].

### `04-v2-case07-at-50k-rows.jsonl`
**The same case at 250x the data.**

Identical structure and comparable token count (~19,850 vs ~20,100) despite
each input file being 4.26 MB. Demonstrates the scale property: the evidence
the agent sees is the same size regardless of file size.

Backs: README section 4, changelog entry [8].

### `05-v2-control-no-false-positive.jsonl`
**A clean feed, correctly reported clean.**

Included because detection accuracy is meaningless without it. A system that
flags everything scores perfectly on recall. Both controls are clean across
every configuration tested; the false-positive rate is 0%.

Backs: README section 5.

## Mapping traces to raw responses

| Trace | `_raw/` file | Session ID |
|---|---|---|
| 01 | `agent_S_13_amount_decoupled.json` | `79437d98-f9b6-4a57-b2b1-9ada2e863c41` |
| 02 | `agentv2_S_13_amount_decoupled.json` | `a3b11e5f-8924-4dd6-ad07-499ce83fe304` |
| 03 | `agentv2_S_07_unit_change_currency.json` | `1a6649c1-26f7-4f1e-92eb-e7fb44f09a7d` |
| 04 | `agentv2_L_07_unit_change_currency.json` | `636db775-9b39-4367-9ff8-33871256f85b` |
| 05 | `agentv2_S_12_control_no_defect.json` | `06c0e1a2-af67-432a-8729-1b29060b8d22` |

## Tools disclosed

| Tool | Version | Role |
|---|---|---|
| Claude Code | 2.1.250 | Runs the evaluated workflow: `--model sonnet`, `--output-format json`, `--json-schema`, all file/shell/network tools denied via `--disallowedTools` |
| Claude Code | 2.1.250 | Development assistance during the build |

The evaluation runs execute with `Bash`, `Read`, `Write`, `Edit`, `Glob`,
`Grep`, `WebSearch`, `WebFetch` and `Task` all explicitly denied. The agent
receives evidence and returns a verdict; it cannot read or modify the feed
files, the corpus, or anything else on disk.

## Selection and privacy

81 sessions were recorded during development. These five were chosen because
they map to specific claims in the README and changelog. The full set is not
included — the deliverable asks for representative trajectories, and one
transcript alone is 17 MB (the failed L-tier baseline attempt, which buffered
8.5 MB of CSV before the API rejected it).

All five were scanned for credentials, bearer tokens, API keys and real email
addresses before committing. No secrets are present. Synthetic email addresses
use the reserved `example.com` domain.
