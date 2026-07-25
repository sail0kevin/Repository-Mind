# Codex Token A/B: small controlled baseline

This experiment asks whether RepoMind currently reduces Codex input Tokens during small repository-understanding tasks. The result is deliberately published even though it is negative overall.

## Setup

- Three read-only tasks: implementation explanation, Agent flow, and cross-file impact.
- Fixed repository commit: `32fd00f0c2b212e04de890d928722717766cd670`.
- Codex CLI `0.145.0`, model `gpt-5.6-terra`, reasoning effort `low`.
- A fresh ephemeral session and the same answer-length constraint for every run.
- Baseline used Shell search/file reads with RepoMind disabled.
- Treatment used only RepoMind's six read-only MCP tools. Shell and local file reads were forbidden.
- Both paths were scored against the required files and answer points in `codex-token-ab-tasks.json`.

## Results

| Task | Baseline input | MCP input | Change | Baseline actions | MCP calls | Quality |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Evidence Budget | 27,742 | 44,117 | +59.0% | 4 | 3 | both passed |
| Main Agent flow | 51,842 | 56,487 | +9.0% | 6 | 5 | both passed |
| `route_question` impact | 51,352 | 47,589 | -7.3% | 9 | 3 | both passed |
| **Total** | **130,936** | **148,193** | **+13.2%** | **19** | **11** | **3/3 both** |

RepoMind removed all 19 blind Shell/file-read actions in the treatment runs and preserved the required answer points, but it did **not** reduce aggregate input Tokens in this small benchmark. MCP tool definitions, repeated tool calls, and returned Evidence are themselves part of the model context.

A diagnostic RRF lookup used 72,431 baseline input Tokens and 51,270 with MCP (-29.2%), but its prompt was less strictly controlled, so it is excluded from the aggregate. It is retained as a warning that results vary substantially by task.

## Interpretation

The current evidence supports a narrow claim: RepoMind makes repository evidence acquisition more bounded and traceable, and can reduce broad manual exploration. It does not yet support a general Token-saving claim. Simple lookups can cost more than direct search, while broader tasks may benefit.

The next optimization target is the MCP surface itself: smaller tool descriptions, fewer discovery calls, more compact evidence payloads, and query-aware tool selection. A larger benchmark should include repeated runs, cold and warm sessions, multiple repositories, and pricing-normalized cost in addition to Token counts.

## Reproduction

See `scripts/run_codex_token_ab.ps1`. The script expects an already indexed fixed Snapshot, a configured RepoMind MCP server, and `-RepositoryPath` pointing to a clean clone at the measured commit. It runs Codex with a read-only sandbox and writes raw JSONL outside tracked benchmark files; review the raw output before regenerating this report.
