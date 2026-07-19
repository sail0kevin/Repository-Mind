# Retrieval benchmark: RepoMind bundled Demo

- Snapshot: `8c5ac33542fbed5e117bfee19af1457e60bd166c`
- Mode: `lexical-only/no-key-fallback`
- Queries: **3**
- Recall@5: **0.667**
- Recall@10: **0.667**
- MRR: **0.833**
- Citation hit rate: **1.000**
- Citation precision: **0.750**

## Per-query actual cited files

### `navigation-build-message`

- Question: `GreetingService.build_message 方法是做什么的？`
- Route tools: `[]`
- Actual cited files: `repomind_demo/service.py`, `README.md`, `tests/test_greeting.py`
- Relevant cited files: `repomind_demo/service.py`, `README.md`, `tests/test_greeting.py`
- Result: **passed**

### `security-review`

- Question: `security token 安全风险`
- Route tools: `['security_review']`
- Actual cited files: `README.md`, `config.json`, `expected/showcase.json`, `repomind_demo/security_examples.py`
- Relevant cited files: `README.md`, `repomind_demo/security_examples.py`
- Result: **passed**

### `impact-build-message`

- Question: `Changing GreetingService.build_message impact call chain and tests`
- Route tools: `['dependency_impact']`
- Actual cited files: `repomind_demo/service.py`, `repomind_demo/app/main.py`, `tests/test_greeting.py`, `expected/showcase.json`
- Relevant cited files: `repomind_demo/service.py`, `repomind_demo/app/main.py`, `tests/test_greeting.py`
- Result: **passed**

## Pre-fix versus post-fix

- Recall@5: **0.556 → 0.667**
- Recall@10: **0.556 → 0.667**
- MRR: **0.667 → 0.833**
- Citation hit rate: **0.667 → 1.000**
- Citation precision: **0.667 → 0.750**

## Limitations

- This capture evaluates cited evidence paths only; it does not judge answer semantics.
- The bundled Demo contains three questions and is not a large-repository benchmark.
- Latency is omitted because this script does not establish a controlled timing protocol.
- This is a post-fix capture generated after Specialist Tool evidence was merged into synthesis.
- No target-repository code was executed and no Chat or Embedding key was configured.
