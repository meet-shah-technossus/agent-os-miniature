"""Agent Communication Bus — parallel message passing between all agents.

Provides pub/sub with typed channels. Any agent can publish messages
and any agent can subscribe to relevant channels. Thread-safe.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Callable

from .channels import Channel
from .messages import AgentMessage

logger = logging.getLogger(__name__)

MessageCallback = Callable[[AgentMessage], None]


class AgentCommBus:
    """Parallel message bus for agent-to-agent communication.

    Thread-safe pub/sub. Subscribers are called synchronously on the
    publisher's thread for Phase 1. Phase 3 will add asyncio queues.
    """

    def __init__(self) -> None:
        self._subscribers: dict[Channel, list[MessageCallback]] = defaultdict(list)
        self._message_log: list[AgentMessage] = []
        self._lock = threading.Lock()

    def subscribe(self, channel: Channel, callback: MessageCallback) -> None:
        """Register a callback for messages on a channel."""
        with self._lock:
            self._subscribers[channel].append(callback)
            logger.debug("Subscriber added to channel %s", channel.value)

    def unsubscribe(self, channel: Channel, callback: MessageCallback) -> None:
        """Remove a callback from a channel."""
        with self._lock:
            try:
                self._subscribers[channel].remove(callback)
            except ValueError:
                pass

    def publish(self, message: AgentMessage) -> None:
        """Publish a message to its channel. All subscribers are notified."""
        with self._lock:
            self._message_log.append(message)
            callbacks = list(self._subscribers.get(message.channel, []))

        for cb in callbacks:
            try:
                cb(message)
            except Exception:
                logger.exception(
                    "Error in subscriber for channel %s", message.channel.value
                )

    @property
    def history(self) -> list[AgentMessage]:
        """Return all messages published so far."""
        with self._lock:
            return list(self._message_log)

    def history_for_channel(self, channel: Channel) -> list[AgentMessage]:
        """Return all messages for a specific channel."""
        with self._lock:
            return [m for m in self._message_log if m.channel == channel]
