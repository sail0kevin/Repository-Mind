# MCP Token Savings Evaluation Protocol

This protocol measures a scoped product claim: how many externally reported Coding
Agent tokens RepoMind MCP saves on matched repository-understanding tasks. Retrieval
Recall/MRR and returned-source character counts are useful diagnostics, but neither is
evidence of model Token savings.

## Experimental Unit

Each task/run pair has two fresh, ephemeral Agent sessions against the same clean,
pinned target-repository commit:

- **Baseline:** Agent may use its ordinary repository search and file-reading tools;
  RepoMind MCP is unavailable.
- **MCP treatment:** Agent may use only a temporary RepoMind MCP server bound to the
  indexed snapshot; local source reads and shell search are unavailable.

Before the external comparison, run a three-profile pilot on the same frozen tasks:
baseline, the existing detailed MCP response, and `locate_code(compact=true)`. The
compact profile must preserve the detailed profile's rubric pass rate before it is
used as the treatment. For ordinary location questions, its prompt must instruct the
Agent to call `locate_code` once with `compact=true` and answer directly from the
returned locations; `search_code` is only available when a narrow source excerpt is
necessary. Record the exact MCP profile and tool instructions in run metadata.

For the compact treatment, prefer `python -m service.mcp_server --profile coding-agent`
with `REPOMIND_MCP_REPO_ID` and `REPOMIND_MCP_SNAPSHOT_ID` supplied only in the
temporary server environment. This profile exposes exactly one tool,
`locate_code(question, limit?)`, and binds it to the isolated manifest snapshot. The
reporter treats `mcp_profile` as a comparable run condition and rejects batches that
mix detailed and compact profiles.

Keep the target commit, task wording and answer rubric, model, client version,
reasoning effort, process/sandbox mode, time limit, and answer limit identical. Run at
least 20 tasks across at least 3 unfamiliar repositories, and repeat each condition
independently when the client is stochastic.

For a location task, `expected_locations` means every annotated location is required.
When a source language exposes semantically interchangeable declarations and concrete
implementations, a versioned task set may instead use `acceptable_location_groups`:
every group is required, but one reported location from that group is sufficient. The
task set must state its scoring-policy version and why the alternatives are equivalent.
Never alter a published task set or historical result to apply a new policy; create a
new task-set version and report it as a new cohort.

Every run must include a non-empty `repeat_id` in `run-metadata.json`. A formal
publishable conclusion requires at least 3 benchmark repositories, 20 task/run pairs,
20 both-passed tasks, and 2 independent repeat IDs. The MCP treatment pass rate must
be at least the baseline pass rate. A report may still be generated when these gates
fail, but its status must be `not_accepted` and its Token percentage is diagnostic
only, not a product claim.

## Required Evidence

Use `scripts/run_codex_location_ab.ps1` with an isolated manifest-bound index. It
writes one `results.json` row per cohort/task and `run-metadata.json` for the run.
Successful rows must contain:

- `input_tokens` and `output_tokens` parsed from the Agent's completed-turn usage;
- `usage_provenance: codex_exec_json.turn.completed`;
- `raw_trace_sha256` of the raw JSONL trace;
- a task pass/fail result evaluated against the pre-written rubric.

Never estimate Tokens from character length, tool calls, model pricing, or RepoMind
logs. Do not include secrets, target source, absolute paths, user databases, or raw
transcripts in committed captures.

## Aggregate

Create a batch file such as:

```json
{
  "batch_id": "external-token-savings-v1",
  "runs": [
    {
      "benchmark_id": "repository-a-run-1",
      "results": "repository-a/run-1/results.json",
      "metadata": "repository-a/run-1/run-metadata.json"
    }
  ]
}
```

Then generate both machine-readable and human-readable reports:

```powershell
python .\scripts\report_mcp_token_savings.py `
  --batch C:\benchmarks\external-token-savings-v1.json `
  --output C:\benchmarks\external-token-savings-v1.summary.json `
  --markdown-output C:\benchmarks\external-token-savings-v1.summary.md
```

The reporter rejects missing pairs, duplicate cohort/task rows, missing usage
provenance, missing trace hashes, and differences in client version, model, reasoning
effort, sandbox mode, or target commit. Its primary input/output/total Token comparison
includes **only tasks passed by both cohorts**. It separately reports cohort pass rates
and source-character change, with the latter labelled as a context-volume proxy.

It also emits `failure_classes` and `statuses`, including whether a timeout happened
before MCP, after MCP but before a final answer, or during an incomplete run. The
acceptance object is a machine-readable gate: `accepted` means the report satisfies
the sample, repeat, and quality requirements above; `not_accepted` means the report
must not be used to advertise Token savings.

## Claim Language

Only state a saving after a real report exists. State the Agent/client version, model,
reasoning effort, target repositories, task count, both-pass count, and whether runs
were repeated in the same sentence as the result. A valid conclusion is, for example:

> Under the stated benchmark conditions, RepoMind MCP changed external Agent total
> Token use by X% on N/N tasks completed by both cohorts; baseline and MCP pass rates
> were B% and M%.

Do not claim a universal saving. Report zero or negative savings exactly as measured.
