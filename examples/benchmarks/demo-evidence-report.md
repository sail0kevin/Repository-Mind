# RepoMind bundled Demo evidence report

- Snapshot: `8c5ac33542fbed5e117bfee19af1457e60bd166c`
- Mode: `lexical-only/no-key-fallback`
- Queries: **3**
- Recall@5: **0.667**
- Recall@10: **0.667**
- MRR: **0.667**
- Citation hit rate: **0.667**
- Citation precision: **0.667**

## Interpretation

This report is computed from the committed `examples/outputs/repomind-demo-trace.json`,
not from a new model run. Two of the three captured questions cited at least one
relevant path; the dependency-impact capture cited `expected/showcase.json` instead
of the expected service, entrypoint, and test files. That miss is intentionally kept
visible as a follow-up engineering item rather than hidden by averaging.

The capture predates the fix that now merges Specialist Tool evidence into the final
synthesis context. It is therefore a **pre-fix baseline**; a post-fix Demo run must be
captured before claiming an improvement.

The result evaluates evidence-path overlap only. It does not claim that the natural
language answer is correct, does not measure latency, and is not representative of
large repositories.
