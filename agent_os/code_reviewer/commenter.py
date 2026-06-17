"""PR commenter — posts review comments to VCS (Phase 11.3).

Handles inline (line-level) comments, global (architecture/structure) comments,
summary posting, and PR finalization (merge + branch delete).
"""
from __future__ import annotations

import logging
from typing import Callable

from ..constants import FILE_LINE_LIMIT
from ..vcs.base import VCSClient
from .schema import ReviewJSON

logger = logging.getLogger(__name__)


def post_inline_comments(
    gh: VCSClient,
    pr_number: int,
    head_sha: str,
    review: ReviewJSON,
    emit: Callable[[str], None],
) -> int:
    """Post line-level review comments to the PR. Returns number of comments posted."""
    if not head_sha:
        emit("[code-reviewer] No head SHA — skipping inline comments")
        return 0

    count = 0
    for lc in review.line_comments:
        if not lc.file or lc.line <= 0:
            continue
        body = f"**[{lc.severity.upper()}] {lc.checklist_item}**: {lc.comment}"
        if lc.suggested_fix:
            body += f"\n\n> **Suggested fix**: {lc.suggested_fix}"
        r = gh.add_pr_review_comment(
            pr_number=pr_number,
            body=body,
            commit_id=head_sha,
            path=lc.file,
            line=lc.line,
        )
        if r.success:
            count += 1
        else:
            # Fall back: add as a global comment if inline placement fails
            fallback = gh.add_pr_comment(
                pr_number, f"\U0001f4dd **File `{lc.file}` line {lc.line}**: {body}"
            )
            if fallback.success:
                count += 1
            logger.debug(
                "Inline comment on %s:%d fell back to global: %s",
                lc.file, lc.line, r.error,
            )

    # File-size violations posted as inline global comments
    for fsv in review.file_size_violations:
        body = (
            f"\u26a0\ufe0f **File size violation**: `{fsv.file}` has **{fsv.line_count} lines** "
            f"(limit: {FILE_LINE_LIMIT}). Please split into smaller modules."
        )
        r = gh.add_pr_comment(pr_number, body)
        if r.success:
            count += 1

    emit(f"[code-reviewer] Posted {count} inline/size comment(s)")
    return count


def post_global_comments(
    gh: VCSClient,
    pr_number: int,
    review: ReviewJSON,
    emit: Callable[[str], None],
) -> int:
    """Post global (non-inline) PR comments for structural findings."""
    count = 0

    # Architecture issues
    for ai in review.architecture_issues:
        body = (
            f"\U0001f3d7\ufe0f **Architecture issue** [{ai.severity.upper()}] "
            f"(layer: `{ai.layer}`): {ai.description}"
        )
        r = gh.add_pr_comment(pr_number, body)
        if r.success:
            count += 1

    # Folder structure issues
    for fsi in review.folder_structure_issues:
        body = (
            f"\U0001f4c1 **Folder structure issue**: `{fsi.path}` \u2014 {fsi.issue}"
        )
        if fsi.expected_location:
            body += f"\n\n> Expected location: `{fsi.expected_location}`"
        r = gh.add_pr_comment(pr_number, body)
        if r.success:
            count += 1

    # General global comments
    for gc in review.global_comments:
        body = f"**[{gc.severity.upper()}] {gc.category}**: {gc.comment}"
        r = gh.add_pr_comment(pr_number, body)
        if r.success:
            count += 1

    # Summary comment
    score_lines = "\n".join(
        f"- **{k}**: {v}/100" for k, v in review.checklist_scores.items()
    )
    summary_body = (
        f"## \U0001f916 Agent OS Code Review \u2014 Iteration summary\n\n"
        f"**Overall status**: `{review.overall_status}`  \n"
        f"**Overall score**: {review.overall_score}/100\n\n"
        f"### Checklist scores\n{score_lines}\n\n"
        f"### Summary\n{review.summary}"
    )
    r = gh.add_pr_comment(pr_number, summary_body)
    if r.success:
        count += 1

    emit(f"[code-reviewer] Posted {count} global comment(s)")
    return count


def finalize_pr(
    gh: VCSClient,
    pr_number: int,
    feature_branch: str,
    emit: Callable[[str], None],
) -> tuple[bool, bool]:
    """Merge the PR and delete the feature branch. Returns (merged, branch_deleted)."""
    merged = False
    branch_deleted = False

    # 1. Merge PR
    merge_result = gh.merge_pr(pr_number, commit_message="Accepted by Agent OS code reviewer")
    if merge_result.success:
        emit(f"[code-reviewer] PR #{pr_number} merged to main \u2705")
        merged = True
    else:
        emit(f"[code-reviewer] PR merge failed: {merge_result.error}")

    # 2. Delete feature branch
    delete_result = gh.delete_branch(branch=feature_branch)
    if delete_result.success:
        emit(f"[code-reviewer] Feature branch '{feature_branch}' deleted \u2705")
        branch_deleted = True
    else:
        emit(f"[code-reviewer] Branch delete failed: {delete_result.error}")

    return merged, branch_deleted
