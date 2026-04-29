"""Prompt Generator runner — builds framework-based prompts from module definitions.

Fills template programmatically with structural data from the module JSON,
then (optionally) enriches natural-language descriptions via OpenAI chat.
Handles first-iteration and subsequent-iteration (review feedback) modes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional

from ..config.schema import AgentOSConfig, PromptFramework
from ..module_maker.schema import ModuleDefinition
from .frameworks import load_template
from .schema import FileVerdict, ReviewFeedback

logger = logging.getLogger(__name__)


class PromptGeneratorRunner:
    """Generate a framework-based prompt for a single module."""

    def __init__(self, config: AgentOSConfig) -> None:
        self._config = config

    def run(
        self,
        module_def: ModuleDefinition,
        iteration: int,
        review: Optional[ReviewFeedback] = None,
        on_stdout: Optional[Callable[[str], None]] = None,
    ) -> Path:
        """Build the prompt and write it to a stamped file. Returns the path."""
        if iteration > 1 and review and review.files:
            # Refinement iteration: generate a focused change-only prompt
            prompt = self._build_refinement_prompt(module_def, iteration, review)
        else:
            # First iteration: full template-based prompt
            template = load_template(self._config.prompt_framework)
            filled = self._fill_template(template, module_def, review)
            prompt = self._enrich_via_chat(filled, module_def)
        return self._write_prompt(prompt, module_def.module_id, iteration, self._config)

    # ------------------------------------------------------------------
    # Refinement prompt (iteration 2+) — focused exclusively on changes
    # ------------------------------------------------------------------

    def _build_refinement_prompt(
        self,
        mod: ModuleDefinition,
        iteration: int,
        review: ReviewFeedback,
    ) -> str:
        """Build a change-only prompt from the code reviewer's feedback.

        Instead of repeating the full module spec, this tells the code
        generator exactly which files to modify and what changes to apply.
        Files marked ACCEPT are explicitly left alone.
        """
        project_name = self._config.project.name or "Agent OS Target"
        language = self._config.project.language

        accepted = []
        patches = []
        regenerates = []

        for fr in review.files:
            if fr.verdict == FileVerdict.ACCEPT:
                accepted.append(fr.file_path)
            elif fr.verdict == FileVerdict.PATCH:
                patches.append(fr)
            elif fr.verdict == FileVerdict.REGENERATE:
                regenerates.append(fr)

        lines = [
            f"# {mod.name} — Iteration {iteration} Refinement",
            "",
            "---",
            "",
            "## Role",
            "",
            f"You are an expert **{language}** developer performing a targeted "
            f"code refinement for module `{mod.name}` in the **{project_name}** project.",
            "",
            "---",
            "",
            "## IMPORTANT — This Is a Refinement, NOT a Full Rewrite",
            "",
            "The codebase for this module already exists from the previous iteration. "
            "You MUST only apply the specific changes described below. "
            "Do NOT regenerate files that are marked as ACCEPTED. "
            "Do NOT rewrite entire files when only a patch is requested.",
            "",
            "---",
            "",
        ]

        # Accepted files — do not touch
        if accepted:
            lines.append("## Files to LEAVE UNCHANGED (ACCEPTED)")
            lines.append("")
            for fp in accepted:
                lines.append(f"- `{fp}` — **DO NOT MODIFY**")
            lines.append("")
            lines.append("---")
            lines.append("")

        # Patch files — targeted fixes
        if patches:
            lines.append("## Files to PATCH (apply targeted fixes)")
            lines.append("")
            for fr in patches:
                lines.append(f"### `{fr.file_path}`")
                lines.append("")
                lines.append("Apply the following changes:")
                lines.append("")
                for c in fr.comments:
                    lines.append(f"- {c}")
                lines.append("")
            lines.append("---")
            lines.append("")

        # Regenerate files — full rewrite needed
        if regenerates:
            lines.append("## Files to REGENERATE (full rewrite)")
            lines.append("")
            for fr in regenerates:
                lines.append(f"### `{fr.file_path}`")
                lines.append("")
                lines.append("Completely rewrite this file addressing:")
                lines.append("")
                for c in fr.comments:
                    lines.append(f"- {c}")
                lines.append("")
            lines.append("---")
            lines.append("")

        # Reviewer summary
        if review.summary:
            lines.append("## Reviewer Summary")
            lines.append("")
            lines.append(review.summary)
            lines.append("")
            lines.append("---")
            lines.append("")

        # Rules
        lines.extend([
            "## Rules for This Refinement",
            "",
            "1. **ONLY** modify or rewrite the files listed above.",
            "2. Do NOT create new files unless explicitly stated in a change.",
            "3. Do NOT remove, rename, or add API endpoints, classes, functions, "
            "or database tables beyond what the reviewer requested.",
            "4. Preserve all existing functionality that was accepted.",
            "5. After applying changes, write `summary.md` listing each file you "
            "modified and what you changed. End with the word END on its own line.",
        ])

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Template filling (programmatic — no LLM)
    # ------------------------------------------------------------------

    def _fill_template(
        self,
        template: str,
        mod: ModuleDefinition,
        review: Optional[ReviewFeedback],
    ) -> str:
        return template.format(
            module_name=mod.name,
            project_name=self._config.project.name or "Agent OS Target",
            language=self._config.project.language,
            description=mod.description or "(no description)",
            technical_spec=mod.technical_spec or "(no spec)",
            dependencies=", ".join(mod.dependencies) if mod.dependencies else "None",
            api_section=self._format_apis(mod),
            class_section=self._format_classes(mod),
            function_section=self._format_functions(mod),
            db_section=self._format_db_schemas(mod),
            file_paths_section=self._format_file_paths(mod),
            constraints_section=self._format_constraints(mod),
            testing_section=self._format_testing(mod),
            review_section=self._format_review(review),
        )

    @staticmethod
    def _format_apis(mod: ModuleDefinition) -> str:
        if not mod.apis:
            return "None"
        lines = []
        for api in mod.apis:
            lines.append(f"#### `{api.method} {api.path}`")
            if api.description:
                lines.append(f"  {api.description}")
            if api.request_body:
                lines.append(f"  - **Request body**: `{api.request_body}`")
            if api.response_body:
                lines.append(f"  - **Response body**: `{api.response_body}`")
            if api.status_codes:
                lines.append(f"  - **Status codes**: {', '.join(api.status_codes)}")
        return "\n".join(lines)

    @staticmethod
    def _format_classes(mod: ModuleDefinition) -> str:
        if not mod.classes:
            return "None"
        lines = []
        for cls in mod.classes:
            lines.append(f"#### `{cls.name}`")
            if cls.description:
                lines.append(f"  {cls.description}")
            if cls.attributes:
                lines.append("  **Attributes:**")
                for attr in cls.attributes:
                    lines.append(f"  - `{attr}`")
            if cls.methods:
                lines.append("  **Methods:**")
                for method in cls.methods:
                    lines.append(f"  - `{method}`")
        return "\n".join(lines)

    @staticmethod
    def _format_functions(mod: ModuleDefinition) -> str:
        if not mod.functions:
            return "None"
        lines = []
        for fn in mod.functions:
            params = ", ".join(fn.params) if fn.params else ""
            ret = f" → {fn.returns}" if fn.returns else ""
            lines.append(f"#### `{fn.name}({params}){ret}`")
            if fn.description:
                lines.append(f"  {fn.description}")
            if fn.raises:
                lines.append(f"  **Raises**: {', '.join(fn.raises)}")
        return "\n".join(lines)

    @staticmethod
    def _format_db_schemas(mod: ModuleDefinition) -> str:
        if not mod.db_schemas:
            return "None"
        lines = []
        for db in mod.db_schemas:
            lines.append(f"#### Table: `{db.table_name}`")
            if db.description:
                lines.append(f"  {db.description}")
            if db.columns:
                lines.append("  **Columns:**")
                for col in db.columns:
                    lines.append(f"  - `{col}`")
            if db.indexes:
                lines.append("  **Indexes:**")
                for idx in db.indexes:
                    lines.append(f"  - `{idx}`")
            if db.constraints:
                lines.append("  **Constraints:**")
                for con in db.constraints:
                    lines.append(f"  - `{con}`")
        return "\n".join(lines)

    @staticmethod
    def _format_file_paths(mod: ModuleDefinition) -> str:
        if not mod.file_paths:
            return "Determine appropriate file paths based on project structure."
        return "\n".join(f"- `{p}`" for p in mod.file_paths)

    @staticmethod
    def _format_constraints(mod: ModuleDefinition) -> str:
        if not mod.constraints:
            return "None specified."
        return "\n".join(f"- {c}" for c in mod.constraints)

    @staticmethod
    def _format_testing(mod: ModuleDefinition) -> str:
        if not mod.testing_notes:
            return "Write unit tests for all public interfaces."
        return mod.testing_notes

    @staticmethod
    def _format_review(review: Optional[ReviewFeedback]) -> str:
        if not review or not review.files:
            return ""
        lines = ["## Review Feedback (from previous iteration)", ""]
        for fr in review.files:
            if fr.verdict == FileVerdict.ACCEPT:
                lines.append(f"- `{fr.file_path}`: **ACCEPTED** — do not modify.")
            elif fr.verdict == FileVerdict.PATCH:
                lines.append(f"- `{fr.file_path}`: **PATCH** — apply targeted fixes:")
                for c in fr.comments:
                    lines.append(f"  - {c}")
            elif fr.verdict == FileVerdict.REGENERATE:
                lines.append(f"- `{fr.file_path}`: **REGENERATE** — rewrite this file:")
                for c in fr.comments:
                    lines.append(f"  - {c}")
        if review.summary:
            lines.append(f"\n**Reviewer summary**: {review.summary}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Chat-based enrichment (natural-language descriptions only)
    # ------------------------------------------------------------------

    def _enrich_via_chat(self, prompt: str, mod: ModuleDefinition) -> str:
        """Use OpenAI chat completions to refine natural-language descriptions.

        Unlike codex exec (which generates code), chat completions only
        refine the text, preserving the RCTCF structure intact.
        """
        api_key = self._config.secrets.openai_api_key
        if not api_key:
            logger.info("No OpenAI API key — skipping prompt enrichment for %s", mod.module_id)
            return prompt

        model = self._config.codex.model_routing.get("PROMPT_GENERATOR", "gpt-4.1-mini")

        try:
            import openai

            client = openai.OpenAI(api_key=api_key)
            resp = client.chat.completions.create(
                model=model,
                temperature=0.3,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a technical writing editor. You refine code-generation "
                            "prompts for clarity and precision. "
                            "RULES:\n"
                            "1. Do NOT add, rename, or remove any endpoints, classes, "
                            "functions, tables, columns, file paths, or constraints.\n"
                            "2. Do NOT invent features, routes, or schemas not in the "
                            "original prompt.\n"
                            "3. Only improve clarity and wording of natural-language "
                            "descriptions.\n"
                            "4. Keep ALL structural sections (API endpoints, classes, "
                            "functions, DB schemas, file paths, constraints) EXACTLY "
                            "as-is including formatting.\n"
                            "5. Keep ALL markdown headings, bullet points, and code "
                            "blocks exactly as-is.\n"
                            "6. Return the FULL prompt text unchanged except for improved "
                            "descriptions.\n"
                            "7. Do NOT generate code, patches, diffs, or implementation. "
                            "Return only the refined prompt document."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Refine the following code-generation prompt. "
                            "Return the full prompt with only wording improvements.\n\n"
                            f"{prompt}"
                        ),
                    },
                ],
            )
            enriched = resp.choices[0].message.content
            if enriched and enriched.strip():
                logger.info(
                    "Prompt enriched via chat for %s (%d → %d chars)",
                    mod.module_id, len(prompt), len(enriched),
                )
                return enriched.strip()
        except Exception:
            logger.warning(
                "Chat enrichment failed for %s — using programmatic prompt.",
                mod.module_id,
                exc_info=True,
            )
        return prompt

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    @staticmethod
    def _write_prompt(content: str, module_id: str, iteration: int, config: "AgentOSConfig") -> Path:
        out_dir = config.storage.data_dir / "prompts" / f"module-{module_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"iteration-{iteration}.md"
        path.write_text(content, encoding="utf-8")
        logger.info("Wrote prompt: %s (%d chars)", path, len(content))
        return path
