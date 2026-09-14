"""The delegation plan state machine.

    DRAFT ──submit──> PENDING_APPROVAL ──approve──> APPROVED
                              │
                              └──reject───────────> REJECTED

APPROVED and REJECTED are terminal. An approved plan is history: it records what
was agreed to, and rewriting it would rewrite the reason the work exists.
"""

from app.domain.enums import DelegationPlanStatus

P = DelegationPlanStatus

PLAN_TRANSITIONS: frozenset[tuple[P, P]] = frozenset(
    {
        (P.DRAFT, P.PENDING_APPROVAL),
        (P.PENDING_APPROVAL, P.APPROVED),
        (P.PENDING_APPROVAL, P.REJECTED),
    }
)

#: States in which a plan's contents may still change. Who may change them
#: differs by state, and that is the permission engine's business:
#: the creator owns a draft, the approver owns it once it has been sent to them.
EDITABLE_STATUSES: frozenset[P] = frozenset({P.DRAFT, P.PENDING_APPROVAL})

TERMINAL_STATUSES: frozenset[P] = frozenset({P.APPROVED, P.REJECTED})
