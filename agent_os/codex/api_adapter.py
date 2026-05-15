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
    copilot   https://models.inference.ai.azure.com                     GITHUB_TOKEN
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
        "https://models.inference.ai.azure.com",
        "GITHUB_TOKEN",
        "gpt-4o",
    ),
}


def stream_chat(tool: str, model: str, prompt: str) -> int:
    """Call an OpenAI-compatible endpoint and stream tokens to stdout.

    Returns 0 on success, non-zero on failure.
    """
    if tool not in TOOL_ENDPOINTS:
        print(f"Error: unknown api_adapter tool '{tool}'", file=sys.stderr)
        return 1

    base_url, env_key, default_model = TOOL_ENDPOINTS[tool]
    api_key = os.environ.get(env_key, "")
    if not api_key:
        print(
            f"Error: {env_key} is not set. "
            f"Configure credentials for {tool} in Settings \u2192 AI Tools.",
            file=sys.stderr,
        )
        return 1

    model = model or default_model

    try:
        from openai import OpenAI
    except ImportError:
        print(
            "Error: the 'openai' package is required for the API adapter. "
            "Install it with: pip install openai",
            file=sys.stderr,
        )
        return 1

    client = OpenAI(api_key=api_key, base_url=base_url)

    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
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
        print(f"\nError calling {tool} API ({base_url}): {exc}", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OpenAI-compatible API adapter for Agent OS",
    )
    parser.add_argument("--tool", required=True, choices=sorted(TOOL_ENDPOINTS))
    parser.add_argument("--model", default="")
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args()
    sys.exit(stream_chat(args.tool, args.model, args.prompt))


if __name__ == "__main__":
    main()
