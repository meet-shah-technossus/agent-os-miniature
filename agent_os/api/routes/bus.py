"""Bus history route — retrieve recent comm bus messages."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from ...comms.channels import Channel
from ..deps import get_orchestrator
from ..schemas import BusMessageResponse

router = APIRouter(prefix="/api/bus", tags=["bus"])


@router.get("/history", response_model=list[BusMessageResponse])
def get_bus_history(
    channel: Optional[str] = Query(None, description="Filter by channel name"),
    orch=Depends(get_orchestrator),
):
    if channel:
        try:
            ch = Channel(channel)
        except ValueError:
            return []
        messages = orch.bus.history_for_channel(ch)
    else:
        messages = orch.bus.history

    return [
        BusMessageResponse(
            channel=msg.channel.value if hasattr(msg.channel, "value") else str(msg.channel),
            sender=msg.sender,
            timestamp=msg.timestamp,
            module_id=msg.module_id,
            iteration=msg.iteration,
            correlation_id=msg.correlation_id,
            payload=msg.payload,
        )
        for msg in messages
    ]
