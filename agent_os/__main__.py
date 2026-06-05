"""Allow running as: python -m agent_os"""

from agent_os.logging_config import configure_logging

configure_logging()

from agent_os.orchestrator.cli import main

main()
