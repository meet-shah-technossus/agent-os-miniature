"""Phase 1 — patch wrapper.py naming + code_generator/runner.py naming."""
from pathlib import Path


def patch_wrapper():
    path = Path("agent_os/codex/wrapper.py")
    c = path.read_text(encoding="utf-8")

    # _exe → _executable_name
    c = c.replace("_exe = executable_name(tool)", "_executable_name = executable_name(tool)")
    c = c.replace("_exe, proc.pid", "_executable_name, proc.pid")
    c = c.replace("'%s' CLI not found. Is it installed and on PATH?\", _exe",
                  "'%s' CLI not found. Is it installed and on PATH?\", _executable_name")
    c = c.replace("\"Unexpected error running %s CLI\", _exe",
                  '"Unexpected error running %s CLI", _executable_name')

    # _stream_bytes param names
    c = c.replace("def _stream_bytes(pipe, buf, cb):",
                  "def _stream_bytes(output_pipe, line_buffer, callback):")
    c = c.replace("for raw in pipe:", "for raw in output_pipe:")
    c = c.replace("buf.append(line)", "line_buffer.append(line)")
    c = c.replace("if cb:", "if callback:")
    c = c.replace("cb(line)", "callback(line)")

    path.write_text(c, encoding="utf-8")
    print("wrapper.py patched")


def patch_code_generator_runner():
    path = Path("agent_os/code_generator/runner.py")
    c = path.read_text(encoding="utf-8")

    # _tool → _cli_tool_name (only the local variable, not cli_tool or _cg_tool)
    c = c.replace(
        "_tool = self._codex._cli_routing.get(SessionType.CODE_GENERATOR.value, \"codex\")",
        "_cli_tool_name = self._codex._cli_routing.get(SessionType.CODE_GENERATOR.value, \"codex\")",
    )
    c = c.replace(
        "prompt_text = self._build_prompt(prompt_path, iteration, api_tool=_tool in API_TOOLS)",
        "prompt_text = self._build_prompt(prompt_path, iteration, api_tool=_cli_tool_name in API_TOOLS)",
    )

    path.write_text(c, encoding="utf-8")
    print("code_generator/runner.py patched")


if __name__ == "__main__":
    patch_wrapper()
    patch_code_generator_runner()
    print("All patches applied.")


