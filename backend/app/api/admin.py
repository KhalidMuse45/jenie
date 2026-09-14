"""Operational views.

Not part of the product. These exist so that a person running Jenie can see what
it is about to do, which matters most before there is any delivery at all.
"""

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import ActorDep, SessionDep
from app.api.envelope import ok
from app.api.schemas import OutboundMessageOut
from app.database.models import OutboundMessage
from app.domain.permissions import Action, require

router = APIRouter(tags=["admin"])


@router.get("/outbound-messages")
async def list_outbound(
    session: SessionDep,
    actor: ActorDep,
    limit: int = Query(default=50, le=200),
) -> dict[str, Any]:
    """The notification queue, newest first."""
    require(actor, Action.VIEW_ORGANIZATION_WORK)

    messages = await session.scalars(
        select(OutboundMessage)
        .where(OutboundMessage.organization_id == actor.organization_id)
        .order_by(OutboundMessage.created_at.desc())
        .limit(limit)
    )
    return ok(
        [OutboundMessageOut.model_validate(message).model_dump(mode="json") for message in messages]
    )
