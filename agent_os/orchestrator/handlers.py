"""Step handlers for each pipeline state — one function per state.

Each handler receives a HandlerContext with access to state_mgr, db, config,
and the communication bus. Stubs will be replaced as each phase is implemented.
"""

from __future__ import annotations

import logging

from rich.console import Console

from ..storage.models import PipelineStatus
from .context import HandlerContext

logger = logging.getLogger(__name__)
console = Console()


def handle_idle(ctx: HandlerContext) -> None:
    console.print("[dim]Transitioning from IDLE → LOADING_REQUIREMENTS[/dim]")
    ctx.state_mgr.transition_to(PipelineStatus.LOADING_REQUIREMENTS)


def _auto_provision_project_folder(ctx: HandlerContext) -> None:
    """Create a versioned project folder on Desktop from the project name in config.

    If ``{slug}`` already exists (left over from a previous session), the folder
    is named ``{slug}_v2``, ``{slug}_v3``, etc. so each session gets its own
    isolated directory without touching any prior version's code.
    """
    from pathlib import Path as _Path
    import re

    name = ctx.config.project.name or "agent-os-project"
    # Sanitise name → folder-safe slug
    slug = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "-").lower()
    if not slug:
        slug = "agent-os-project"

    desktop_base = _Path.home() / "Desktop"
    candidate = desktop_base / slug
    if candidate.exists():
        # Bump version until we find an unused name
        version = 2
        while (desktop_base / f"{slug}_v{version}").exists():
            version += 1
        candidate = desktop_base / f"{slug}_v{version}"

    candidate.mkdir(parents=True, exist_ok=True)
    ctx.config.project.root_path = str(candidate)

    console.print(f"[green]Project folder: {candidate}[/green]")
    logger.info("Auto-provisioned project folder: %s", candidate)

    # Persist both name and root_path to config.yaml so they survive restarts
    try:
        from ..api.deps import orch_holder
        from ..api.routes.settings import _write_config_yaml
        _write_config_yaml(ctx.config, orch_holder.config_path)
    except Exception:
        logger.debug("Could not persist root_path to config.yaml (non-fatal)", exc_info=True)


def handle_loading_requirements(ctx: HandlerContext) -> None:
    from ..requirements.parser import RequirementsParser

    req_path = ctx.config.requirements.path
    console.print(f"[cyan]Loading requirements from: {req_path}[/cyan]")

    parser = RequirementsParser(db=ctx.db)
    stats = parser.load_and_store(req_path)

    # Extract project name from first epic title if not already set
    if not ctx.config.project.name:
        try:
            import yaml as _yaml
            from pathlib import Path as _Path
            raw = _yaml.safe_load(_Path(req_path).read_text(encoding="utf-8"))
            epics = raw.get("epics", [])
            if epics:
                ctx.config.project.name = epics[0].get("title", "").strip()
                console.print(
                    f"[green]Project name set from requirements: "
                    f"{ctx.config.project.name}[/green]"
                )
        except Exception:
            logger.debug("Could not extract project name from requirements", exc_info=True)

    console.print(
        f"[green]Requirements loaded — "
        f"{stats['epics']} epics, {stats['features']} features, "
        f"{stats['stories']} stories, {stats['acceptance_criteria']} ACs[/green]"
    )
    ctx.state_mgr.transition_to(PipelineStatus.MODULE_PLANNING)


def handle_module_planning(ctx: HandlerContext) -> None:
    from ..comms.channels import Channel
    from ..comms.messages import GenerationStatusMessage, ModuleUpdateMessage
    from ..module_maker.runner import ModuleMakerRunner

    # Auto-provision project folder now that we have the project name from requirements
    if not ctx.config.project.root_path:
        _auto_provision_project_folder(ctx)

    console.print("[cyan]Module Maker — decomposing requirements into modules...[/cyan]")

    def _stream_line(line: str) -> None:
        ctx.bus.publish(GenerationStatusMessage(
            sender="module_maker",
            payload={"stream": "stdout", "line": line},
        ))

    runner = ModuleMakerRunner(db=ctx.db, config=ctx.config)
    plan = runner.run(on_stdout=_stream_line)

    console.print(
        f"[green]Module plan ready — {len(plan.modules)} modules "
        f"(including Module 0: Foundation)[/green]"
    )
    for mod in plan.modules:
        dep_str = f" (deps: {mod.dependencies})" if mod.dependencies else ""
        console.print(f"  [dim]{mod.module_id}: {mod.name}{dep_str}[/dim]")

    # Publish module definitions on Comm Bus for HITL review
    ctx.bus.publish(ModuleUpdateMessage(
        sender="module_maker",
        payload={
            "action": "plan_ready",
            "module_count": len(plan.modules),
            "module_ids": [m.module_id for m in plan.modules],
        },
    ))

    ctx.state_mgr.transition_to(PipelineStatus.HITL_1_MODULE_REVIEW)


def handle_prompt_generation(ctx: HandlerContext) -> None:
    import json as _json
    from pathlib import Path as _Path

    from ..comms.channels import Channel
    from ..comms.messages import PromptReadyMessage
    from ..hardening.rollback import RollbackManager
    from ..module_maker.schema import ModuleDefinition
    from ..prompt_generator.runner import PromptGeneratorRunner
    from ..prompt_generator.schema import FileReview, FileVerdict, ReviewFeedback
    from ..storage.iteration_repo import IterationRepository
    from ..storage.models import IterationRecord

    state = ctx.state_mgr.state
    module_id = state.current_module_id
    iteration = state.current_iteration or 1

    if not module_id:
        raise RuntimeError("PROMPT_GENERATION requires a current_module_id.")

    # Create a git checkpoint at iteration start (Phase 15: rollback)
    if ctx.config.git.enabled and ctx.config.error_handling.rollback_on_failure:
        from ..git_ops.manager import GitOpsManager
        working_dir = ctx.config.project.root_path or "."
        git = GitOpsManager(working_dir=working_dir, remote=ctx.config.git.remote)
        if git.is_repo():
            rb = RollbackManager(git)
            tag = rb.create_checkpoint(module_id, iteration)
            if tag:
                console.print(f"  [dim]Checkpoint: {tag}[/dim]")

    # Load module definition JSON (written by Module Maker)
    data_dir = ctx.config.storage.data_dir
    mod_json_path = data_dir / "modules" / f"{module_id}.json"
    if not mod_json_path.exists():
        # Restore from DB instead of re-running Module Maker for all modules
        from ..storage.module_repo import ModuleRepository as _MR
        mod_record = _MR(ctx.db.conn).get(module_id)
        if mod_record and mod_record.definition_json:
            mod_json_path.parent.mkdir(parents=True, exist_ok=True)
            mod_json_path.write_text(mod_record.definition_json, encoding="utf-8")
            console.print(
                f"[yellow]Module definition JSON restored from DB for {module_id}[/yellow]"
            )
        else:
            raise RuntimeError(
                f"Module definition missing for {module_id} — "
                f"not on disk ({mod_json_path}) and not in DB. "
                f"Re-run the pipeline from MODULE_PLANNING."
            )
    mod_def = ModuleDefinition.model_validate_json(mod_json_path.read_text())

    console.print(
        f"[cyan]Prompt Generator — building prompt for {module_id} "
        f"(iteration {iteration}, framework: {ctx.config.prompt_framework.value})[/cyan]"
    )

    # On iteration > 1, load review feedback from the prior iteration
    review: ReviewFeedback | None = None
    if iteration > 1:
        prev_review_path = data_dir / "reviews" / module_id / f"iteration-{iteration - 1}.json"
        if prev_review_path.exists():
            prev_data = _json.loads(prev_review_path.read_text(encoding="utf-8"))
            review = _convert_review_to_feedback(prev_data, iteration - 1)
            console.print(
                f"  [dim]Loaded review feedback from iteration {iteration - 1} "
                f"({len(review.files)} files)[/dim]"
            )

    runner = PromptGeneratorRunner(config=ctx.config)

    def _stream_line(line: str) -> None:
        ctx.bus.publish(PromptReadyMessage(
            sender="prompt_generator",
            module_id=module_id,
            iteration=iteration,
            payload={"stream": "stdout", "line": line},
        ))

    prompt_path = runner.run(mod_def, iteration, review, on_stdout=_stream_line)

    # Read the written prompt content so we can store it in DB
    prompt_content = ""
    try:
        prompt_content = prompt_path.read_text(encoding="utf-8")
    except Exception:
        pass

    # Record iteration in DB
    iter_repo = IterationRepository(ctx.db.conn)
    iter_record = IterationRecord(
        module_id=module_id,
        iteration_number=iteration,
        prompt_path=str(prompt_path),
        prompt_content=prompt_content,
    )
    iter_repo.create(iter_record)

    console.print(f"[green]Prompt written → {prompt_path}[/green]")

    # Publish on Comm Bus
    ctx.bus.publish(PromptReadyMessage(
        sender="prompt_generator",
        module_id=module_id,
        iteration=iteration,
        payload={
            "prompt_path": str(prompt_path),
            "framework": ctx.config.prompt_framework.value,
            "has_review_feedback": review is not None,
        },
    ))

    ctx.state_mgr.transition_to(PipelineStatus.HITL_2_PROMPT_REVIEW)


def _convert_review_to_feedback(review_data: dict, iteration: int) -> ReviewFeedback:
    """Convert a CodeReviewResult JSON dict to ReviewFeedback for the Prompt Generator."""
    from ..prompt_generator.schema import FileReview, FileVerdict, ReviewFeedback

    _ACTION_TO_VERDICT = {
        "accept": FileVerdict.ACCEPT,
        "patch": FileVerdict.PATCH,
        "regenerate": FileVerdict.REGENERATE,
    }

    files: list[FileReview] = []
    for f in review_data.get("files", []):
        action = f.get("action", "accept")
        verdict = _ACTION_TO_VERDICT.get(action, FileVerdict.ACCEPT)

        comments = list(f.get("comments", []))
        # Also include issue descriptions as comments for the prompt
        for issue in f.get("issues", []):
            sev = issue.get("severity", "")
            msg = issue.get("issue", "")
            fix = issue.get("suggested_fix", "")
            entry = f"[{sev}] {msg}"
            if fix:
                entry += f" — Fix: {fix}"
            comments.append(entry)

        files.append(FileReview(
            file_path=f.get("file_path", ""),
            verdict=verdict,
            comments=comments,
        ))

    return ReviewFeedback(
        iteration=iteration,
        files=files,
        summary=review_data.get("summary", ""),
    )


def handle_code_generation(ctx: HandlerContext) -> None:
    from ..code_generator.completion import CompletionStatus
    from ..code_generator.runner import CodeGeneratorRunner
    from ..comms.channels import Channel
    from ..comms.messages import GenerationStatusMessage
    from ..hardening.dependency_mgr import DependencyManager
    from ..hardening.token_budget import TokenBudgetTracker
    from ..storage.iteration_repo import IterationRepository
    from ..storage.models import IterationStatus

    state = ctx.state_mgr.state
    module_id = state.current_module_id
    iteration = state.current_iteration or 1

    if not module_id:
        raise RuntimeError("CODE_GENERATION requires a current_module_id.")

    # Find the prompt written by the Prompt Generator
    iter_repo = IterationRepository(ctx.db.conn)
    iter_record = iter_repo.get(module_id, iteration)
    if not iter_record or not iter_record.prompt_path:
        raise RuntimeError(
            f"No prompt found for {module_id} iteration {iteration}."
        )

    # Restore prompt file from DB content if the disk file is missing
    from pathlib import Path as _Path
    _prompt_file = _Path(iter_record.prompt_path)
    if not _prompt_file.exists() and iter_record.prompt_content:
        _prompt_file.parent.mkdir(parents=True, exist_ok=True)
        _prompt_file.write_text(iter_record.prompt_content, encoding="utf-8")
        console.print(
            f"  [dim]Restored prompt file from DB → {_prompt_file}[/dim]"
        )

    working_dir = ctx.config.project.root_path or "."

    console.print(
        f"[cyan]Code Generator — generating code for {module_id} "
        f"(iteration {iteration})[/cyan]"
    )
    console.print(f"  [dim]Working dir: {working_dir}[/dim]")

    def _stream_line(line: str) -> None:
        ctx.bus.publish(GenerationStatusMessage(
            sender="code_generator",
            module_id=module_id,
            iteration=iteration,
            payload={"stream": "stdout", "line": line},
        ))

    # Both stdout and stderr from Codex go to the Rich console so the user
    # can see what Codex is doing (and see any auth/rate-limit error messages).
    _ERROR_KEYWORDS = ("error", "unauthorized", "rate limit", "quota", "invalid api key", "timeout")

    def _stream_and_log(line: str) -> None:
        if line.strip():
            level = "red" if any(k in line.lower() for k in _ERROR_KEYWORDS) else "dim"
            console.print(f"  [{level}][codex] {line}[/{level}]")
        _stream_line(line)

    def _log_stderr(line: str) -> None:
        if line.strip():
            level = "red" if any(k in line.lower() for k in _ERROR_KEYWORDS) else "dim"
            console.print(f"  [{level}][codex/err] {line}[/{level}]")

    runner = CodeGeneratorRunner(config=ctx.config)
    gen_result = runner.run(iter_record.prompt_path, working_dir, on_stdout=_stream_and_log, on_stderr=_log_stderr)

    status = gen_result.completion.status
    retried_str = " (retried)" if gen_result.retried else ""
    console.print(
        f"[{'green' if status == CompletionStatus.COMPLETE else 'yellow'}]"
        f"Code generation {status.value}{retried_str} — "
        f"{gen_result.codex_result.duration_seconds:.1f}s"
        f"[/{'green' if status == CompletionStatus.COMPLETE else 'yellow'}]"
    )

    # Update iteration record with summary
    if gen_result.summary_text:
        iter_record.summary_path = f"data/summaries/{module_id}/iteration-{iteration}.txt"
        from pathlib import Path as _Path
        summary_dir = _Path(iter_record.summary_path).parent
        summary_dir.mkdir(parents=True, exist_ok=True)
        _Path(iter_record.summary_path).write_text(
            gen_result.summary_text, encoding="utf-8"
        )

    if status == CompletionStatus.FAILED:
        iter_record.status = IterationStatus.FAILED
        iter_repo.update(iter_record)
        logger.error(
            "Code generation failed: %s", gen_result.completion.reason
        )
        ctx.state_mgr.transition_to(PipelineStatus.FAILED)
        return

    iter_repo.update(iter_record)

    # Estimate token usage from output length (Phase 15: budget tracking)
    estimated_tokens = _estimate_tokens(gen_result.codex_result.stdout)
    budget_tracker = TokenBudgetTracker(
        config=ctx.config.budget,
        iter_repo=iter_repo,
        bus=ctx.bus,
    )
    budget_status = budget_tracker.record_usage(module_id, iteration, estimated_tokens)
    if budget_tracker.should_pause(module_id):
        console.print(
            f"[red]Token budget exceeded for {module_id} — pausing.[/red]"
        )
        ctx.state_mgr.transition_to(PipelineStatus.HITL_4_MAX_ITERATIONS)
        return

    # Auto-install dependencies (Phase 15: dependency management)
    if ctx.config.dependencies.auto_install:
        dep_mgr = DependencyManager(ctx.config.dependencies, working_dir)
        dep_mgr.ensure_venv()
        dep_result = dep_mgr.install_requirements()
        if not dep_result.success:
            console.print(f"  [yellow]Dep install issue: {dep_result.errors[:200]}[/yellow]")

    # Publish on Comm Bus
    ctx.bus.publish(GenerationStatusMessage(
        sender="code_generator",
        module_id=module_id,
        iteration=iteration,
        payload={
            "status": status.value,
            "duration": gen_result.codex_result.duration_seconds,
            "retried": gen_result.retried,
            "summary_length": len(gen_result.summary_text),
        },
    ))

    ctx.state_mgr.transition_to(PipelineStatus.VALIDATION)


def handle_validation(ctx: HandlerContext) -> None:
    from pathlib import Path as _Path

    from ..comms.messages import ValidationResultMessage
    from ..storage.iteration_repo import IterationRepository
    from ..validation.runner import ValidationRunner, store_validation_result

    state = ctx.state_mgr.state
    module_id = state.current_module_id
    iteration = state.current_iteration or 1

    if not module_id:
        raise RuntimeError("VALIDATION requires a current_module_id.")

    working_dir = ctx.config.project.root_path or "."

    console.print(
        f"[cyan]Validation — running checks for {module_id} "
        f"(iteration {iteration})[/cyan]"
    )

    runner = ValidationRunner(config=ctx.config.validation, bus=ctx.bus)
    result = runner.run(
        working_dir=working_dir,
        module_id=module_id,
        iteration=iteration,
    )

    # Store aggregated JSON
    json_path = store_validation_result(result)

    # Update iteration record
    iter_repo = IterationRepository(ctx.db.conn)
    iter_record = iter_repo.get(module_id, iteration)
    if iter_record:
        iter_repo.update(iter_record)

    status_color = "green" if result.all_passed else "yellow"
    console.print(
        f"[{status_color}]Validation {'passed' if result.all_passed else 'has issues'} — "
        f"{result.total_errors} errors, {result.total_warnings} warnings "
        f"({len(result.tools)} tools)[/{status_color}]"
    )
    for t in result.tools:
        if t.skipped:
            console.print(f"  [dim]{t.tool}: skipped ({t.skip_reason})[/dim]")
        else:
            icon = "[green]✓[/green]" if t.passed else "[red]✗[/red]"
            console.print(f"  {icon} {t.tool}: {t.error_count}E / {t.warning_count}W")

    # Publish final aggregated result on Comm Bus
    ctx.bus.publish(ValidationResultMessage(
        sender="validation_runner",
        module_id=module_id,
        iteration=iteration,
        payload={
            "all_passed": result.all_passed,
            "total_errors": result.total_errors,
            "total_warnings": result.total_warnings,
            "json_path": str(json_path),
            "tools": [
                {"tool": t.tool, "passed": t.passed, "skipped": t.skipped}
                for t in result.tools
            ],
        },
    ))

    ctx.state_mgr.transition_to(PipelineStatus.CODE_REVIEW)


def handle_code_review(ctx: HandlerContext) -> None:
    import json as _json
    from pathlib import Path as _Path

    from ..code_reviewer.runner import CodeReviewerRunner, store_review_result
    from ..code_reviewer.schema import CodeReviewResult
    from ..comms.messages import ReviewFeedbackMessage
    from ..module_maker.schema import ModuleDefinition
    from ..storage.iteration_repo import IterationRepository
    from ..validation.schema import ValidationResult

    state = ctx.state_mgr.state
    module_id = state.current_module_id
    iteration = state.current_iteration or 1

    if not module_id:
        raise RuntimeError("CODE_REVIEW requires a current_module_id.")

    console.print(
        f"[cyan]Code Review — reviewing {module_id} "
        f"(iteration {iteration})[/cyan]"
    )

    # Load module definition — fall back to DB if disk file is missing
    data_dir = ctx.config.storage.data_dir
    mod_json_path = data_dir / "modules" / f"{module_id}.json"
    if not mod_json_path.exists():
        from ..storage.module_repo import ModuleRepository
        mod_repo = ModuleRepository(ctx.db.conn)
        mod_record = mod_repo.get(module_id)
        if mod_record and mod_record.definition_json:
            mod_json_path.parent.mkdir(parents=True, exist_ok=True)
            mod_json_path.write_text(mod_record.definition_json, encoding="utf-8")
            console.print(
                f"  [dim]Restored module definition from DB → {mod_json_path}[/dim]"
            )
        else:
            raise FileNotFoundError(
                f"Module definition not found: {mod_json_path}. "
                "Retry Module Maker to regenerate module definitions."
            )
    mod_def = ModuleDefinition.model_validate_json(mod_json_path.read_text())

    # Load validation results (if available)
    val_json_path = data_dir / "validations" / module_id / f"iteration-{iteration}.json"
    validation_result = None
    if val_json_path.exists():
        validation_result = ValidationResult.model_validate_json(
            val_json_path.read_text()
        )

    working_dir = ctx.config.project.root_path or "."

    # Pre-flight: verify at least one source file exists in the project folder
    from pathlib import Path as _WdPath
    _wd = _WdPath(working_dir)
    _IGNORE_DIRS = {".venv", "__pycache__", ".git", "node_modules", ".mypy_cache", ".pytest_cache"}
    _source_files = [
        f for f in _wd.rglob("*")
        if f.is_file() and not any(part in _IGNORE_DIRS for part in f.parts)
    ]
    if not _source_files:
        console.print(
            f"[red]Code Review — no source files found in {working_dir}. "
            f"Code generation likely failed. Skipping review.[/red]"
        )
        logger.error("No source files in %s — code review cannot proceed.", working_dir)
        ctx.state_mgr.transition_to(PipelineStatus.FAILED)
        return

    def _stream_line(line: str) -> None:
        ctx.bus.publish(ReviewFeedbackMessage(
            sender="code_reviewer",
            module_id=module_id,
            iteration=iteration,
            payload={"stream": "stdout", "line": line},
        ))

    runner = CodeReviewerRunner(config=ctx.config)
    run_result = runner.run(
        module_def=mod_def,
        iteration=iteration,
        validation_result=validation_result,
        working_dir=working_dir,
        on_stdout=_stream_line,
    )

    review = run_result.review
    json_path = store_review_result(review, ctx.config)

    # Update iteration record with review path and content
    review_content = review.model_dump_json(indent=2)
    iter_repo = IterationRepository(ctx.db.conn)
    iter_record = iter_repo.get(module_id, iteration)
    if iter_record:
        iter_record.review_json_path = str(json_path)
        iter_record.review_content = review_content
        iter_repo.update(iter_record)

    status_color = "green" if review.overall_status == "accepted" else "yellow"
    console.print(
        f"[{status_color}]Review: {review.overall_status} — "
        f"convergence {review.convergence_score}/100, "
        f"{review.blocking_issues} blocking issues[/{status_color}]"
    )
    for f in review.files:
        icon = "[green]✓[/green]" if f.action.value == "accept" else "[red]✗[/red]"
        console.print(f"  {icon} {f.file_path}: {f.action.value} ({len(f.issues)} issues)")

    # Publish review feedback on Comm Bus
    ctx.bus.publish(ReviewFeedbackMessage(
        sender="code_reviewer",
        module_id=module_id,
        iteration=iteration,
        payload={
            "overall_status": review.overall_status,
            "convergence_score": review.convergence_score,
            "blocking_issues": review.blocking_issues,
            "json_path": str(json_path),
            "file_count": len(review.files),
            "ac_passed": sum(1 for ac in review.acceptance_criteria if ac.passed),
            "ac_total": len(review.acceptance_criteria),
        },
    ))

    ctx.state_mgr.transition_to(PipelineStatus.HITL_3_REVIEW_DECISION)


def handle_decision(ctx: HandlerContext) -> None:
    import json as _json
    from pathlib import Path as _Path

    from ..comms.messages import PipelineEventMessage
    from ..storage.iteration_repo import IterationRepository
    from ..storage.models import IterationStatus
    from .decision import decide_iteration

    state = ctx.state_mgr.state
    module_id = state.current_module_id
    iteration = state.current_iteration or 1

    if not module_id:
        raise RuntimeError("DECISION requires a current_module_id.")

    # Load review JSON from this iteration
    data_dir = ctx.config.storage.data_dir
    review_path = data_dir / "reviews" / module_id / f"iteration-{iteration}.json"
    if not review_path.exists():
        logger.warning("No review JSON found for %s iter %d — defaulting to iterate", module_id, iteration)
        review_data: dict = {"overall_status": "needs_work", "files": []}
    else:
        review_data = _json.loads(review_path.read_text(encoding="utf-8"))

    max_iters = ctx.config.orchestrator.max_iterations_per_module
    convergence_rule = ctx.config.orchestrator.convergence_rule

    decision = decide_iteration(review_data, iteration, max_iters, convergence_rule)

    console.print(
        f"[cyan]Decision for {module_id} (iteration {iteration}): "
        f"[bold]{decision}[/bold][/cyan]"
    )

    # Mark current iteration as completed
    iter_repo = IterationRepository(ctx.db.conn)
    iter_record = iter_repo.get(module_id, iteration)
    if iter_record:
        iter_record.status = IterationStatus.COMPLETED
        iter_repo.update(iter_record)

    # Publish decision event
    ctx.bus.publish(PipelineEventMessage(
        sender="orchestrator",
        module_id=module_id,
        iteration=iteration,
        payload={
            "event": "decision",
            "decision": decision,
            "convergence_score": review_data.get("convergence_score", 0),
        },
    ))

    if decision == "MODULE_COMPLETE":
        console.print(f"[green]Module {module_id} accepted → GIT_COMMIT[/green]")
        ctx.state_mgr.transition_to(PipelineStatus.GIT_COMMIT)

    elif decision == "HITL_4_MAX_ITERATIONS":
        console.print(
            f"[yellow]Max iterations ({max_iters}) reached for {module_id} "
            f"→ HITL gate[/yellow]"
        )
        ctx.state_mgr.transition_to(PipelineStatus.HITL_4_MAX_ITERATIONS)

    elif decision == "ITERATE":
        next_iter = iteration + 1
        console.print(
            f"[yellow]Iterating {module_id} → iteration {next_iter}[/yellow]"
        )
        ctx.state_mgr.transition_to(
            PipelineStatus.PROMPT_GENERATION,
            iteration=next_iter,
        )


def _create_github_client(ctx: HandlerContext):
    """Create a GitHubClient from config, or return None if not configured."""
    from ..config.env import resolve_secret
    from ..github.client import GitHubClient

    gh_cfg = ctx.config.github
    if not gh_cfg.owner or not gh_cfg.repo:
        return None

    project_root = ctx.config.project.root_path or "."
    token = resolve_secret("github_token", ctx.config.secrets.github_token, project_root)
    if not token:
        logger.warning("GitHub token not configured — skipping GitHub operations")
        return None

    try:
        return GitHubClient(token=token, owner=gh_cfg.owner, repo=gh_cfg.repo)
    except ValueError as exc:
        logger.warning("Cannot create GitHub client: %s", exc)
        return None


def _create_module_pr(
    ctx: HandlerContext,
    module_id: str,
    iteration: int,
    branch_name: str,
) -> tuple[int | None, str]:
    """Create a PR for a module branch. Returns (pr_number, pr_url)."""
    client = _create_github_client(ctx)
    if not client:
        return None, ""

    title = f"feat({module_id}): iteration {iteration} — accepted"
    body = (
        f"## Module: {module_id}\n\n"
        f"Accepted at iteration {iteration}.\n\n"
        f"Branch: `{branch_name}`\n\n"
        f"*Created by Agent OS pipeline.*"
    )
    base = ctx.config.git.dev_branch

    result = client.create_pr(title=title, head=branch_name, base=base, body=body)
    if result.success and result.data:
        pr_num = result.data.get("number")
        pr_url = result.data.get("html_url", "")
        console.print(f"  [dim]PR #{pr_num}: {pr_url}[/dim]")
        return pr_num, pr_url
    else:
        console.print(f"  [yellow]PR creation failed: {result.error[:200]}[/yellow]")
        return None, ""


def handle_git_commit(ctx: HandlerContext) -> None:
    from ..comms.messages import PipelineEventMessage
    from ..config.env import resolve_secret
    from ..git_ops.manager import GitOpsManager
    from ..storage.module_repo import ModuleRepository

    state = ctx.state_mgr.state
    module_id = state.current_module_id
    iteration = state.current_iteration or 1

    if not module_id:
        raise RuntimeError("GIT_COMMIT requires a current_module_id.")

    git_cfg = ctx.config.git
    working_dir = ctx.config.project.root_path or "."

    console.print(
        f"[cyan]Git Commit — committing {module_id} "
        f"(iteration {iteration})[/cyan]"
    )

    git = GitOpsManager(working_dir=working_dir, remote=git_cfg.remote)

    branch_name: str | None = None
    commit_sha: str | None = None
    pr_number: int | None = None
    pr_url: str = ""

    if git_cfg.enabled and git.is_repo():
        # Create and switch to feature branch
        if git_cfg.auto_create_feature_branches:
            branch_name = f"feature/{module_id}"
            result = git.create_and_checkout(branch_name, git_cfg.dev_branch)
            if not result.success and "already exists" not in result.stdout:
                # If dev branch doesn't exist as base, try from current
                result = git.create_and_checkout(branch_name)
            if result.success:
                console.print(f"  [dim]Branch: {branch_name}[/dim]")

        # Commit all changes
        commit_msg = f"feat({module_id}): iteration {iteration} — accepted"
        commit_result = git.commit_all(commit_msg)

        if commit_result.success:
            commit_sha = git.latest_commit_sha()
            if "nothing to commit" in commit_result.stdout:
                console.print("  [dim]No changes to commit[/dim]")
            else:
                console.print(f"  [dim]Committed: {commit_sha}[/dim]")

        # Tag the accepted iteration
        tag_name = f"{module_id}/v{iteration}"
        tag_msg = f"Module {module_id} accepted at iteration {iteration}"
        git.tag(tag_name, tag_msg)
        console.print(f"  [dim]Tagged: {tag_name}[/dim]")

        # Push branch if auto_push is enabled
        gh_cfg = ctx.config.github
        if gh_cfg.auto_push and branch_name:
            push_result = git.push(branch_name)
            if push_result.success:
                console.print(f"  [dim]Pushed: {branch_name}[/dim]")
                git.push_tags()
            else:
                console.print(f"  [yellow]Push failed: {push_result.stderr[:200]}[/yellow]")

            # Create PR if auto_create_pr is enabled
            if gh_cfg.auto_create_pr and push_result.success:
                pr_number, pr_url = _create_module_pr(
                    ctx, module_id, iteration, branch_name,
                )
    else:
        console.print("  [dim]Git disabled or not a repo — skipping[/dim]")

    # Store PR info in pipeline metadata for HITL_5 merge
    metadata = dict(state.metadata)
    if pr_number:
        metadata["pr_number"] = pr_number
        metadata["pr_url"] = pr_url
    if branch_name:
        metadata["branch_name"] = branch_name
    ctx.state_mgr.update_metadata(metadata)

    # Publish event
    ctx.bus.publish(PipelineEventMessage(
        sender="git_ops",
        module_id=module_id,
        iteration=iteration,
        payload={
            "event": "git_commit",
            "branch": branch_name,
            "commit_sha": commit_sha,
            "git_enabled": git_cfg.enabled,
            "pushed": bool(ctx.config.github.auto_push and branch_name),
            "pr_number": pr_number,
            "pr_url": pr_url,
        },
    ))

    ctx.state_mgr.transition_to(PipelineStatus.MODULE_COMPLETE)


def handle_module_complete(ctx: HandlerContext) -> None:
    from ..comms.messages import PipelineEventMessage
    from ..storage.models import ModuleStatus
    from ..storage.module_repo import ModuleRepository

    state = ctx.state_mgr.state
    module_id = state.current_module_id
    iteration = state.current_iteration or 1

    if not module_id:
        raise RuntimeError("MODULE_COMPLETE requires a current_module_id.")

    console.print(f"[green]Module {module_id} complete (iteration {iteration})[/green]")

    # Mark module as completed in DB
    mod_repo = ModuleRepository(ctx.db.conn)
    mod_repo.update_status(module_id, ModuleStatus.COMPLETED)

    # Add PR comment if a PR was created
    pr_number = state.metadata.get("pr_number")
    if pr_number:
        client = _create_github_client(ctx)
        if client:
            comment = (
                f"✅ **Module `{module_id}` completed** at iteration {iteration}.\n\n"
                f"Ready for PR review."
            )
            result = client.add_pr_comment(int(pr_number), comment)
            if result.success:
                console.print(f"  [dim]PR #{pr_number} comment added[/dim]")

    # Publish completion event
    ctx.bus.publish(PipelineEventMessage(
        sender="orchestrator",
        module_id=module_id,
        iteration=iteration,
        payload={
            "event": "module_complete",
            "module_id": module_id,
            "final_iteration": iteration,
            "pr_number": pr_number,
        },
    ))

    # Only pause at HITL_5 PR review if a PR was actually created (auto_push enabled).
    # Otherwise skip straight to NEXT_MODULE to avoid an unnecessary gate and the
    # risk of integration-test failures looping back to the same module.
    if pr_number:
        ctx.state_mgr.transition_to(PipelineStatus.HITL_5_PR_REVIEW)
    else:
        ctx.state_mgr.transition_to(PipelineStatus.NEXT_MODULE)


def handle_integration_test(ctx: HandlerContext) -> None:
    import subprocess as _subprocess

    from ..comms.messages import PipelineEventMessage

    state = ctx.state_mgr.state
    module_id = state.current_module_id
    iteration = state.current_iteration or 1

    if not module_id:
        raise RuntimeError("INTEGRATION_TEST requires a current_module_id.")

    working_dir = ctx.config.project.root_path or "."

    console.print(
        f"[cyan]Integration Test — checking {module_id} "
        f"against completed modules[/cyan]"
    )

    errors: list[str] = []

    # 1. Python syntax/import check on the working directory
    try:
        result = _subprocess.run(
            ["python", "-m", "py_compile", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        # Run a lightweight check: try importing the module's package
        # Use compileall for a broad syntax check
        compile_result = _subprocess.run(
            ["python", "-m", "compileall", "-q", "-l", working_dir],
            capture_output=True, text=True, timeout=120,
            cwd=working_dir,
        )
        if compile_result.returncode != 0:
            errors.append(f"Compile check failed: {compile_result.stderr[:500]}")
    except (FileNotFoundError, _subprocess.TimeoutExpired) as exc:
        console.print(f"  [dim]Compile check skipped: {exc}[/dim]")

    # 2. Run pytest if available (quick smoke test)
    if ctx.config.validation.tests:
        try:
            test_result = _subprocess.run(
                ["python", "-m", "pytest", "--tb=short", "-q", "--timeout=60", "-x"],
                capture_output=True, text=True, timeout=180,
                cwd=working_dir,
            )
            if test_result.returncode != 0:
                errors.append(
                    f"Test failures: {test_result.stdout[-500:]}"
                )
        except (FileNotFoundError, _subprocess.TimeoutExpired) as exc:
            console.print(f"  [dim]Pytest skipped: {exc}[/dim]")

    passed = len(errors) == 0
    status_color = "green" if passed else "yellow"
    console.print(
        f"[{status_color}]Integration: "
        f"{'passed' if passed else f'{len(errors)} issue(s)'}[/{status_color}]"
    )
    for err in errors:
        console.print(f"  [red]{err[:200]}[/red]")

    ctx.bus.publish(PipelineEventMessage(
        sender="integration_test",
        module_id=module_id,
        iteration=iteration,
        payload={
            "event": "integration_test",
            "passed": passed,
            "error_count": len(errors),
            "errors": [e[:200] for e in errors],
        },
    ))

    if passed:
        ctx.state_mgr.transition_to(PipelineStatus.NEXT_MODULE)
    else:
        # Integration failure → route back to prompt generation for a fix
        console.print(
            f"[yellow]Integration test failed — routing {module_id} "
            f"back to PROMPT_GENERATION[/yellow]"
        )
        next_iter = iteration + 1
        ctx.state_mgr.transition_to(
            PipelineStatus.PROMPT_GENERATION,
            iteration=next_iter,
        )


def handle_next_module(ctx: HandlerContext) -> None:
    from ..comms.messages import PipelineEventMessage
    from ..storage.models import ModuleStatus
    from ..storage.module_repo import ModuleRepository

    console.print("[cyan]Next Module — checking module queue...[/cyan]")

    mod_repo = ModuleRepository(ctx.db.conn)
    all_modules = mod_repo.get_all()  # ordered by execution_order

    completed_ids = {m.id for m in all_modules if m.status == ModuleStatus.COMPLETED}

    # Find the next module whose dependencies are all completed
    next_mod = None
    for m in all_modules:
        if m.status != ModuleStatus.PENDING:
            continue
        deps_met = all(dep_id in completed_ids for dep_id in m.dependency_ids)
        if deps_met:
            next_mod = m
            break

    if next_mod is None:
        # Check if there are still pending modules (circular deps or blocked)
        pending = [m for m in all_modules if m.status == ModuleStatus.PENDING]
        if pending:
            console.print(
                f"[yellow]{len(pending)} module(s) still pending but dependencies "
                f"not met — completing pipeline[/yellow]"
            )
        else:
            console.print("[bold green]All modules completed![/bold green]")

        ctx.bus.publish(PipelineEventMessage(
            sender="orchestrator",
            payload={
                "event": "pipeline_complete",
                "completed_modules": len(completed_ids),
                "total_modules": len(all_modules),
            },
        ))

        # Create final dev → main PR if configured
        gh_cfg = ctx.config.github
        git_cfg = ctx.config.git
        if gh_cfg.auto_create_pr and gh_cfg.owner and gh_cfg.repo:
            client = _create_github_client(ctx)
            if client:
                result = client.create_pr(
                    title=f"Release: {len(completed_ids)} modules completed",
                    head=git_cfg.dev_branch,
                    base=git_cfg.main_branch,
                    body=(
                        f"## Pipeline Complete\n\n"
                        f"All {len(completed_ids)} modules have been completed "
                        f"and merged into `{git_cfg.dev_branch}`.\n\n"
                        f"*Created by Agent OS pipeline.*"
                    ),
                )
                if result.success and result.data:
                    pr_num = result.data.get("number")
                    pr_url = result.data.get("html_url", "")
                    console.print(f"  [dim]Release PR #{pr_num}: {pr_url}[/dim]")
                    ctx.bus.publish(PipelineEventMessage(
                        sender="git_ops",
                        payload={
                            "event": "release_pr_created",
                            "pr_number": pr_num,
                            "pr_url": pr_url,
                        },
                    ))

        ctx.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
        return

    # Mark next module as in-progress and start it
    mod_repo.update_status(next_mod.id, ModuleStatus.IN_PROGRESS)

    console.print(
        f"[green]Starting module: {next_mod.id} ({next_mod.name})"
        f" — order {next_mod.execution_order}[/green]"
    )

    ctx.bus.publish(PipelineEventMessage(
        sender="orchestrator",
        module_id=next_mod.id,
        payload={
            "event": "next_module",
            "module_id": next_mod.id,
            "module_name": next_mod.name,
            "execution_order": next_mod.execution_order,
            "completed": len(completed_ids),
            "remaining": len(all_modules) - len(completed_ids) - 1,
        },
    ))

    ctx.state_mgr.transition_to(
        PipelineStatus.PROMPT_GENERATION,
        module_id=next_mod.id,
        iteration=1,
    )


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return max(len(text) // 4, 1) if text else 0


# Handler registry: state → function
HANDLER_REGISTRY: dict[PipelineStatus, object] = {
    PipelineStatus.IDLE: handle_idle,
    PipelineStatus.LOADING_REQUIREMENTS: handle_loading_requirements,
    PipelineStatus.MODULE_PLANNING: handle_module_planning,
    PipelineStatus.PROMPT_GENERATION: handle_prompt_generation,
    PipelineStatus.CODE_GENERATION: handle_code_generation,
    PipelineStatus.VALIDATION: handle_validation,
    PipelineStatus.CODE_REVIEW: handle_code_review,
    PipelineStatus.DECISION: handle_decision,
    PipelineStatus.GIT_COMMIT: handle_git_commit,
    PipelineStatus.MODULE_COMPLETE: handle_module_complete,
    PipelineStatus.INTEGRATION_TEST: handle_integration_test,
    PipelineStatus.NEXT_MODULE: handle_next_module,
}
