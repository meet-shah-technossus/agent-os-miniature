"""Diff fetcher — retrieves PR diff from VCS (Phase 11.2).

Encapsulates the logic to fetch a PR diff via the VCSClient, including
the fallback to per-file patches when the unified diff is empty.
"""
from __future__ import annotations

import logging
from typing import Callable

from ..vcs.base import VCSClient

logger = logging.getLogger(__name__)


def fetch_pr_context(
    gh: VCSClient,
    pr_number: int,
    emit: Callable[[str], None],
) -> tuple[str, str, dict]:
    """Fetch diff text, head SHA and basic PR metadata.

    Args:
        gh:        VCS client instance.
        pr_number: Pull request number.
        emit:      Callback for status messages.

    Returns:
        Tuple of (diff_text, head_sha, pr_data_dict).
    """
    emit(f"[code-reviewer] Fetching PR #{pr_number} diff …")

    diff_result = gh.get_pr_diff(pr_number)
    diff_text = (diff_result.data or {}).get("diff", "") if diff_result.success else ""

    # Fallback: build diff from per-file patches when unified diff is empty
    if not diff_text:
        emit("[code-reviewer] Unified diff empty — falling back to per-file patches")
        try:
            files_result = gh.get_pr_files(pr_number)
            if files_result.success and files_result.data:
                raw_files = files_result.data
                if isinstance(raw_files, dict):
                    raw_files = raw_files.get("files", raw_files.get("value", []))
                parts: list[str] = []
                for f in (raw_files or []):
                    fname = f.get("filename", "")
                    patch = f.get("patch", "")
                    if fname and patch:
                        parts.append(
                            f"diff --git a/{fname} b/{fname}\n"
                            f"--- a/{fname}\n+++ b/{fname}\n{patch}"
                        )
                if parts:
                    diff_text = "\n".join(parts)
                    emit(f"[code-reviewer] Built diff from {len(parts)} file patch(es) ({len(diff_text)} chars)")
        except Exception:
            logger.debug("[code-reviewer] Per-file fallback failed", exc_info=True)

    if not diff_text:
        emit("[code-reviewer] Warning: could not fetch PR diff — review will have no code context")

    pr_result = gh.get_pr(pr_number)
    pr_data = pr_result.data or {} if pr_result.success else {}
    head_sha = (pr_data.get("head") or {}).get("sha", "")

    if not head_sha:
        head_sha = gh.get_pr_head_sha(pr_number) or ""

    emit(f"[code-reviewer] Diff fetched ({len(diff_text)} chars), head SHA: {head_sha[:8] or 'unknown'}")
    return diff_text, head_sha, pr_data
