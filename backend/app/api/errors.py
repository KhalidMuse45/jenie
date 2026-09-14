"""Turning domain exceptions into responses a person can read.

Handlers are registered once, so no route repeats this mapping and no domain
service has to know about HTTP. The message carried by each exception is written
for a person -- it goes into the envelope unchanged, because the messaging layer
will eventually relay it verbatim over iMessage.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.envelope import fail
from app.domain.delegation import (
    InvalidPlanState,
    PlanChanged,
    PlanNotEditable,
    PlanNotFound,
    PlanNotReady,
)
from app.domain.permissions import PermissionDenied
from app.domain.work import InvalidStructure, InvalidTransition

#: Exception -> (status, code). Order is irrelevant; each type is registered
#: individually so a subclass never silently picks up the wrong mapping.
_MAPPING = {
    PermissionDenied: (status.HTTP_403_FORBIDDEN, "permission_denied"),
    PlanNotFound: (status.HTTP_404_NOT_FOUND, "not_found"),
    PlanChanged: (status.HTTP_409_CONFLICT, "plan_changed"),
    InvalidPlanState: (status.HTTP_409_CONFLICT, "invalid_state"),
    PlanNotEditable: (status.HTTP_409_CONFLICT, "not_editable"),
    InvalidTransition: (status.HTTP_409_CONFLICT, "invalid_transition"),
    PlanNotReady: (status.HTTP_422_UNPROCESSABLE_CONTENT, "not_ready"),
    InvalidStructure: (status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_structure"),
}


def register_error_handlers(app: FastAPI) -> None:
    for exception_type, (http_status, code) in _MAPPING.items():
        app.add_exception_handler(exception_type, _handler_for(http_status, code))


def _handler_for(http_status: int, code: str):
    async def handler(request: Request, exception: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=http_status,
            content=fail(code, str(exception)),
        )

    return handler
