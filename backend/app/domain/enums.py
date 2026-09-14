"""Domain enumerations shared by the ORM models and the domain services.

These are persisted as VARCHAR with a CHECK constraint rather than as native
PostgreSQL enum types. Adding or renaming a value then costs a drop-and-recreate
of the constraint inside an ordinary transactional migration, where ALTER TYPE
on a native enum is awkward to reverse and cannot be rolled back cleanly.
"""

from enum import StrEnum


class RoleType(StrEnum):
    """Position in the organization.

    Authority comes from the hierarchy and the superadmin flag, not from this
    value -- it is a label for display and for coarse default rules. The
    permission engine must never branch on it alone.
    """

    MEMBER = "MEMBER"
    LEAD = "LEAD"
    VP = "VP"
    PRESIDENT = "PRESIDENT"


class MembershipStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class MessagingChannel(StrEnum):
    """Transports a person can reach Jenie through.

    iMessage is the only one implemented. The column exists from the start
    because the same phone number can be both an iMessage and an SMS address,
    and they are different identities.
    """

    IMESSAGE = "IMESSAGE"
    SMS = "SMS"


class WorkItemType(StrEnum):
    """Levels of the work tree.

    Strictly nested: an initiative holds responsibilities, a responsibility
    holds tasks. Keeping tasks off the initiative means every leaf sits under a
    responsibility, which is what makes progress reporting a simple count.
    """

    INITIATIVE = "INITIATIVE"
    RESPONSIBILITY = "RESPONSIBILITY"
    TASK = "TASK"


class WorkItemStatus(StrEnum):
    """Lifecycle of a work item.

    BLOCKED is deliberately absent. Blockers are out of MVP scope; adding the
    value later is a CHECK constraint change, which is why these are not native
    PostgreSQL enums.
    """

    ACTIVE = "ACTIVE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class TaskEventType(StrEnum):
    """Entries in a work item's immutable history.

    Only values Jenie actually emits are listed. An event type nothing writes is
    a lie about what the history can contain.
    """

    WORK_CREATED = "WORK_CREATED"
    ASSIGNED = "ASSIGNED"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
