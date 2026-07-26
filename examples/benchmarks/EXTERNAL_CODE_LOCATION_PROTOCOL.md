# External Code-Location Evaluation Protocol

This protocol evaluates one narrow product claim: whether a Coding Agent can locate
manually annotated source evidence in an unfamiliar repository with less broad source
reading after it uses RepoMind MCP. It does not measure full feature-development
quality, and it must not be used to claim universal Token savings.

## Prepare a clean evaluation

1. Create a separate checkout for each external public repository and pin it to one
   40-character Git commit. Do not store task JSON, reports, or raw traces inside the
   checkout.
2. Register and ingest that checkout using a new RepoMind data directory. Do not reuse
   a daily-use database or an index built for a different local checkout.
3. Write 5-10 two-location tasks per repository. Each task needs a natural-language
   question, two or more manually verified `path`/`line_start` locations, and the same
   pinned commit. Include both successful and failed runs in the report.
4. Fill a manifest from
   `external-location-benchmark.manifest.example.json`. The manifest points to the
   checkout, its isolated database/data directory, `repo_id`, `snapshot_id`, and a task
   file outside the target checkout.

The first recommended batch is 3-5 repositories and 20-30 total tasks. Keep language,
repository size, client version, model configuration, and task categories in the final
report.

## Run

Run the preflight first:

```powershell
python .\scripts\validate_location_benchmark.py --manifest C:\benchmarks\target.manifest.json
```

It checks the checkout HEAD, task commit, Git paths, index database/data-directory
isolation, repo/snapshot ownership, succeeded status, and snapshot commit. It also
rejects task files placed inside the repository under test. The preflight only reads Git
metadata and SQLite metadata; it does not execute target code, install dependencies, or
change the checkout.

Then run both cohorts:

```powershell
& .\scripts\run_codex_location_ab.ps1 `
  -Manifest C:\benchmarks\target.manifest.json `
  -McpBackendPath .\backend `
  -OutputDir e2e-artifacts\external-location-example `
  -Model gpt-5.6-terra `
  -ReasoningEffort low `
  -Mode all
```

The runner writes `results.json` plus `run-metadata.json`. To aggregate completed
runs from several repositories, create a batch file from
`external-location-batch.example.json` and run:

```powershell
python .\scripts\report_external_location_batch.py `
  --batch C:\benchmarks\external-location-batch.json `
  --output C:\benchmarks\external-location-summary.json
```

The aggregator rejects runs with different Codex versions, models, reasoning effort,
or sandbox mode. It reports task pass rates across all tasks, but calculates Token and
source-text deltas only on tasks passed by both cohorts.

The baseline may use repository search/read commands. The treatment may use only the
temporary, manifest-bound RepoMind MCP profile. Both use one ephemeral Codex session per
task. The runner never invokes target-repository commands beyond `git` metadata reads.

## Report honestly

- A task passes only when the final answer reports every gold path and a line range that
  covers every annotated gold start line.
- Report pass rate over all tasks for each cohort.
- Compare input Token counts and `source_characters_received` only on tasks that both
  cohorts pass. The latter is a tool-output context-volume proxy, not billed Tokens.
- Preserve the manifest, task annotation, raw JSONL traces, client/model version, and
  runner options next to the generated result table. Do not commit private checkouts,
  databases, API keys, or raw repository source.
- On Windows, the current CLI experiment uses the same unrestricted process mode because
  read-only sandboxing terminates local stdio MCP children. Cohort restrictions are
  prompt-enforced; state this limitation in every report.

Only after this protocol has been completed across multiple external repositories may
the results be summarized as a scoped evaluation. Keep the sample size and conditions in
the same sentence as any metric.
