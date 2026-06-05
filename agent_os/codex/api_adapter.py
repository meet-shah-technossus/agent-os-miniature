"""Unified OpenAI-compatible API adapter for LLM tools without native CLIs.

Invoked as a subprocess by the codex wrapper, streaming tokens to stdout
so the existing terminal / streaming architecture works unchanged.

Usage::

    python -m agent_os.codex.api_adapter \
        --tool deepseek --model deepseek-coder \
        --prompt "Refactor the auth module…"

Supported tools and their default endpoints:

    deepseek  https://api.deepseek.com/v1                               DEEPSEEK_API_KEY
    gemini    https://generativelanguage.googleapis.com/v1beta/openai    GEMINI_API_KEY
    qwen      https://dashscope.aliyuncs.com/compatible-mode/v1         DASHSCOPE_API_KEY
    copilot   https://api.githubcopilot.com                             GITHUB_TOKEN
"""

from __future__ import annotations

import argparse
import os
import sys

# (base_url, env_var_for_api_key, default_model)
TOOL_ENDPOINTS: dict[str, tuple[str, str, str]] = {
    "deepseek": (
        "https://api.deepseek.com/v1",
        "DEEPSEEK_API_KEY",
        "deepseek-coder",
    ),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        "gemini-2.0-flash",
    ),
    "qwen": (
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "DASHSCOPE_API_KEY",
        "qwen-coder-plus",
    ),
    "copilot": (
        "https://api.githubcopilot.com",
        "GITHUB_TOKEN",
        "gpt-4o",  # gpt-4o is universally available on all Copilot plans
    ),
}


def _sanitize_model_name(model: str) -> str:
    """Clean a model name for use with the Copilot / GitHub Models API.

    Handles:
    - AzureML registry URIs:  ``azureml://registries/.../models/gpt-4o/versions/2``
      → ``gpt-4o``
    - Date-versioned names:   ``gpt-4.1-2025-04-14`` → ``gpt-4.1``
                              ``claude-3-5-haiku-20241022`` → ``claude-3-5-haiku``
    - Anthropic dot notation: ``claude-haiku-4.5`` → ``claude-haiku-4-5``
      (GitHub Copilot API uses hyphens, not dots, in Anthropic version numbers)
    """
    import re as _re
    if model.startswith("azureml://"):
        m = _re.search(r"/models/([^/]+)/versions/", model)
        if m:
            model = m.group(1)
    # Strip date-version suffixes: -2025-04-14 (YYYY-MM-DD) or -20241022 (YYYYMMDD)
    model = _re.sub(r'-\d{4}-\d{2}-\d{2}$', '', model)
    model = _re.sub(r'-\d{8}$', '', model)
    # Anthropic models: normalize dot-separated version numbers to hyphens
    # e.g. claude-haiku-4.5 → claude-haiku-4-5
    if model.startswith('claude-'):
        model = _re.sub(r'(\d)\.(\d)', r'\1-\2', model)
    return model


# Models to try in order when the configured model is not available (404/400)
_COPILOT_FALLBACK_MODELS: list[str] = ["gpt-4o", "gpt-4o-mini"]


def _get_copilot_token() -> str:
    """Return a GitHub token for the Copilot API.

    Priority:
    1. ``gh auth token`` — the token stored by the gh CLI keychain.
    2. ``GITHUB_TOKEN`` env var — PAT or token configured in Settings.

    IMPORTANT: ``gh`` echoes back GITHUB_TOKEN/GH_TOKEN if they are present
    in its environment instead of reading the stored credential.  We
    must strip those vars before invoking ``gh auth token``.
    """
    try:
        import shutil as _shutil
        import subprocess as _sp
        # Resolve gh binary — on Windows the server may have a restricted PATH
        gh_exe = _shutil.which("gh")
        if not gh_exe and sys.platform == "win32":
            try:
                _r = _sp.run(["where.exe", "gh"], capture_output=True, text=True, timeout=5)
                if _r.returncode == 0:
                    gh_exe = _r.stdout.strip().splitlines()[0].strip()
            except Exception:
                pass
        gh_exe = gh_exe or "gh"
        # Strip PAT vars so gh reads its own keychain credential
        clean_env = {
            k: v for k, v in os.environ.items()
            if k not in ("GITHUB_TOKEN", "GH_TOKEN")
        }
        result = _sp.run(
            [gh_exe, "auth", "token"],
            capture_output=True, text=True, timeout=5,
            env=clean_env,
        )
        token = (result.stdout or result.stderr or "").strip().splitlines()[0].strip() if result.returncode == 0 else ""
        if token:
            return token
    except Exception:
        pass
    # Fall back to env var
    return os.environ.get("GITHUB_TOKEN", "")


def _exchange_for_copilot_session_token(github_token: str) -> str:
    """Exchange a GitHub token (PAT or OAuth) for a short-lived Copilot API session token.

    ``api.githubcopilot.com`` rejects raw PATs with "Personal Access Tokens are not
    supported for this endpoint".  The solution is to first exchange the GitHub token
    for a Copilot session token via ``api.github.com/copilot_internal/v2/token``.
    The returned token starts with ``tid=`` and is accepted by the Copilot API.

    This works for:
    - GitHub OAuth tokens (``gho_``) from ``gh auth login --web``
    - Classic PATs (``ghp_``) with Copilot/API access
    - Fine-grained PATs (``github_pat_``) with appropriate permissions

    Returns the session token string, or empty string if the exchange fails.
    """
    if not github_token:
        return ""
    try:
        import urllib.request as _ur
        import json as _json
        req = _ur.Request(
            "https://api.github.com/copilot_internal/v2/token",
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/json",
                "User-Agent": "GitHubCopilotChat/0.26.7",
                "Editor-Version": "vscode/1.87.2",
                "Editor-Plugin-Version": "copilot-chat/0.26.7",
                "Openai-Organization": "github-copilot",
            },
        )
        with _ur.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
            session_token = data.get("token", "")
            if session_token:
                return session_token
    except Exception:
        pass
    return ""


def stream_chat(tool: str, model: str, prompt: str) -> int:
    """Call an OpenAI-compatible endpoint and stream tokens to stdout.

    Returns 0 on success, non-zero on failure.
    """
    # On Windows the default stdout encoding is cp1252 which cannot represent
    # many Unicode characters (box-drawing, emoji, …) returned by LLM APIs.
    # Reconfigure both streams to UTF-8 so output is never corrupted/aborted.
    import io as _io
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    elif hasattr(sys.stdout, "buffer"):
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    if tool not in TOOL_ENDPOINTS:
        print(f"Error: unknown api_adapter tool '{tool}'", file=sys.stderr)
        return 1

    base_url, env_key, default_model = TOOL_ENDPOINTS[tool]
    if tool == "copilot":
        github_token = _get_copilot_token()
        if not github_token:
            print(
                "Error: No GitHub token found. "
                "Run 'gh auth login --web' or set GITHUB_TOKEN in Settings → AI Tools.",
                file=sys.stderr,
            )
            return 1
        # Exchange the GitHub token (PAT or OAuth) for a short-lived Copilot session
        # token.  api.githubcopilot.com rejects raw PATs; the session token works
        # regardless of whether the source token is a PAT or an OAuth token.
        session_token = _exchange_for_copilot_session_token(github_token)
        if session_token:
            api_key = session_token
            # base_url stays as api.githubcopilot.com
        else:
            # Exchange failed (token may lack Copilot scope, or network issue).
            # Fall back to GitHub Models marketplace which accepts PATs directly.
            api_key = github_token
            base_url = "https://models.inference.ai.azure.com"
    else:
        api_key = os.environ.get(env_key, "")
    if not api_key:
        print(
            f"Error: {env_key} is not set. "
            f"Configure credentials for {tool} in Settings \u2192 AI Tools.",
            file=sys.stderr,
        )
        return 1

    # Sanitize model name — strip date suffixes, AzureML URIs, normalize Anthropic notation
    model = _sanitize_model_name(model or default_model)

    try:
        from openai import OpenAI
    except ImportError:
        print(
            "Error: the 'openai' package is required for the API adapter. "
            "Install it with: pip install openai",
            file=sys.stderr,
        )
        return 1

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        # GitHub Copilot API requires these headers to identify the integration.
        # Without them, newer/codex models return "not accessible via /chat/completions".
        default_headers={
            "Copilot-Integration-Id": "agent-os",
            "Editor-Version": "agent-os/1.0",
            "Editor-Plugin-Version": "agent-os/1.0",
        } if tool == "copilot" else {},
    )

    # For the Copilot tool, build a fallback model list so we gracefully handle
    # models that are not available on the user's subscription plan (404) or
    # have an unrecognised name format (400 unknown_model).
    models_to_try: list[str] = [model]
    if tool == "copilot":
        for fb in _COPILOT_FALLBACK_MODELS:
            if fb != model:
                models_to_try.append(fb)

    last_exc: Exception | None = None
    for attempt_model in models_to_try:
        try:
            stream = client.chat.completions.create(
                model=attempt_model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            if attempt_model != model:
                print(
                    f"[copilot] Model '{model}' unavailable — using '{attempt_model}' instead.",
                    file=sys.stderr,
                )
            for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        sys.stdout.write(delta.content)
                        sys.stdout.flush()
            sys.stdout.write("\n")
            sys.stdout.flush()
            return 0
        except Exception as exc:
            exc_str = str(exc)
            # Retry on model-not-found errors; propagate all others immediately
            is_retryable = any(
                k in exc_str.lower() for k in (
                    "unknown_model", "unknown model", "model_not_found",
                    "resource not found", "404", "not found", "not accessible",
                    "not available for integrator",
                )
            )
            if is_retryable and attempt_model != models_to_try[-1]:
                print(
                    f"[copilot] Model '{attempt_model}' not available ({exc_str[:120]}), trying next fallback...",
                    file=sys.stderr,
                )
                last_exc = exc
                continue
            last_exc = exc
            break

    exc = last_exc  # type: ignore[assignment]
    print(f"\nError calling {tool} API ({base_url}): {exc}", file=sys.stderr)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OpenAI-compatible API adapter for Agent OS",
    )
    parser.add_argument("--tool", required=True, choices=sorted(TOOL_ENDPOINTS))
    parser.add_argument("--model", default="")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--stdin", action="store_true",
                        help="Read prompt from stdin instead of --prompt (avoids Windows cmd-line length limit)")
    args = parser.parse_args()

    prompt = args.prompt
    if args.stdin:
        prompt = sys.stdin.read()

    if not prompt:
        print("Error: no prompt provided (use --prompt or --stdin)", file=sys.stderr)
        sys.exit(1)

    sys.exit(stream_chat(args.tool, args.model, prompt))


if __name__ == "__main__":
    main()
