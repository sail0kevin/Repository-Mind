# RepoMind Security Boundary

This document describes the security posture of the public `0.1.x` development
line. It is a product boundary, not a security certification.

RepoMind is a local, single-user repository knowledge assistant. It reads a Git
repository and builds immutable commit-level Snapshots, structured Evidence,
Catalog data, and optional local indexes. It does not execute code from the
target repository.

## Read-only product boundary

- RepoMind does not modify the target repository, create commits, push branches,
  open pull requests, or publish releases.
- Repository files are scanned and parsed as data. Repository dependencies and
  scripts are not installed or executed by the indexing workflow.
- Main Agent tools are bounded, read-only analyses. Security Review reports
  static rule-based signals; it is not a complete security audit.
- Code Graph relations describe observed static relationships. They are not a
  claim about every runtime call path.

## Local data and credentials

- Use a temporary `REPOMIND_USER_DATA_PATH` and temporary database for demos,
  tests, screenshots, and smoke checks.
- Never commit SQLite databases, logs, build output, API keys, tokens, private
  source code, or real user data.
- Chat and Embedding credentials are independent settings. Empty keys must
  degrade to lexical retrieval and deterministic rule answers; the UI and trace
  must not disclose credential values.
- On Windows, saved credentials are kept through the local SecretStore/DPAPI
  path. The settings API exposes configuration and masked hints, not full key
  material. A user who can read the Windows user profile can still access that
  user's secrets; use a separate Windows account for sensitive work.
- Custom provider URLs are user-controlled configuration. When Chat or Embedding
  is enabled, RepoMind sends the repository Evidence retrieved for that request
  to the configured endpoint. That payload can include source code, file paths,
  configuration excerpts, symbols, and the user's question. The corresponding
  API key is also sent as required by the provider API.
- An arbitrary custom endpoint is therefore a local-user trust boundary, not a
  sandboxed or project-endorsed service. Do not put secrets in URLs, query
  strings, repository files, screenshots, or public traces. Only use HTTPS
  endpoints whose operator, data retention, logging, and access policies you
  trust. Do not analyze a private repository with an untrusted endpoint.
- RepoMind does not claim to provide a network sandbox, destination allowlist,
  data-loss-prevention layer, or SSRF boundary for arbitrary provider URLs.
- Public examples and screenshots must remove personal paths, temporary
  directories, user database locations, and secrets.

## Safe operating procedure

1. Set a temporary `REPOMIND_USER_DATA_PATH` before demos or tests.
2. Do not execute target-repository scripts, install its dependencies, or point
   RepoMind at a private repository when capturing public evidence.
3. If a credential may have appeared in a log or screenshot, revoke/rotate it
   before investigating further.
4. Before publishing a build, inspect the archive and publish a SHA-256 digest;
   do not treat an unsigned binary as an authenticated release.

## Reporting a concern

Please use a private GitHub security report if one is enabled for the
repository. Otherwise contact the repository owner through the address listed
on the owner's GitHub profile before opening a public issue. Do not include
secrets or private repository contents. Describe the affected component,
reproducible steps using a temporary repository, expected behavior, and
observed behavior. For a suspected credential exposure, revoke the credential
first and report only a redacted description. There is currently no promise of
a dedicated SLA or bug-bounty program.

## Known limitations

Static Security Review is a bounded signal detector, not a full SAST, dependency
audit, runtime sandbox, or penetration test. Findings require human review and
should not be presented as proof that a repository is secure.
