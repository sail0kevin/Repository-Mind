# External code-location A/B v3

## Scope

This is a narrow, reproducible code-location experiment. It measures whether an
external Coding Agent can report manually annotated source locations while receiving
less raw source text through its tools. It does not measure full feature-development
quality, and it does not prove a universal Token reduction.

The target was one isolated local checkout of the user's AgentForge project, not a
set of unrelated public repositories. The evaluation was pinned to commit
`22f253b568980238334eec64e3a2b1eb10ddc163` and used a separate RepoMind database
and data directory.

## Conditions

| Item | Value |
| --- | --- |
| Target checkout | `G:\projects\agent-learning\benchmarks\agentforge-location-v1\checkout` |
| Target commit | `22f253b568980238334eec64e3a2b1eb10ddc163` |
| Indexed files / chunks | 211 / 3,790 |
| Tasks | 5 manually annotated two-location tasks |
| Retrieval mode | Lexical-only; no Embedding provider was configured |
| Baseline | Codex may use Git/PowerShell search and read commands |
| Treatment | Codex may use only the isolated RepoMind MCP server |

Each task passes only when the final answer reports every annotated relative path and
a line range covering every annotated start line. The task manifest, checkout binding,
snapshot binding, and index isolation are validated before the runner starts.

## Results

| Cohort | Passed tasks | Total input tokens | Output tokens | Source characters received |
| --- | ---: | ---: | ---: | ---: |
| Direct search baseline | 2 / 5 | 422,444 | 3,843 | 1,032,948 |
| RepoMind MCP, initial run | 3 / 5 | 399,563 | 6,388 | 112,971 |
| RepoMind MCP, short-snippet trial | 1 / 5 | 368,727 | 4,197 | 120,960 |

The initial MCP path completed one additional task. Tool-result source text was about
89% lower, while total input Token count was only about 5.4% lower. This gap is
important: repeated MCP calls, tool schemas, and model reasoning consume context too.
RepoMind therefore cannot honestly claim that it reduces total Token usage by 89%.

After the initial run, a short-snippet trial added up to eight lines of source to each
`locate_code` candidate to reduce follow-up queries. Its single treatment rerun passed
only 1/5 tasks and returned more source text than the initial MCP run. That trial was
removed from the default tool behavior rather than being presented as an optimization.
The two treatment runs are not a statistical comparison; they are a concrete reminder
that plausible context additions must be evaluated before becoming product claims.

| Task | Baseline | RepoMind MCP |
| --- | --- | --- |
| `workflow-routing` | Fail | Fail |
| `checkpoint-resume` | Fail | Pass in initial run; fail in short-snippet trial |
| `tool-idempotency` | Fail | Pass in initial run; fail in short-snippet trial |
| `human-approval-gate` | Pass | Pass |
| `run-budget-and-events` | Pass | Fail in both treatment runs |

## Interpretation and next step

- This run supports the product direction: indexed, bounded evidence can substantially
  reduce the source text an external Agent must inspect to locate code.
- It does not evaluate hybrid retrieval because the index ran in lexical-only mode.
- It does not establish generalization because there is one local repository, five
  tasks, and one run per cohort.
- The failure traces show that external Agents can make repeated location and search
  calls. A short-snippet attempt did not reliably improve that behavior, so the default
  tool stays compact while further changes are evaluated against fixed tasks.

Next, run the same protocol on 3-5 unrelated public repositories with 20-30 manually
annotated tasks, then add configured Embeddings and compare lexical-only against hybrid
retrieval under the same fixed conditions.

## Reproduction

```powershell
python .\scripts\validate_location_benchmark.py `
  --manifest G:\projects\agent-learning\benchmarks\agentforge-location-v1\agentforge-location.manifest.json

& .\scripts\run_codex_location_ab.ps1 `
  -Manifest G:\projects\agent-learning\benchmarks\agentforge-location-v1\agentforge-location.manifest.json `
  -McpBackendPath .\backend `
  -OutputDir e2e-artifacts\agentforge-location-v2 `
  -Mode all `
  -TimeoutSeconds 180 `
  -Force
```

Raw traces and the generated `results.json` are local artifacts and intentionally not
committed because they include target-repository source excerpts.
