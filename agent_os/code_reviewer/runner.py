"""Code Reviewer runner — Phase 3.3.

Reviews a GitHub PR diff using OpenAI streaming API and produces a structured
``ReviewJSON`` output that is then fed back to the Prompt Generator for the next
iteration.

Input:
  - ``pr_number``     : GitHub pull request number
  - ``iteration``     : current pipeline iteration (1-based)
  - ``feature_branch``: name of the feature branch (used for final merge + delete)

Operations (executed in order):
  1. Fetch PR diff + files via GitHubClient
  2. Run the 15-point checklist review via OpenAI streaming
     + 3 additional checks: file size, clean architecture, folder structure
  3. Parse the structured ReviewJSON from the LLM output
  4. Post inline PR comments for line-level findings
  5. Post global PR comments for structural / architecture findings
  6. Write ReviewJSON to the configured local file path
  7. If ``overall_status == "accepted"``: merge PR → delete feature branch

The reviewer has NO local codebase access — all code is read from VCS.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

from ..config.schema import AgentOSConfig
from ..constants import (
    DIFF_CHAR_LIMIT,
)
from ..vcs.base import VCSClient
from .schema import (
    ArchitectureIssue,
    FileSizeViolation,
    FolderStructureIssue,
    GlobalComment,
    IssueSeverity,
    LineComment,
    ReviewJSON,
    ReviewRunResult,
)

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a senior software engineer and code reviewer performing a strict quality \
review of a pull request diff.

You have NO access to the local filesystem — all code to review is provided to you \
as a PR diff below.  Do NOT ask for files or assume you can read from disk.

════════════════════════════════════════════════════════════════════════
MANDATORY 15-POINT CHECKLIST (assess and score every item 0–100):
════════════════════════════════════════════════════════════════════════

 1. code_correctness   — Logic errors, bugs, edge cases, unexpected behaviour
 2. readability        — Naming conventions, formatting, clarity at a glance
 3. structure_design   — Modularity, SOLID principles, separation of concerns
 4. performance        — Algorithmic complexity, unnecessary loops, memory usage
 5. security           — Injection vulns, auth weaknesses, data exposure, OWASP Top 10
 6. error_handling     — Exception coverage, fallback logic, graceful degradation
 7. code_standards     — Style-guide conformance, linting, formatting consistency
 8. testing            — Unit/integration test presence, quality, coverage
 9. documentation      — Docstrings, README accuracy, inline comments
10. maintainability    — Tech debt, duplication, excessive coupling, fragility
11. dependencies       — Unused imports, outdated deps, version pinning
12. logging            — Structured logging, error tracing, observability
13. version_control    — Commit quality, branch hygiene, merge readiness
14. ui_ux              — Usability, accessibility, responsive design (frontend only—
                         score 100 if no frontend files changed)
15. overall_impact     — Risk assessment, regression potential, release readiness

════════════════════════════════════════════════════════════════════════
ADDITIONAL MANDATORY CHECKS:
════════════════════════════════════════════════════════════════════════

File size rule:
  - Count lines added (lines beginning with '+' in the diff, excluding the '+++' header).
  - Flag EVERY file with more than 200 added lines in ``file_size_violations``.

Clean architecture compliance:
  - No business logic inside route/controller handlers.
  - No direct database calls from the UI layer or route handlers.
  - No cross-layer dependency bypasses (e.g. a UI component importing a DB model directly).
  - Report each violation in ``architecture_issues``.

Folder structure review:
  - Verify every new/modified file is in the correct directory for the project.
  - Flag misplaced files in ``folder_structure_issues`` with the path, issue, and expected location.

════════════════════════════════════════════════════════════════════════
STRICT REJECTION RULES (non-negotiable):
════════════════════════════════════════════════════════════════════════

  - ANY syntax error detected → overall_status = "rejected" immediately.
  - ANY critical security vulnerability → overall_status = "rejected" immediately.
  - Tests failing or missing for new functionality → overall_score ≤ 40.
  - overall_score ≥ 80 requires items 1–7 all scoring ≥ 70 with zero critical/high issues.

════════════════════════════════════════════════════════════════════════
CONVERGENCE RULE:
════════════════════════════════════════════════════════════════════════

  Set overall_status = "accepted" ONLY when ALL of the following hold:
  - overall_score ≥ 80
  - No critical or high severity issues in line_comments or global_comments
  - No architecture_issues with severity "critical" or "high"
  - No file_size_violations
  - No syntax errors

════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT:
════════════════════════════════════════════════════════════════════════

First, reason through each checklist item and finding in plain text.
Then, end your response with a single JSON object (no markdown fences) with:

CRITICAL RULES FOR line_comments:
- You MUST generate line_comments for EVERY specific code issue you find.
  Do NOT put line-specific issues only in global_comments.
- Every line_comment MUST have a non-empty "suggested_fix" field showing
  the corrected code or the exact change needed. "See above" is NOT acceptable.
- Use the exact file path from the diff (e.g. "app.py", "register.py").
- Use the line number of the added line (lines starting with '+' in the diff).
- Aim for at least one line_comment per file that has issues.

{
  "overall_status"          : "needs_work" | "accepted" | "rejected",
  "overall_score"           : <integer 0-100>,
  "checklist_scores"        : {
      "code_correctness": <0-100>, "readability": <0-100>,
      "structure_design": <0-100>, "performance": <0-100>,
      "security": <0-100>, "error_handling": <0-100>,
      "code_standards": <0-100>, "testing": <0-100>,
      "documentation": <0-100>, "maintainability": <0-100>,
      "dependencies": <0-100>, "logging": <0-100>,
      "version_control": <0-100>, "ui_ux": <0-100>,
      "overall_impact": <0-100>
  },
  "line_comments"           : [
      { "file": "<exact path from diff>", "line": <int>,
        "comment": "<specific issue description>",
        "severity": "critical"|"high"|"medium"|"low"|"info",
        "checklist_item": "<name>",
        "suggested_fix": "<exact corrected code or precise fix instruction>" }
  ],
  "global_comments"         : [
      { "comment": "<text>",
        "category": "architecture"|"folder_structure"|"security"|"general",
        "severity": "critical"|"high"|"medium"|"low"|"info" }
  ],
  "folder_structure_issues" : [
      { "path": "<path>", "issue": "<desc>", "expected_location": "<path>" }
  ],
  "architecture_issues"     : [
      { "description": "<desc>", "layer": "<layer>",
        "severity": "critical"|"high"|"medium"|"low"|"info" }
  ],
  "file_size_violations"    : [
      { "file": "<path>", "line_count": <int> }
  ],
  "summary"                 : "<overall verdict and recommended next steps>"
}

Do NOT wrap the JSON in markdown fences.
"""

# ── Checklist keys (used for validation / display) ────────────────────────────

CHECKLIST_KEYS = [
    "code_correctness", "readability", "structure_design", "performance",
    "security", "error_handling", "code_standards", "testing",
    "documentation", "maintainability", "dependencies", "logging",
    "version_control", "ui_ux", "overall_impact",
]


class CodeReviewerRunner:
    """Review a GitHub PR diff via OpenAI API and post findings back to GitHub."""

    def __init__(
        self,
        config: AgentOSConfig,
        identity_ctx=None,
        vcs_client: VCSClient | None = None,
        llm_client: Any | None = None,
    ) -> None:
        self._config = config
        self._identity_ctx = identity_ctx
        self._vcs_client = vcs_client
        self._llm_client = llm_client  # Optional injected LLM client for testing

    # ── Public API ─────────────────────────────────────────────────────────

    def run(
        self,
        pr_number: int,
        iteration: int,
        feature_branch: str | None = None,
        on_stdout: Callable[[str], None] | None = None,
        story_context: dict | None = None,
    ) -> ReviewRunResult:
        """Run a full PR review.

        Args:
            pr_number:      GitHub PR number to review.
            iteration:      Current pipeline iteration (1-based).
            feature_branch: Feature branch name — needed only for the final
                            "accepted" merge + delete step.
            on_stdout:      Callback for real-time streaming lines (Terminal Hub).

        Returns:
            ReviewRunResult with the parsed ReviewJSON and metadata.
        """
        def _emit(line: str) -> None:
            if on_stdout:
                with contextlib.suppress(Exception):
                    on_stdout(line)

        _emit(f"[code-reviewer] Starting review of PR #{pr_number} (iteration {iteration})")

        gh = self._make_vcs_client()
        if gh is None:
            _emit("[code-reviewer] VCS credentials not configured — aborting review")
            return ReviewRunResult(
                ReviewJSON(overall_status="needs_work", summary="VCS credentials not configured"),
            )

        # 1. Fetch PR context
        diff_text, head_sha, pr_info = self._fetch_pr_context(gh, pr_number, _emit)

        # 2. Stream review via OpenAI (pass story ACs when in GitHub Review mode)
        raw_text = self._stream_review(diff_text, pr_info, iteration, _emit,
                                       story_context=story_context)
        if not raw_text:
            return ReviewRunResult(
                ReviewJSON(overall_status="needs_work", summary="LLM returned empty response"),
            )

        # 3. Parse JSON
        review = self._parse_review_json(raw_text, _emit)

        # Populate GitHub Review mode fields on the ReviewJSON
        review.pr_number = pr_number
        review.pr_url = (pr_info.get("html_url") or "") if pr_info else ""
        if story_context:
            review.story_id = story_context.get("story_id", "")

        # 4. Post inline PR comments
        comments_posted = self._post_inline_comments(gh, pr_number, head_sha, review, _emit)

        # 5. Post global PR comments
        comments_posted += self._post_global_comments(gh, pr_number, review, _emit)

        # 6. Write review JSON to disk
        review_json_path = self._write_review_json(review, iteration)
        _emit(f"[code-reviewer] Review JSON written to {review_json_path}")

        pr_merged = False
        branch_deleted = False

        # 7. If accepted — merge PR and delete feature branch
        if review.overall_status == "accepted":
            _emit("[code-reviewer] Review accepted — merging PR and deleting feature branch")
            feature_branch = feature_branch or self._config.project.feature_branch or "dev"
            pr_merged, branch_deleted = self._finalize_pr(gh, pr_number, feature_branch, _emit)

        _emit(
            f"[code-reviewer] Done — status={review.overall_status} "
            f"score={review.overall_score} comments={comments_posted}"
        )

        return ReviewRunResult(
            review=review,
            raw_text=raw_text,
            review_json_path=str(review_json_path),
            comments_posted=comments_posted,
            pr_merged=pr_merged,
            branch_deleted=branch_deleted,
        )

    # ── Private helpers ────────────────────────────────────────────────────

    def _make_vcs_client(self) -> VCSClient | None:
        """Return the injected VCSClient, or build one from config via the factory."""
        if self._vcs_client is not None:
            return self._vcs_client
        from ..vcs.factory import make_vcs_client
        client = make_vcs_client(self._config)
        if client is None:
            logger.warning("VCS credentials incomplete — code review will be skipped")
        return client

    def _fetch_pr_context(
        self,
        gh: VCSClient,
        pr_number: int,
        emit: Callable[[str], None],
    ) -> tuple[str, str, dict]:
        """Fetch diff text, head SHA and basic PR metadata."""
        from .diff_fetcher import fetch_pr_context
        return fetch_pr_context(gh, pr_number, emit)

    def _stream_review(
        self,
        diff_text: str,
        pr_info: dict,
        iteration: int,
        emit: Callable[[str], None],
        story_context: dict | None = None,
    ) -> str:
        """Stream LLM review of the diff; return the full raw text.

        Delegates provider resolution and streaming to llm_client module.
        """
        from .llm_client import resolve_provider_config, stream_review

        code_reviewer_config = getattr(self._config, "code_reviewer", None)
        provider, base_url, api_key, model = resolve_provider_config(
            self._config, code_reviewer_config, emit,
        )
        if not api_key:
            return ""

        emit(f"[code-reviewer] Streaming review via {provider}/{model} …")

        pr_title = pr_info.get("title", "")
        pr_url = pr_info.get("html_url", "")
        project_name = self._config.project.name or "the project"
        language = self._config.project.language or "python"

        preamble = (
            self._identity_ctx.build_preamble() if self._identity_ctx else ""
        )
        system_prompt = (
            (preamble + "\n\n" + _SYSTEM_PROMPT).strip() if preamble else _SYSTEM_PROMPT
        )

        # In GitHub Review mode, append the story's acceptance criteria
        if story_context:
            ac_list: list[str] = story_context.get("acceptance_criteria", []) or []
            story_id = story_context.get("story_id", "")
            story_title = story_context.get("title", "")
            if ac_list:
                ac_section = "\n".join(f"  - {ac}" for ac in ac_list)
                story_label = f"Story {story_id}: {story_title}" if story_id else "this story"
                system_prompt += (
                    f"\n\n════════════════════════════════════════════════════════════════════════\n"
                    f"STORY ACCEPTANCE CRITERIA (MANDATORY — validate against these):\n"
                    f"════════════════════════════════════════════════════════════════════════\n"
                    f"The implementation must satisfy ALL acceptance criteria for {story_label}:\n\n"
                    f"{ac_section}\n\n"
                    f"Add a global_comment for each AC that is NOT fully satisfied, with "
                    f'category=\'general\' and severity=\'high\'. '
                    f"If all ACs are satisfied, note this in the summary."
                )

        # Cap diff
        _MAX_DIFF = DIFF_CHAR_LIMIT
        if len(diff_text) > _MAX_DIFF:
            diff_text = diff_text[:_MAX_DIFF] + "\n\n... [diff truncated — review as many files as possible]"

        user_message = (
            f"Review the following pull request for **{project_name}** "
            f"(language: {language}, iteration {iteration}).\n\n"
            f"PR: {pr_title or pr_url}\n\n"
            "---\n"
            f"{diff_text}\n"
            "---\n\n"
            "Reason through each checklist item and finding, then emit the JSON object."
        )

        try:
            return stream_review(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                system_prompt=system_prompt,
                user_message=user_message,
                emit=emit,
            )
        except Exception as exc:
            emit(f"[code-reviewer] LLM streaming failed: {exc}")
            logger.warning("Code review LLM failed (iter %d): %s", iteration, exc)
            raise

    def _parse_review_json(
        self,
        raw_text: str,
        emit: Callable[[str], None],
    ) -> ReviewJSON:
        """Extract and parse the JSON object from the LLM output."""
        json_str = _extract_json(raw_text)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            emit("[code-reviewer] Could not parse review JSON — returning default")
            return ReviewJSON(
                overall_status="needs_work",
                summary="Review parse error: no valid JSON in LLM output",
            )

        try:
            review = ReviewJSON.model_validate(data)
        except Exception as exc:
            emit(f"[code-reviewer] Schema validation failed ({exc}) — attempting lenient parse")
            review = _lenient_parse(data)

        review.compute_overall_score()
        return review

    def _post_inline_comments(
        self,
        gh: VCSClient,
        pr_number: int,
        head_sha: str,
        review: ReviewJSON,
        emit: Callable[[str], None],
    ) -> int:
        """Post line-level review comments to the PR. Returns number of comments posted."""
        from .commenter import post_inline_comments
        return post_inline_comments(gh, pr_number, head_sha, review, emit)

    def _post_global_comments(
        self,
        gh: VCSClient,
        pr_number: int,
        review: ReviewJSON,
        emit: Callable[[str], None],
    ) -> int:
        """Post global (non-inline) PR comments for structural findings."""
        from .commenter import post_global_comments
        return post_global_comments(gh, pr_number, review, emit)

    def _write_review_json(self, review: ReviewJSON, iteration: int) -> Path:
        """Serialise and write the review JSON to the configured output path."""
        review_path = getattr(self._config.project, "review_json_path", "") or ""
        if review_path:
            out_path = Path(review_path)
        else:
            out_path = (
                Path(self._config.storage.db_path).parent
                / "reviews"
                / f"iteration-{iteration}.json"
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(review.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Review JSON written to %s (%d chars)", out_path, out_path.stat().st_size)
        return out_path

    def _finalize_pr(
        self,
        gh: VCSClient,
        pr_number: int,
        feature_branch: str,
        emit: Callable[[str], None],
    ) -> tuple[bool, bool]:
        """Merge the PR and delete the feature branch. Returns (merged, branch_deleted)."""
        from .commenter import finalize_pr
        return finalize_pr(gh, pr_number, feature_branch, emit)


# ── JSON extraction ────────────────────────────────────────────────────────────

def _extract_json(raw: str) -> str:
    """Extract the first top-level JSON object from text that may include reasoning."""
    # Fenced code blocks
    fenced = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', raw)
    if fenced:
        return fenced.group(1).strip()

    # Walk from the first '{' to the balanced '}'
    start = raw.find("{")
    if start < 0:
        return raw

    depth = 0
    in_str = False
    escape_next = False
    for i, ch in enumerate(raw[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_str:
            escape_next = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start: i + 1]

    return raw[start:]


# ── Lenient parser ─────────────────────────────────────────────────────────────

def _lenient_parse(data: dict) -> ReviewJSON:
    """Best-effort coercion of a loosely-shaped dict into ReviewJSON."""

    def _sev(raw: str) -> IssueSeverity:
        try:
            return IssueSeverity(raw.lower())
        except (ValueError, AttributeError):
            return IssueSeverity.MEDIUM

    line_comments = []
    for item in (data.get("line_comments") or []):
        if not isinstance(item, dict):
            continue
        line_comments.append(LineComment(
            file=str(item.get("file", "")),
            line=int(item.get("line", 0)),
            comment=str(item.get("comment", "")),
            severity=_sev(str(item.get("severity", "medium"))),
            checklist_item=str(item.get("checklist_item", "")),
            suggested_fix=str(item.get("suggested_fix", "")),
        ))

    global_comments = []
    for item in (data.get("global_comments") or []):
        if not isinstance(item, dict):
            continue
        global_comments.append(GlobalComment(
            comment=str(item.get("comment", "")),
            category=str(item.get("category", "general")),
            severity=_sev(str(item.get("severity", "medium"))),
        ))

    folder_issues = []
    for item in (data.get("folder_structure_issues") or []):
        if not isinstance(item, dict):
            continue
        folder_issues.append(FolderStructureIssue(
            path=str(item.get("path", "")),
            issue=str(item.get("issue", "")),
            expected_location=str(item.get("expected_location", "")),
        ))

    arch_issues = []
    for item in (data.get("architecture_issues") or []):
        if not isinstance(item, dict):
            continue
        arch_issues.append(ArchitectureIssue(
            description=str(item.get("description", "")),
            layer=str(item.get("layer", "")),
            severity=_sev(str(item.get("severity", "high"))),
        ))

    size_violations = []
    for item in (data.get("file_size_violations") or []):
        if not isinstance(item, dict):
            continue
        size_violations.append(FileSizeViolation(
            file=str(item.get("file", "")),
            line_count=int(item.get("line_count", 0)),
        ))

    review = ReviewJSON(
        overall_status=str(data.get("overall_status", "needs_work")),
        overall_score=int(data.get("overall_score", 0)),
        checklist_scores={
            str(k): int(v)
            for k, v in (data.get("checklist_scores") or {}).items()
            if isinstance(v, (int, float))
        },
        line_comments=line_comments,
        global_comments=global_comments,
        folder_structure_issues=folder_issues,
        architecture_issues=arch_issues,
        file_size_violations=size_violations,
        summary=str(data.get("summary", "")),
    )
    review.compute_overall_score()
    return review

