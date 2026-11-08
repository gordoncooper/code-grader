<!-- Part of the Code Grading Suite v4.2.2. Read together with prompts/grader.md, which holds the scoring rules, anti-gaming rules and output format. -->

# Pillar A rubric: Correctness & Trust

*Does it work, is it safe, and can you rely on it under real conditions?*

## A1. Correctness & Functional Behavior
- **Measures:** The code does what it's meant to, including edge cases, boundary values, invalid input, empty or null states and failure paths.
- **Not this:** Whether the right features exist at all (D1, D2). Behavior under hostile or degraded conditions (A3).
- **Assess:** Run the tests. Trace core flows by hand. Probe off-by-one errors, empty collections, Unicode, time zones and DST, numeric overflow and precision, money rounding, and ordering assumptions.
- **Anchors:**
  - **1–3:** Core features broken or crash on ordinary input; tests fail.
  - **4–6:** Happy paths work; edge cases often mishandled.
  - **7–8:** Edge cases mostly handled; a few latent bugs found on careful reading.
  - **9–10:** No defects found on careful review; edge cases handled deliberately and covered by tests.
- **Caps:** Failing build or tests → max 4. A bug that corrupts or loses data → max 3.

## A2. Security & Privacy
- **Measures:** Resistance to misuse and attack, and responsible handling of personal data. Covers input validation; injection (SQL, shell, path, template); authentication and authorization; secrets handling; cryptography; deserialization; SSRF; XSS/CSRF; secure defaults; least privilege; collecting only the personal data needed; retention; no sensitive data in logs or errors.
- **Not this:** Vulnerable dependencies are scored here only when they're reachable; general dependency health is F6.
- **Assess:** Trace every trust boundary. Search for hard-coded secrets, string-built queries or commands, disabled TLS verification, homemade crypto, endpoints missing authorization checks, overly broad IAM or permissions, and PII in logs. Run vulnerability scans.
- **Anchors:**
  - **1–3:** Exploitable vulnerabilities, or committed secrets.
  - **4–6:** No obvious exploit, but validation is inconsistent and defaults are unsafe.
  - **7–8:** Trust boundaries validated, queries parameterized, secrets externalized; minor hardening gaps.
  - **9–10:** Defense in depth, centralized authorization, privacy by design, security scanning gated in CI.
- **Caps:** Exploitable vulnerability or committed live secret → max 2. Reachable high or critical CVE → max 4.

## A3. Robustness & Error Handling
- **Measures:** Behavior when things go wrong: malformed input, dependency outages, slow networks, resource exhaustion, partial failures. Explicit error handling, useful error context, timeouts, retries with backoff and jitter, circuit breakers where warranted, resource cleanup, graceful degradation, bounded queues and buffers.
- **Not this:** Whether retries are *safe* to repeat (A4). Whether data survives a crash (A5).
- **Assess:** Review every catch, except, rescue and error return. Look for swallowed errors, overly broad catches, I/O with no timeout, leaked handles, unchecked return values, unbounded growth, and crashes on expected failures. Use fuzz or property tests if available.
- **Anchors:**
  - **1–3:** Errors ignored; crashes on routine failures.
  - **4–6:** Handling is inconsistent; vague messages; missing timeouts.
  - **7–8:** Consistent strategy; errors carry context; external calls bounded; cleanup reliable.
  - **9–10:** A uniform error model; failures are contained, observable and recoverable; failure paths are tested, including injected faults.
- **Caps:** Catch-all blocks that swallow errors in core paths → max 4.

## A4. Idempotence & Determinism
- **Measures:**
  - **Idempotence:** operations that may be retried or repeated have the same effect as running once. This covers API mutations (idempotency keys or natural keys), message and queue consumers under redelivery, webhooks, setup, provisioning and seed scripts, migrations, infrastructure-as-code (repeated applies converge to the same state), deploys, and cron jobs.
  - **Determinism:** the same inputs give the same outputs. Builds are reproducible, tests are deterministic, and time, randomness, ordering and environment are injected or controlled rather than hidden.
- **Not this:** General retry and timeout policy (A3).
- **Assess:** Run setup, seed and migration scripts twice. Look for blind INSERTs, "create" with no existence check, increments or charges on retry, non-atomic check-then-act, unordered map iteration that affects output, unseeded randomness, and `now()` called deep inside logic. Rebuild and compare artifacts or hashes where practical.
- **Anchors:**
  - **1–3:** Repeating an operation duplicates side effects; scripts break on the second run.
  - **4–6:** Some operations safe to repeat; others not; tests occasionally nondeterministic.
  - **7–8:** All externally triggered mutations and scripts are safe to re-run; time and randomness are injectable.
  - **9–10:** Idempotence is designed in and tested (replay or redelivery tests); builds are reproducible; zero flaky tests.
- **Caps:** Retry or redelivery can double-charge, double-send or duplicate records with real-world consequences → max 3. Setup or migration fails or corrupts on a second run → max 5.

## A5. Durability & Recoverability
- **Measures:** Data and state survive crashes, restarts, deploys and power loss, and the system can recover. Covers atomic writes (write to a temp file then rename; fsync where it matters), transactions around multi-step writes, no important state held only in memory, crash-consistent file formats, versioned and reversible migrations, backups with a *tested* restore, defined RPO and RTO for production data, and clean resume after a restart (checkpointing for long jobs).
- **Not this:** Schema design quality (B4). Concurrency races (X3).
- **Assess:** Find every write path and every place state lives. Ask what happens if the process is killed between any two lines. Check for a backup and restore procedure and evidence it has been tested.
- **Anchors:**
  - **1–3:** A crash can lose or corrupt important data.
  - **4–6:** Mostly safe; some non-atomic writes or in-memory-only state; backups untested.
  - **7–8:** Atomic, transactional writes; reliable resume; backups exist.
  - **9–10:** Crash-consistency is designed in and tested (kill tests, chaos tests); restore drills are documented and automated.
- **Caps:** Important state written non-atomically or held only in memory → max 4. Persistent production data with no backup → max 5.
