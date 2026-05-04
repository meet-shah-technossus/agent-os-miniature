"""Code Reviewer — invokes Codex CLI to produce a structured code review."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..codex.session import CodexResult, SessionType
from ..codex.wrapper import CodexWrapper
from ..config.schema import AgentOSConfig
from ..module_maker.schema import ModuleDefinition
from ..validation.schema import ValidationResult
from .schema import CodeReviewResult

logger = logging.getLogger(__name__)

_REVIEW_SYSTEM_PROMPT = """\
You are a senior code reviewer. Analyse the generated code using the provided:
1. Validation results (lint, type-check, tests, security)
2. Module specification (APIs, classes, functions, schemas)
3. Acceptance criteria

Produce a JSON object with EXACTLY the following structure:
{
  "overall_status": "accepted" | "needs_work" | "rejected",
  "convergence_score": <0-100>,
  "files": [
    {
      "file_path": "<path>",
      "action": "accept" | "patch" | "regenerate",
      "issues": [
        {
          "id": "<unique-id>",
          "file": "<path>",
          "line_start": <int>,
          "line_end": <int>,
          "severity": "critical" | "high" | "medium" | "low" | "info",
          "category": "bug" | "security" | "performance" | "design" | "style" | "testing" | "documentation" | "other",
          "issue": "<description>",
          "suggested_fix": "<fix>"
        }
      ],
      "comments": ["<comment>"]
    }
  ],
  "acceptance_criteria": [
    {"ac_id": "<id>", "description": "<text>", "passed": true|false, "evidence": "<reason>"}
  ],
  "area_scores": [
    {"area": "design", "score": <0-100>, "notes": "<text>"},
    {"area": "security", "score": <0-100>, "notes": "<text>"},
    {"area": "testing", "score": <0-100>, "notes": "<text>"},
    {"area": "performance", "score": <0-100>, "notes": "<text>"}
  ],
  "summary": "<brief review summary>"
}

Output ONLY valid JSON. No markdown, no explanation outside the JSON.
"""


@dataclass
class ReviewRunResult:
    """Wraps the review output along with Codex metadata."""

    review: CodeReviewResult
    codex_result: CodexResult
    raw_json: str = ""


class CodeReviewerRunner:
    """Runs a code review via Codex CLI and parses the structured result."""

    def __init__(self, config: AgentOSConfig, identity_ctx=None) -> None:
        self._identity_ctx = identity_ctx
        self._wrapper = CodexWrapper(
            timeout_seconds=config.codex.timeout_seconds,
            max_retries=0,  # We handle retry logic externally if needed
            openai_api_key=config.secrets.openai_api_key,
            project_root=config.project.root_path or ".",
            model_routing=config.codex.model_routing,
            default_model=config.codex.model,
        )

    def run(
        self,
        module_def: ModuleDefinition,
        iteration: int,
        validation_result: Optional[ValidationResult] = None,
        working_dir: str = ".",
        on_stdout: Optional[Callable[[str], None]] = None,
    ) -> ReviewRunResult:
        prompt = self._build_prompt(module_def, iteration, validation_result, working_dir)
        codex_result = self._wrapper.execute(
            prompt=prompt,
            working_dir=working_dir,
            session_type=SessionType.CODE_REVIEWER,
            on_stdout=on_stdout,
        )

        review = self._parse_review(
            codex_result, module_def.module_id, iteration,
        )
        raw = codex_result.stdout.strip()

        return ReviewRunResult(
            review=review,
            codex_result=codex_result,
            raw_json=raw,
        )

    def _build_prompt(
        self,
        module_def: ModuleDefinition,
        iteration: int,
        validation_result: Optional[ValidationResult],
        working_dir: str = ".",
    ) -> str:
        preamble = self._identity_ctx.build_preamble() if self._identity_ctx else ""
        parts = [preamble + _REVIEW_SYSTEM_PROMPT] if preamble else [_REVIEW_SYSTEM_PROMPT]

        parts.append(f"\n## Module: {module_def.module_id} — {module_def.name}")
        parts.append(f"Iteration: {iteration}")

        if module_def.description:
            parts.append(f"\n### Description\n{module_def.description}")

        if module_def.technical_spec:
            parts.append(f"\n### Technical Spec\n{module_def.technical_spec}")

        # File list + actual contents from disk
        if module_def.file_paths:
            parts.append("\n### Expected Files")
            wd = Path(working_dir)
            missing_files: list[str] = []
            found_files: list[str] = []
            for fp in module_def.file_paths:
                full = wd / fp
                if full.is_file():
                    found_files.append(fp)
                    parts.append(f"\n#### `{fp}` (exists)")
                    try:
                        content = full.read_text(encoding="utf-8", errors="replace")
                        # Cap at 500 lines to avoid prompt explosion
                        lines = content.splitlines()
                        if len(lines) > 500:
                            content = "\n".join(lines[:500]) + "\n... (truncated)"
                        parts.append(f"```\n{content}\n```")
                    except Exception:
                        parts.append("(could not read file)")
                else:
                    missing_files.append(fp)
                    parts.append(f"- `{fp}` — **MISSING (not generated)**")

            if missing_files and not found_files:
                parts.append(
                    "\n**WARNING: No source files were generated. "
                    "All expected files are missing from the project folder. "
                    "The review should reflect that code generation failed.**"
                )

        # Validation data
        if validation_result:
            parts.append("\n### Validation Results")
            for tool in validation_result.tools:
                status = "SKIPPED" if tool.skipped else ("PASS" if tool.passed else "FAIL")
                parts.append(
                    f"- {tool.tool}: {status} "
                    f"({tool.error_count}E / {tool.warning_count}W)"
                )
                for issue in tool.issues[:20]:  # Cap to avoid prompt explosion
                    parts.append(
                        f"  - {issue.severity.value}: {issue.file}:{issue.line} "
                        f"{issue.message}"
                    )

        return "\n".join(parts)

    def _parse_review(
        self,
        codex_result: CodexResult,
        module_id: str,
        iteration: int,
    ) -> CodeReviewResult:
        """Parse Codex stdout as JSON into CodeReviewResult."""
        if codex_result.exit_code != 0:
            logger.warning(
                "Code review Codex call failed (exit %d), returning empty review",
                codex_result.exit_code,
            )
            return CodeReviewResult(
                module_id=module_id,
                iteration=iteration,
                overall_status="needs_work",
                summary=f"Review failed: Codex exit code {codex_result.exit_code}",
            )

        raw = codex_result.stdout.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            lines = raw.splitlines()
            lines = [l for l in lines if not l.startswith("```")]
            raw = "\n".join(lines)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Code review output is not valid JSON")
            return CodeReviewResult(
                module_id=module_id,
                iteration=iteration,
                overall_status="needs_work",
                summary="Review parse error: Codex output was not valid JSON",
            )

        data["module_id"] = module_id
        data["iteration"] = iteration

        try:
            review = CodeReviewResult.model_validate(data)
        except Exception as exc:
            logger.warning("Code review JSON schema validation failed: %s", exc)
            return CodeReviewResult(
                module_id=module_id,
                iteration=iteration,
                overall_status="needs_work",
                summary=f"Review schema error: {exc}",
            )

        review.compute_summary_fields()
        return review


def store_review_result(review: CodeReviewResult, config: "AgentOSConfig | None" = None) -> Path:
    """Persist review JSON to disk."""
    if config is not None:
        out_dir = config.storage.data_dir / "reviews" / review.module_id
    else:
        out_dir = Path(f"data/reviews/{review.module_id}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"iteration-{review.iteration}.json"
    out_path.write_text(review.model_dump_json(indent=2), encoding="utf-8")
    return out_path
