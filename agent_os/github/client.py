"""GitHub REST API client — thin wrapper for push, PR, and comment operations.

Uses httpx for HTTP calls. All methods are synchronous (matching the rest of
the Agent OS pipeline). Requires a resolved GitHub token.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_TIMEOUT = 30.0
_MAX_RETRIES = 2
_BACKOFF_BASE = 1.0


@dataclass
class GitHubResult:
    """Result of a GitHub API operation."""
    success: bool
    status_code: int = 0
    data: dict[str, Any] | None = None
    error: str = ""


class GitHubClient:
    """Minimal GitHub REST API client for Agent OS pipeline operations.

    Supports: create PR, add PR comment, merge PR, get PR.
    Push is handled by GitOpsManager (local git push subprocess).
    """

    def __init__(self, token: str, owner: str, repo: str) -> None:
        if not token:
            raise ValueError("GitHub token is required")
        if not owner or not repo:
            raise ValueError("GitHub owner and repo are required")
        self._token = token
        self._owner = owner
        self._repo = repo
        self._base_url = f"{_GITHUB_API}/repos/{owner}/{repo}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        absolute_url: str = "",
    ) -> GitHubResult:
        """Make an HTTP request with retry logic."""
        url = absolute_url or f"{self._base_url}{path}"

        for attempt in range(_MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=_TIMEOUT) as client:
                    response = client.request(
                        method, url, headers=self._headers(), json=json_body,
                    )

                if response.status_code == 422:
                    # Validation error — don't retry
                    data = response.json() if response.content else {}
                    msg = data.get("message", response.text[:200])
                    return GitHubResult(
                        success=False, status_code=422,
                        data=data, error=msg,
                    )

                if response.status_code >= 500 and attempt < _MAX_RETRIES:
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "GitHub API %d on %s %s — retrying in %.1fs",
                        response.status_code, method, path, wait,
                    )
                    time.sleep(wait)
                    continue

                if response.status_code >= 400:
                    data = response.json() if response.content else {}
                    msg = data.get("message", response.text[:200])
                    return GitHubResult(
                        success=False, status_code=response.status_code,
                        data=data, error=msg,
                    )

                data = response.json() if response.content else {}
                return GitHubResult(
                    success=True, status_code=response.status_code, data=data,
                )

            except httpx.TimeoutException:
                if attempt < _MAX_RETRIES:
                    time.sleep(_BACKOFF_BASE * (2 ** attempt))
                    continue
                return GitHubResult(success=False, error="Request timed out")
            except httpx.HTTPError as exc:
                if attempt < _MAX_RETRIES:
                    time.sleep(_BACKOFF_BASE * (2 ** attempt))
                    continue
                return GitHubResult(success=False, error=str(exc))

        return GitHubResult(success=False, error="Max retries exceeded")

    # ── PR operations ─────────────────────────────────────────────

    def create_pr(
        self,
        title: str,
        head: str,
        base: str,
        body: str = "",
    ) -> GitHubResult:
        """Create a pull request.

        Args:
            title: PR title.
            head: Head branch (the feature branch).
            base: Base branch to merge into.
            body: PR description body.

        Returns:
            GitHubResult with data containing PR number in data["number"].
        """
        logger.info("Creating PR: %s (%s → %s)", title, head, base)
        return self._request("POST", "/pulls", {
            "title": title,
            "head": head,
            "base": base,
            "body": body,
        })

    def get_pr(self, pr_number: int) -> GitHubResult:
        """Get details of a pull request."""
        return self._request("GET", f"/pulls/{pr_number}")

    def merge_pr(
        self,
        pr_number: int,
        merge_method: str = "squash",
        commit_message: str = "",
    ) -> GitHubResult:
        """Merge a pull request.

        Args:
            pr_number: PR number to merge.
            merge_method: One of "merge", "squash", "rebase".
            commit_message: Optional custom commit message.
        """
        logger.info("Merging PR #%d via %s", pr_number, merge_method)
        body: dict[str, Any] = {"merge_method": merge_method}
        if commit_message:
            body["commit_message"] = commit_message
        return self._request("PUT", f"/pulls/{pr_number}/merge", body)

    def add_pr_comment(self, pr_number: int, body: str) -> GitHubResult:
        """Add a comment on a PR (uses the issues API)."""
        logger.info("Adding comment to PR #%d", pr_number)
        return self._request("POST", f"/issues/{pr_number}/comments", {
            "body": body,
        })

    def close_pr(self, pr_number: int) -> GitHubResult:
        """Close a pull request without merging."""
        return self._request("PATCH", f"/pulls/{pr_number}", {
            "state": "closed",
        })

    # ── Repository operations ─────────────────────────────────────

    def create_repo(self, name: str, description: str = "", private: bool = False) -> GitHubResult:
        """Create a new GitHub repository under the authenticated user's account.

        Args:
            name: Repository name.
            description: Short description.
            private: Whether the repo is private.

        Returns:
            GitHubResult with data containing clone_url, html_url, full_name.
        """
        logger.info("Creating GitHub repo: %s", name)
        return self._request(
            "POST", "", json_body={
                "name": name,
                "description": description,
                "private": private,
                "auto_init": False,
            },
            absolute_url=f"{_GITHUB_API}/user/repos",
        )

    def repo_exists(self) -> bool:
        """Check if the configured owner/repo exists on GitHub."""
        result = self._request("GET", "")
        return result.success
