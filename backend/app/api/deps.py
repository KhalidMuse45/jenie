"""Request dependencies for the administrative API.

Two separate things happen here, and conflating them would be a mistake:

* **Authentication** -- a shared secret proving the caller may use this API at
  all. Compared in constant time.
* **Acting as** -- which membership the request is made on behalf of. This is
  impersonation, and it is deliberate: the administrative API exists to drive
  Jenie before iMessage does, so it has to be able to act as any member.

What that member may then *do* is not decided here. Every route still asks the
permission engine, so the token buys access to the API, never to an action.

The trade is explicit: anyone holding the token can act as anyone in the
organization. That is appropriate for an operator tool on an internal network
and inappropriate for anything public. When the token is unset these routes are
not mounted at all.
"""

import secrets
import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.session import get_db
from app.domain.permissions import Actor, load_actor

SessionDep = Annotated[AsyncSession, Depends(get_db)]


async def verify_admin_token(
    x_jenie_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    configured = get_settings().admin_api_token

    if not configured:
        # Should be unreachable: the router is not mounted without a token.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    if not x_jenie_admin_token or not secrets.compare_digest(x_jenie_admin_token, configured):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid administrative token.")


async def current_actor(
    session: SessionDep,
    x_jenie_actor: Annotated[uuid.UUID | None, Header()] = None,
) -> Actor:
    """The membership this request acts as."""
    if x_jenie_actor is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Name the membership to act as in the X-Jenie-Actor header.",
        )

    actor = await load_actor(session, x_jenie_actor)
    if actor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such membership.")

    return actor


ActorDep = Annotated[Actor, Depends(current_actor)]
