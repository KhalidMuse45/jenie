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
