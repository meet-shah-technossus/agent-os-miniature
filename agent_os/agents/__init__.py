"""agent_os.agents — Agent identity file system."""

from .brain import BrainUpdater
from .context import IdentityContextInjector
from .store import (
    AGENT_FILES,
    BUILTIN_AGENTS,
    AgentIdentityStore,
    AgentNotFoundError,
    AgentRegistry,
)

__all__ = [
    "AgentIdentityStore",
    "AgentNotFoundError",
    "AgentRegistry",
    "AgentFiles",
    "AGENT_FILES",
    "BUILTIN_AGENTS",
    "BrainUpdater",
    "IdentityContextInjector",
]
