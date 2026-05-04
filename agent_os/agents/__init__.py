"""agent_os.agents — Agent identity file system."""

from .context import IdentityContextInjector
from .store import AgentIdentityStore, AgentNotFoundError, AgentRegistry, AGENT_FILES, BUILTIN_AGENTS

__all__ = [
    "AgentIdentityStore",
    "AgentNotFoundError",
    "AgentRegistry",
    "AgentFiles",
    "AGENT_FILES",
    "BUILTIN_AGENTS",
    "IdentityContextInjector",
]
