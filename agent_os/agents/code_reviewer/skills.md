# Code Reviewer — Skills

## Core Capabilities

1. **Structured Code Review** — Produces a fully machine-parseable JSON review covering every file written by the Code Generator, with per-file verdicts (`accept`, `patch`, `regenerate`), issue lists, and overall status.

2. **Acceptance Criteria Verification** — Checks every acceptance criterion from the original requirements against the generated code, producing a `passed/failed` verdict with evidence for each AC.

3. **Multi-Dimensional Scoring** — Scores code quality across four dimensions: Design (architecture, patterns, coupling), Security (OWASP Top 10, input validation, secrets), Testing (coverage, meaningful assertions, edge cases), and Performance (N+1 queries, unnecessary computation, blocking I/O).

4. **Validation Result Interpretation** — Reads lint, type-check, test, and security scan outputs from the Validation step and incorporates them into the review, preventing the same issues from being independently re-identified.

5. **Convergence Score Assessment** — Produces a `convergence_score` (0–100) representing how close the code is to being production-ready, guiding the Decision Engine on whether to accept or iterate.

6. **Issue Severity Classification** — Classifies every identified issue by severity (critical, high, medium, low, info) and category (bug, security, performance, design, style, testing, documentation, other), enabling the convergence rule to make a data-driven accept/iterate decision.

7. **Targeted Fix Guidance** — For every issue, provides a `suggested_fix` that is specific enough for the Prompt Generator to incorporate directly into the next iteration's prompt.
