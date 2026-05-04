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

from ..config.schema import AgentOSConfig
from ..module_maker.schema import ModuleDefinition
from .frameworks import load_template
from .schema import FileVerdict, ReviewFeedback

logger = logging.getLogger(__name__)


class PromptGeneratorRunner:
    """Generate a framework-based prompt for a single module."""

    def __init__(self, config: AgentOSConfig, identity_ctx=None) -> None:
        self._config = config
        self._identity_ctx = identity_ctx

    def run(
        self,
        module_def: ModuleDefinition,
        iteration: int,
        review: Optional[ReviewFeedback] = None,
        on_stdout: Optional[Callable[[str], None]] = None,
    ) -> Path:
        """Build the prompt and write it to a stamped file. Returns the path."""
        # Always build a full template-based prompt with the complete module spec.
        # For iteration 2+, the review feedback is included via the review_section
        # so the code generator has the full context to make targeted changes.
        template = load_template(self._config.prompt_framework)
        filled = self._fill_template(template, module_def, review)
        prompt = self._enrich_via_chat(filled, module_def, iteration, review)
        return self._write_prompt(prompt, module_def.module_id, iteration, self._config)

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
    # Chat-based full rewrite — structure constrained, content free
    # ------------------------------------------------------------------

    def _enrich_via_chat(
        self,
        draft: str,
        mod: ModuleDefinition,
        iteration: int,
        review: Optional[ReviewFeedback],
    ) -> str:
        """Fully rewrite the draft prompt via an LLM.

        The LLM has maximum freedom over content, emphasis, ordering, and
        depth — but must preserve every technical artefact (file paths, API
        routes, class/function signatures, DB schemas, constraints) verbatim.

        For iteration 1 the focus is on clarity and implementation depth.
        For iteration 2+ the review failures become the most prominent section
        and the spec is reframed as context rather than the primary directive.
        """
        api_key = self._config.secrets.openai_api_key
        if not api_key:
            logger.info("No OpenAI API key — skipping prompt rewrite for %s", mod.module_id)
            return draft

        model = self._config.codex.model_routing.get("PROMPT_GENERATOR", "gpt-4.1-mini")
        is_review_iteration = iteration > 1 and review and review.files

        # ── Structural constraints (same for every iteration) ──────────────
        structural_rules = (
            "STRUCTURAL CONSTRAINTS — you MUST respect these no matter what:\n"
            "1. Every file path listed in the draft must appear in your output, "
            "word-for-word, in a clearly labelled section.\n"
            "2. Every API endpoint (method + path) must appear verbatim.\n"
            "3. Every class name, method signature, function signature, and "
            "database table/column definition must appear verbatim.\n"
            "4. Every constraint bullet must appear verbatim.\n"
            "5. Do NOT invent new endpoints, classes, functions, tables, or files "
            "that are not in the draft.\n"
            "6. Do NOT remove any of the above artefacts.\n"
            "7. End with an Output Format section that tells the code generator "
            "to write a summary.md listing each file created/modified, ending "
            "with the word END on its own line.\n"
        )

        # ── Content freedom (same for every iteration) ─────────────────────
        content_freedom = (
            "CONTENT FREEDOM — within the structural constraints above, you have "
            "full editorial control:\n"
            "- Choose the most effective section order for this specific module.\n"
            "- Decide how much detail to give each section based on complexity.\n"
            "- Write rich, module-specific implementation guidance: if there are "
            "tricky SQL constraints, call them out. If there are circular-import "
            "risks, warn about them. If auth middleware must be applied to certain "
            "routes, specify that explicitly.\n"
            "- Write the Role/Context framing to match exactly what THIS module "
            "does — not a generic developer persona.\n"
            "- Add module-specific gotchas, sequencing advice, or "
            "dependency-handling notes wherever they add value.\n"
            "- Use whatever Markdown formatting best communicates priority and "
            "structure (callout blocks, numbered steps, warning sections, etc.).\n"
            "- Vary the depth: a trivial utility module may need only a compact "
            "prompt, while a complex auth or DB module needs exhaustive detail.\n"
        )

        if is_review_iteration:
            # ── Review iteration directive ──────────────────────────────────
            focus_directive = (
                f"ITERATION FOCUS — this is iteration {iteration} of the module. "
                "A code reviewer found problems in the previous iteration.\n\n"
                "Your PRIMARY task is to make the review failures impossible to miss. "
                "Structure the prompt so that:\n"
                "1. The FIRST major section is a high-visibility 'Critical Fixes Required' "
                "block that lists every reviewer complaint with a concrete, actionable "
                "fix instruction for each.\n"
                "2. Files marked ACCEPTED by the reviewer must be listed as "
                "'DO NOT MODIFY' with a warning.\n"
                "3. The full module spec (APIs, classes, DB schemas, etc.) follows the "
                "fixes section — reframe it as 'Reference Spec' to remind the code "
                "generator what contracts must stay intact while applying the fixes.\n"
                "4. Make it absolutely clear: this is a targeted fix run, not a "
                "ground-up rewrite, unless a file is explicitly marked REGENERATE.\n"
            )
        else:
            # ── First-iteration directive ───────────────────────────────────
            focus_directive = (
                "ITERATION FOCUS — this is the FIRST implementation of this module. "
                "There is no prior code to fix.\n\n"
                "Your task is to produce the clearest, most implementation-ready "
                "prompt possible. Think like a senior engineer handing a module spec "
                "to a capable but junior developer:\n"
                "1. Lead with a crisp, module-specific Role and Objective — not a "
                "generic 'you are a developer' statement.\n"
                "2. Identify and call out the 2–3 most likely implementation pitfalls "
                "for THIS specific module (e.g. transaction handling, auth context "
                "propagation, schema migration ordering).\n"
                "3. If multiple files need to created in a specific order "
                "(e.g. models before routes), make that sequencing explicit.\n"
                "4. For DB modules: emphasise exact column types, constraints, and "
                "index names. For API modules: emphasise exact request/response "
                "shape and status codes. Adapt the emphasis to the module type.\n"
            )

        system_prompt = "\n\n".join(filter(None, [
            self._identity_ctx.build_role_preamble() if self._identity_ctx else "",
            "You are an expert prompt engineer specialising in code-generation "
            "prompts for autonomous coding agents (like Codex, Claude, or GPT-4). "
            "You will be given a draft code-generation prompt built from a structured "
            "module specification. Your job is to REWRITE it into the highest-quality "
            "prompt possible for that specific module.",
            structural_rules,
            content_freedom,
            focus_directive,
            "Return ONLY the final rewritten prompt — no preamble, no commentary, "
            "no 'Here is the rewritten prompt:' header. Start directly with the "
            "prompt content.",
        ]))

        user_prompt = (
            f"Rewrite this code-generation prompt for the **{mod.name}** module "
            f"(iteration {iteration}).\n\n"
            "Draft prompt to rewrite:\n"
            "---\n"
            f"{draft}\n"
            "---\n\n"
            "Return the fully rewritten prompt now."
        )

        try:
            import openai

            client = openai.OpenAI(api_key=api_key)
            resp = client.chat.completions.create(
                model=model,
                temperature=0.7,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            rewritten = resp.choices[0].message.content
            if rewritten and rewritten.strip():
                logger.info(
                    "Prompt rewritten via LLM for %s iter %d (%d → %d chars)",
                    mod.module_id, iteration, len(draft), len(rewritten),
                )
                return rewritten.strip()
        except Exception:
            logger.warning(
                "LLM prompt rewrite failed for %s — using template draft.",
                mod.module_id,
                exc_info=True,
            )
        return draft

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
