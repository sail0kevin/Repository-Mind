# Codex code-location A/B v2

## Question

This experiment measures the cost for a Coding Agent to locate annotated source evidence in an unfamiliar repository. It does not measure full feature-development cost or claim a universal Token reduction.

The two cohorts receive the same natural-language location task at the same repository commit:

- **Baseline:** Codex may use `git grep` and PowerShell search/read commands. RepoMind MCP is disabled.
- **RepoMind MCP:** Codex may only use the `repomind-location` MCP server. Shell and local-file reads are disallowed by the task prompt.

Every task requires two annotated locations. A result passes only when the final answer includes both repository-relative paths and a line range covering each gold line.

## Fixed Conditions

| Item | Value |
| --- | --- |
| Target repository | RepoMind backend and MCP implementation |
| Repository commit | `904ac6a7cbcfdce4a0b992d99966da54af09061a` |
| Tasks | 8 manually annotated, two-location code-navigation tasks |
| Client | Codex CLI, ephemeral session per task |
| RepoMind index | `snap_370f33b4516b1aedc7cee92717a4795fc21968a3bf65a2e8268cd1e0b398b36d` |
| Retrieval mode | lexical fallback; no Embedding was configured for this snapshot |

Both cohorts used the same unrestricted CLI process mode because the Windows `read-only` sandbox cancels local stdio MCP child processes. The baseline MCP server was explicitly disabled, while the RepoMind cohort was instructed to use only the MCP tools. This keeps the client runtime equal but is weaker than OS-enforced tool isolation.

## Result Summary

| Cohort | Passed tasks | Pass rate |
| --- | ---: | ---: |
| Direct search baseline | 2 / 8 | 25.0% |
| RepoMind MCP | 5 / 8 | 62.5% |
| Both cohorts passed | 1 / 8 | 12.5% |

The only common successful task was `mcp-symbol`.

| Common-success task | Baseline input tokens | MCP input tokens | Change | Baseline received source text | MCP received source text | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `mcp-symbol` | 189,739 | 46,911 | -75.3% | 397,399 chars | 15,485 chars | -96.1% |

`source_characters_received` is calculated from command output or MCP result text in the Codex JSONL trace. It is a proxy for source/context volume, not a tokenizer billing metric.

## Interpretation

The result is useful as an engineering signal, not as a resume-level performance claim:

- RepoMind MCP returned correct evidence on three tasks where direct search did not complete both locations: `evidence-budget`, `mcp-impact`, and `mcp-tests`.
- In the one task both cohorts completed, the MCP route returned substantially less source text and lower total input tokens.
- The sample is too small, and the common-success set is only one task. Do **not** write "RepoMind reduces Token cost by 75.3%" in a resume or README.
- Total input tokens include model instructions, MCP schemas, reasoning, caching, and tool-result serialization. Source-text volume is closer to the product goal of reducing repeated code reading, but it is still only a proxy.

## Failure Review

| Task | Baseline | RepoMind MCP | Observation |
| --- | --- | --- | --- |
| `evidence-budget` | Missed the assembly location | Passed | MCP symbol lookup found both the budget definition and `EvidenceAssembler.assemble`. |
| `evidence-assembler` | Missed the second line | Missed the second line | Both agents found the per-tool cap but confused the final assembly call with the assembler implementation. |
| `route-question` | Reported a range starting after the gold trace line | Passed | MCP returned the full `run_main_agent` definition containing the trace initialization. |
| `main-agent` | Passed | Returned the MCP wrapper instead of the underlying specialist implementation | Current lexical retrieval/symbol resolution cannot reliably distinguish wrapper and implementation layers. |
| `mcp-search` | Missed the retrieval entry line | Missed the retrieval entry line | Both cohorts located the MCP wrapper but not the intended construction/entry point. Gold labels need a clearer semantic boundary or more precise task wording. |
| `mcp-symbol` | Passed | Passed | The only valid paired cost comparison in this run. |
| `mcp-impact` | Missed both gold starting lines | Passed | MCP-oriented structure and symbol lookup helped identify both layers. |
| `mcp-tests` | Returned the wrapper module instead of implementation | Passed | MCP located the public tool and its specialist function. |

## Next Experiment

Before using a Token-saving metric externally:

1. Expand to at least 20-30 tasks across 3-5 real repositories, with repository and commit fixed per task.
2. Keep each task behavior-oriented and require multiple locations, but remove ambiguous gold labels such as `mcp-search`.
3. Run each cohort multiple times or use a fixed deterministic client/model setting, then report pass rate and cost only on common-success runs.
4. Record both total model input tokens and source/context volume. Report failures and confidence intervals rather than only the best average.
5. Add a targeted regression for wrapper-to-implementation navigation before claiming that RepoMind consistently improves cross-file navigation.

## Reproduction

```powershell
& .\scripts\run_codex_location_ab.ps1 `
  -RepoId 'repo_19d561514a8142ac8b8b665f71c01d8a' `
  -SnapshotId 'snap_370f33b4516b1aedc7cee92717a4795fc21968a3bf65a2e8268cd1e0b398b36d' `
  -McpName 'repomind-location' `
  -TimeoutSeconds 180 `
  -Force
```

Raw Codex traces and the machine-readable result table are written to `e2e-artifacts/codex-location-ab-v2/`.
