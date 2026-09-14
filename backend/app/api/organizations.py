"""Reading the organization."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import ActorDep, SessionDep
from app.api.envelope import ok
from app.api.schemas import MemberOut, RelatedMemberOut
from app.database.models import Membership
from app.domain.organizations.graph import OrgGraph
from app.domain.permissions import Action, require, subject_for

router = APIRouter(tags=["organization"])


@router.get("/organizations/{organization_id}/members")
async def list_members(
    organization_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    require(actor, Action.VIEW_ORGANIZATION_WORK)

    if organization_id != actor.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such organization.")

    members = await session.scalars(
        select(Membership)
        .where(Membership.organization_id == organization_id)
        .order_by(Membership.created_at)
    )
    return ok([MemberOut.model_validate(member).model_dump(mode="json") for member in members])


@router.get("/members/{membership_id}/descendants")
async def list_descendants(
    membership_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    member = await session.get(Membership, membership_id)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such membership.")

    require(actor, Action.VIEW_MEMBER_WORK, subject_for(member))

    below = await OrgGraph(session).descendants(membership_id)
    return ok(
        [
            RelatedMemberOut(membership_id=related.membership_id, depth=related.depth).model_dump(
                mode="json"
            )
            for related in below
        ]
    )
