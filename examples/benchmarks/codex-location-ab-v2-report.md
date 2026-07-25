# Codex code-location A/B v2

## What this measures

This experiment measures the cost for a Coding Agent to locate annotated source evidence in an unfamiliar repository. It does not measure full feature-development cost, and it does not claim a universal Token reduction.

Each task asks for two source locations. A run passes only when its final answer contains every expected repository-relative path and a line range covering every annotated start line.

- **Baseline:** Codex may use `git grep` and PowerShell search/read commands.
- **RepoMind MCP:** Codex may use only the isolated RepoMind MCP server. The task prompt disallows shell and local-file reads.

## Clean fixed conditions

| Item | Value |
| --- | --- |
| Target repository | Sparse, backend-only checkout of RepoMind |
| Target commit | `b4eacc5ba103fcbedff07a275ebd508595ee3c0b` |
| Indexed files | 137 |
| Tasks | 8 manually annotated two-location navigation tasks |
| Client | Codex CLI, one ephemeral session per task |
| RepoMind index | `repo_4815c06b3f9747c1a9a4ec80add738f2` / `snap_7ec1ccbea3827ec936ff5774e2242595f65330bdebf9a9982d37c7204ebbd962` |
| Retrieval mode | Lexical fallback; this index has no configured Embedding provider |

The sparse checkout contains `backend/` and root files only. It does not contain the benchmark task JSON, previous reports, or benchmark artifacts, so RepoMind cannot retrieve task wording or gold locations from files under test.

Both cohorts used the same unrestricted CLI process mode because the Windows read-only sandbox terminates local stdio MCP child processes. The restrictions above are prompt-enforced, not OS-enforced. This is a limitation of the experiment.

## Results

| Cohort | Passed tasks | Pass rate |
| --- | ---: | ---: |
| Direct search baseline | 4 / 8 | 50.0% |
| RepoMind MCP | 7 / 8 | 87.5% |
| Both cohorts passed | 4 / 8 | 50.0% |

Token and source-volume comparisons are calculated only for the four tasks both cohorts passed.

| Common-success tasks | Baseline input tokens | MCP input tokens | Change | Baseline received source text | MCP received source text | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `evidence-budget`, `main-agent`, `mcp-search`, `mcp-symbol` | 379,217 | 266,038 | -29.8% | 750,738 chars | 123,836 chars | -83.5% |

`source_characters_received` is computed from command output or MCP tool-result text in the Codex JSONL traces. It is a proxy for code/context volume, not a tokenizer billing metric.

## Interpretation

- In this small, clean run, RepoMind MCP completed three more location tasks than direct search.
- For the four tasks where both paths found the same annotated locations, RepoMind returned much less code text and used fewer total input tokens.
- The common-success set has only four tasks. Do not state that RepoMind "saves 29.8% Tokens" in a resume, README, or product claim. The defensible statement is: **an initial isolated A/B showed lower context volume on 4 comparable code-location tasks; broader validation is still required.**
- Total input tokens include client instructions, MCP schemas, reasoning, caching, and tool-result serialization. The large reduction in returned source text is closer to the product goal, but it is still a proxy rather than an end-user cost measurement.

## Failure review

| Task | Baseline | RepoMind MCP | Observation |
| --- | --- | --- | --- |
| `evidence-budget` | Passed | Passed | Bounded evidence lookup avoided broad file reading. |
| `evidence-assembler` | Missed final assembly line | Missed final assembly line | Both need a clearer wrapper-versus-call-site signal. |
| `route-question` | Missed trace line | Passed | MCP evidence included the complete route-and-trace flow. |
| `main-agent` | Passed | Passed | Cross-file wrapper and specialist implementation were both located. |
| `mcp-search` | Passed | Passed | The original gold used the `HybridRetriever` class line; the task asks for its invoked entry point, so the annotated line was corrected to `retrieve()` at line 62. |
| `mcp-symbol` | Passed | Passed | Symbol lookup is a strong bounded-context case. |
| `mcp-impact` | Missed both gold lines | Passed | Static relation data helped bridge the public MCP tool and its implementation. |
| `mcp-tests` | Missed specialist implementation | Passed | MCP found the public tool and the test-candidate helper without running the target repository. |

## Reproduction

The raw JSONL traces and machine-readable table are intentionally ignored local artifacts under `e2e-artifacts/codex-location-ab-b4eacc5-backend-only/`.

```powershell
& .\scripts\run_codex_location_ab.ps1 `
  -RepoId 'repo_4815c06b3f9747c1a9a4ec80add738f2' `
  -SnapshotId 'snap_7ec1ccbea3827ec936ff5774e2242595f65330bdebf9a9982d37c7204ebbd962' `
  -McpName 'repomind-location-backend-only-b4eacc5' `
  -Commit 'b4eacc5ba103fcbedff07a275ebd508595ee3c0b' `
  -RepositoryPath '.\e2e-artifacts\token-ab\repo-backend-only-b4eacc5' `
  -McpBackendPath '.\backend' `
  -McpDatabasePath '.\backend\e2e-artifacts\codex-location-ab-backend-only-b4eacc5-data\repomind.sqlite3' `
  -McpDataDir '.\backend\e2e-artifacts\codex-location-ab-backend-only-b4eacc5-data' `
  -OutputDir 'e2e-artifacts\codex-location-ab-b4eacc5-backend-only' `
  -Mode all
```

## Next validation step

Build a 20-30 task evaluation over 3-5 external open-source repositories, pin every task to a commit, manually annotate expected paths and lines, and rerun each cohort with a fixed client/model configuration. Report task success and cost only on common-success tasks, including failures instead of reporting a best-case average. The repository now includes an [external evaluation protocol](EXTERNAL_CODE_LOCATION_PROTOCOL.md), an example manifest, and a preflight that rejects mismatched checkouts, snapshots, and implicit user-level indexes before Codex starts.
